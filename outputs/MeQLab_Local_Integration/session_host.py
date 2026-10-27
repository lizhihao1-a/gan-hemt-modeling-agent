"""Keep one private PMMS session alive while processing local JSON requests."""
from pathlib import Path
import argparse
import json
import time

from pmms_client import PmmsClient, beijing_now


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--session-dir', required=True)
    args = parser.parse_args()
    root = Path(args.session_dir).resolve()
    inbox, outbox = root / 'commands', root / 'responses'
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    client = PmmsClient(args.config, root)
    state = {'status': 'starting', 'started': beijing_now()}
    write_json(root / 'state.json', state)
    try:
        state['initialize'] = client.start()
        state['discovery'] = client.discover()
        state['status'] = 'ready'
        write_json(root / 'state.json', state)
        print('Session ready: ' + str(root), flush=True)
        idle = time.monotonic()
        stop = False
        while not stop:
            if time.monotonic() - idle > 600:
                state['status'] = 'idle_timeout'
                break
            for path in sorted(inbox.glob('*.json')):
                target = outbox / path.name
                if target.exists():
                    continue
                request = json.loads(path.read_text(encoding='utf-8-sig'))
                response = {'request': request, 'started': beijing_now()}
                try:
                    operation = request.get('operation', 'tool')
                    if operation == 'stop':
                        stop = True
                        response.update(ok=True, result={'stopping': True})
                    elif operation == 'tool':
                        result = client.call_tool(request['name'], request.get('arguments', {}), request.get('timeout', 30))
                        response.update(ok=True, result=result)
                    elif operation == 'rpc' and request['method'] in {'tools/list', 'resources/list', 'resources/read', 'prompts/list', 'prompts/get'}:
                        response.update(ok=True, result=client.request(request['method'], request.get('params'), request.get('timeout', 30)))
                    else:
                        raise ValueError('Unsupported local operation')
                except Exception as error:
                    response.update(ok=False, error_type=type(error).__name__, error=str(error))
                    if isinstance(error, TimeoutError) or client.proc.poll() is not None:
                        stop = True
                        state['status'] = 'transport_failed'
                response['ended'] = beijing_now()
                write_json(target, response)
                idle = time.monotonic()
                state.update(last_request=path.stem, tool_calls=client.tool_calls, tool_successes=client.tool_successes)
                write_json(root / 'state.json', state)
                print(path.stem + ': ' + ('ok' if response['ok'] else 'failed'), flush=True)
                if stop:
                    break
            time.sleep(0.15)
    except Exception as error:
        state.update(status='failed', error_type=type(error).__name__, error=str(error))
        print(type(error).__name__ + ': ' + str(error), flush=True)
    finally:
        client.close()
        if state['status'] == 'ready':
            state['status'] = 'closed'
        state.update(ended=beijing_now(), tool_calls=client.tool_calls, tool_successes=client.tool_successes)
        write_json(root / 'state.json', state)


if __name__ == '__main__':
    main()
