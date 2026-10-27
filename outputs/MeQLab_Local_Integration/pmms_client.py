"""A small stdio MCP client for the user-provided PMMS distribution."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone


class PmmsError(RuntimeError):
    pass


def beijing_now():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def result_text(result):
    return '\n'.join(item.get('text', '') for item in result.get('content', []) if item.get('type') == 'text')


class PmmsClient:
    def __init__(self, config_path, run_dir, export_root=None):
        self.config = json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
        self.run_dir = Path(run_dir).resolve()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.export_root = Path(export_root).resolve() if export_root is not None else self.run_dir
        self.events = self.run_dir / 'mcp_events.jsonl'
        self.stderr_path = self.run_dir / 'pmms_stderr.log'
        self.stdout_noise = self.run_dir / 'stdout_non_json.log'
        self.messages = queue.Queue()
        self.lock = threading.Lock()
        self.next_id = 1
        self.tool_calls = 0
        self.tool_successes = 0
        self.initialized = False
        self.proc = None
        self.threads = []
        self.tool_schemas = {}
        self.started = time.monotonic()

    def event(self, kind, **fields):
        record = {'time': beijing_now(), 'elapsed_seconds': round(time.monotonic() - self.started, 3), 'kind': kind, **fields}
        with self.lock, self.events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')

    @staticmethod
    def decode(data):
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return data.decode('gb18030', errors='replace')

    def start(self):
        cfg = self.config
        env = os.environ.copy()
        if cfg.get('license_document'):
            license_document = Path(cfg['license_document']).read_text(encoding='utf-8-sig')
            match = re.search(r'(?m)^\s*PRIMARIUS_LICENSE_FILE\s*=\s*([^\r\n]+)', license_document)
            if not match:
                raise PmmsError('License variable is absent from the local document')
            env['PRIMARIUS_LICENSE_FILE'] = match.group(1).strip()
        if not env.get('PRIMARIUS_LICENSE_FILE', '').strip():
            raise PmmsError('Set PRIMARIUS_LICENSE_FILE in this terminal or use a local license_document')
        temp = Path(cfg['runtime_root']) / 'temp'
        temp.mkdir(parents=True, exist_ok=True)
        env['TEMP'] = env['TMP'] = str(temp.resolve())
        env['PYTHONUTF8'] = '1'
        args = [cfg['pmms_path'], '--local', '--meqlab-path', cfg['meqlab_path'],
                '--feature', cfg['feature'], '--prjdir', cfg['project_path']]
        startup = None
        flags = 0
        if os.name == 'nt':
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = subprocess.SW_HIDE
            flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        self.event('launch', command=args, license_variable='PRIMARIUS_LICENSE_FILE', cwd=cfg['runtime_root'])
        self.proc = subprocess.Popen(args, cwd=cfg['runtime_root'], env=env, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     startupinfo=startup, creationflags=flags)
        self.event('process_started', pid=self.proc.pid)
        for target in (self._stdout_reader, self._stderr_reader):
            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            self.threads.append(thread)
        response = self.request('initialize', {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'gan-hemt-local-integration', 'version': '0.1.0'}
        }, timeout=cfg.get('initialize_timeout_seconds', 100))
        self.initialized = True
        self.notify('notifications/initialized')
        self.event('initialized', result=response)
        return response

    def _stdout_reader(self):
        try:
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    break
                text = self.decode(line).strip()
                if not text:
                    continue
                try:
                    message = json.loads(text)
                    if not isinstance(message, dict):
                        raise ValueError('Non-object JSON')
                except (ValueError, json.JSONDecodeError):
                    with self.stdout_noise.open('a', encoding='utf-8') as stream:
                        stream.write(text + '\n')
                    self.event('stdout_non_json', text=text[:1000])
                    continue
                self.messages.put(message)
        except Exception as error:
            self.event('stdout_reader_error', error=str(error))
        finally:
            self.messages.put({'_eof': True})

    def _stderr_reader(self):
        try:
            with self.stderr_path.open('a', encoding='utf-8') as stream:
                for line in iter(self.proc.stderr.readline, b''):
                    stream.write(self.decode(line))
                    stream.flush()
        except Exception as error:
            self.event('stderr_reader_error', error=str(error))

    def _send(self, message):
        if self.proc is None or self.proc.poll() is not None:
            raise PmmsError('PMMS is not running')
        self.proc.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        self.proc.stdin.flush()

    def notify(self, method, params=None):
        message = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            message['params'] = params
        self._send(message)
        self.event('notification_sent', message=message)

    def request(self, method, params=None, timeout=30):
        request_id = self.next_id
        self.next_id += 1
        message = {'jsonrpc': '2.0', 'id': request_id, 'method': method}
        if params is not None:
            message['params'] = params
        self.event('request', message=message)
        self._send(message)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.event('timeout', id=request_id, method=method, seconds=timeout)
                raise TimeoutError(f'{method} did not respond within {timeout} seconds')
            try:
                response = self.messages.get(timeout=min(remaining, 1))
            except queue.Empty:
                if self.proc.poll() is not None:
                    raise PmmsError(f'PMMS exited with status {self.proc.returncode}; see pmms_stderr.log')
                continue
            if response.get('_eof'):
                raise PmmsError(f'PMMS stdout closed; process status={self.proc.poll()}; see pmms_stderr.log')
            self.event('response', message=response)
            if response.get('id') != request_id:
                if 'method' in response and 'id' not in response:
                    continue
                raise PmmsError(f'Unexpected response ID while waiting for {request_id}')
            if 'error' in response:
                raise PmmsError(f'JSON-RPC error: {response["error"]}')
            if 'result' not in response:
                raise PmmsError('JSON-RPC response has neither result nor error')
            return response['result']

    def call_tool(self, name, arguments=None, timeout=30):
        if not self.initialized:
            raise PmmsError('MCP handshake has not completed')
        if self.tool_schemas and name not in self.tool_schemas:
            raise PmmsError(f'Tool {name!r} not advertised by this PMMS instance')
        if name == 'save_sim_result':
            # The server deletes this directory recursively before exporting.
            target = Path((arguments or {}).get('path', '')).resolve()
            if self.export_root not in target.parents:
                raise PmmsError('Simulation export must be a new subdirectory of this run directory')
            if target.exists() and (not target.is_dir() or any(target.iterdir())):
                raise PmmsError('Refusing to overwrite an existing simulation export')
        self.tool_calls += 1
        result = self.request('tools/call', {'name': name, 'arguments': arguments or {}}, timeout)
        text = result_text(result)
        # PMMS can encode business failures in text while isError remains false.
        if result.get('isError') or re.search(r'(^|\n)\s*错误[：:]', text):
            self.event('tool_failure', tool=name, result=result)
            raise PmmsError(text or f'{name} returned isError')
        self.tool_successes += 1
        return result

    def discover(self):
        tools = self.request('tools/list')
        resources = self.request('resources/list')
        prompts = self.request('prompts/list')
        self.tool_schemas = {tool['name']: tool for tool in tools.get('tools', [])}
        for filename, obj in [('tools.json', tools), ('resources.json', resources), ('prompts.json', prompts)]:
            (self.run_dir / filename).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
        resource_dir = self.run_dir / 'resources'
        resource_dir.mkdir(exist_ok=True)
        for resource in resources.get('resources', []):
            uri = resource['uri']
            response = self.request('resources/read', {'uri': uri}, timeout=10)
            body = '\n'.join(item.get('text', '') for item in response.get('contents', []))
            name = re.sub(r'[^A-Za-z0-9_.-]', '_', uri.removeprefix('pmms://'))
            (resource_dir / (name + '.md')).write_text(body, encoding='utf-8')
        return {'tool_count': len(tools.get('tools', [])), 'resource_count': len(resources.get('resources', [])),
                'prompt_count': len(prompts.get('prompts', []))}

    def close(self):
        if self.proc is None:
            return
        try:
            if self.proc.poll() is None and self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            # Only terminate the process tree launched by this client.
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.proc.pid), '/T', '/F'],
                               capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.proc.kill()
            self.proc.wait(timeout=5)
        finally:
            for thread in self.threads:
                thread.join(timeout=2)
            self.event('closed', returncode=self.proc.poll(), tool_calls=self.tool_calls,
                       tool_successes=self.tool_successes)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args()
    client = PmmsClient(args.config, args.run_dir)
    summary = {'started': beijing_now(), 'status': 'started'}
    exit_code = 0
    try:
        summary['initialize'] = client.start()
        print('MCP initialize succeeded', flush=True)
        summary['discovery'] = client.discover()
        summary['status'] = 'discovery_passed'
        print(json.dumps(summary['discovery'], ensure_ascii=False), flush=True)
    except Exception as error:
        summary.update(status='failed', error_type=type(error).__name__, error=str(error))
        print(type(error).__name__ + ': ' + str(error), flush=True)
        exit_code = 1
    finally:
        client.close()
        summary.update(ended=beijing_now(), tool_calls=client.tool_calls, tool_successes=client.tool_successes)
        (client.run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Report: ' + str(client.run_dir / 'summary.json'), flush=True)
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
