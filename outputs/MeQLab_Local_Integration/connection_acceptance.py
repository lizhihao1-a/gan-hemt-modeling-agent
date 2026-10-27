"""Verify the MCP connection with a labelled MOS control and checkpoint replay.

This checks tool plumbing, not the GaN model or competition accuracy.
"""
from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse
import json
import math
import re
import shutil

from pmms_client import PmmsClient, result_text, beijing_now


def load_dat(directory):
    files = list(Path(directory).glob('*.dat'))
    if len(files) != 1:
        raise RuntimeError(f'Expected one exported .dat, found {len(files)} in {directory}')
    rows = []
    for line in files[0].read_text(encoding='utf-8', errors='replace').splitlines():
        try:
            values = [float(item) for item in line.split(',')]
        except ValueError:
            continue
        if len(values) == 4:
            rows.append(values)
    if len(rows) != 11 or not all(math.isfinite(value) for row in rows for value in row):
        raise RuntimeError('Export must contain 11 finite rows and three model-current columns')
    if max(abs(value) for row in rows for value in row[1:]) < 1e-10:
        raise RuntimeError('All model currents are zero; a success message is insufficient')
    return files[0], rows


def parameter(client, source, name):
    text = result_text(client.call_tool('get_param', {'model_source_name': source, 'param_name': name}))
    match = re.search(r'值[：:]\s*([-+0-9.eE]+)', text)
    if not match:
        raise RuntimeError('Parameter readback missing a numeric value')
    return float(match.group(1))


def initialize_model(client, project_path, model_path, data_path):
    client.call_tool('generate_project', {'project_path': str(project_path), 'device_type': 'Mosfet', 'device_polarity': 'NMOS'})
    client.call_tool('load_model', {'path': str(model_path), 'format': 'hspice'})
    text = result_text(client.call_tool('list_available_models'))
    ids = re.findall(r'ID:\s*(\d+)', text)
    if len(ids) != 1:
        raise RuntimeError('Control session must contain exactly one model suite')
    suite_id = int(ids[0])
    text = result_text(client.call_tool('add_model_source', {'model_suite_id': suite_id, 'model_name': 'mos_control', 'simulator': 'Internal'}))
    match = re.search(r'名称[：:]\s*([^，\r\n]+)', text)
    if not match:
        raise RuntimeError('Model source name not present')
    source = match.group(1).strip()
    client.call_tool('load_data', {'data_type': 0, 'data_source_name': 'accept_data', 'path': str(data_path), 'device_type': 'Mosfet', 'device_polarity': 'NMOS'})
    if 'accept_data' not in result_text(client.call_tool('list_data_sources')):
        raise RuntimeError('Data loader reported success without registering a source')
    client.call_tool('build_filter_by_data', {'data_source_name': 'accept_data'})
    client.call_tool('view', {'view_fields': [{'filter_string': 'name,accept_data(Sweep)', 'source_string': 'accept_data,' + source,
                                            'page_string': 'Id_Vds', 'selection_string': 'xr(0,1)'}]})
    return suite_id, source


def export_curve(client, source, directory):
    directory.mkdir(parents=True, exist_ok=True)
    client.call_tool('save_sim_result', {'data_source_name': 'accept_data', 'model_source_name': source, 'path': str(directory)}, timeout=60)
    return load_dat(directory)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--results', required=True)
    args = parser.parse_args()
    out = Path(args.results).resolve()
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    runtime = Path(cfg['runtime_root'])
    data_path = runtime / 'data/dfo_dc_smoke_v2.pms'
    input_card = runtime / 'models/mos_control.l'
    assets = Path(__file__).resolve().parent / 'assets'
    for target, source in [(data_path, assets / data_path.name), (input_card, assets / input_card.name)]:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
    tag = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S')
    summary = {'started': beijing_now(), 'purpose': 'MCP connection and checkpoint acceptance using a diagnostic MOS control; NOT a GaN fitting result', 'checks': {}}
    checks = summary['checks']
    counts = []
    try:
        client = PmmsClient(args.config, out / 'first_session', export_root=out)
        try:
            summary['initialize'] = client.start()
            summary['discovery'] = client.discover()
            checks['handshake'] = True
            suite, source = initialize_model(client, runtime / 'projects' / ('accept_' + tag), input_card, data_path)
            checks['data_source_registered'] = True
            client.call_tool('set_param', {'model_source_name': source, 'param_name': 'kp', 'param_value': '0.00004'})
            checks['parameter_readback'] = abs(parameter(client, source, 'kp') - 0.00004) < 1e-14
            before_path, before = export_curve(client, source, out / 'control_low_kp')
            checks['finite_nonzero_simulation'] = True
            client.call_tool('set_param', {'model_source_name': source, 'param_name': 'kp', 'param_value': '0.00008'})
            after_path, after = export_curve(client, source, out / 'control_high_kp')
            max_change = max(abs(a-b) for ra, rb in zip(before, after) for a, b in zip(ra[1:], rb[1:]))
            checks['parameter_changes_curve'] = max_change > 1e-5
            summary['max_current_change_A'] = max_change
            summary['parameter_values'] = {'kp_low': 0.00004, 'kp_high': 0.00008}
            export_dir = out / 'checkpoint_assets'
            export_dir.mkdir(exist_ok=True)
            client.call_tool('save_model', {'model_suite_id': suite, 'path': str(export_dir / 'requested_name.l')})
            # This implementation keeps the source model basename rather than the requested basename.
            card = export_dir / input_card.name
            if not card.is_file():
                raise RuntimeError('save_model success did not produce the expected source-basename card')
            if not re.search(r'kp\s*=\s*0\.00008', card.read_text(encoding='utf-8'), re.I):
                raise RuntimeError('Exported card does not contain the current parameter value')
            checks['model_card_export'] = True
            summary['checkpoint'] = {'model_card': str(card), 'data_file': str(data_path), 'simulator': 'Internal',
                                     'expected_parameter': {'kp': 0.00008}, 'expected_simulation_file': str(after_path)}
            (out / 'checkpoint.json').write_text(json.dumps(summary['checkpoint'], ensure_ascii=False, indent=2), encoding='utf-8')
        finally:
            client.close()
            counts.append({'phase': 'first_session', 'tool_calls': client.tool_calls, 'tool_successes': client.tool_successes})
        client = PmmsClient(args.config, out / 'replay_session', export_root=out)
        try:
            client.start()
            client.discover()
            suite, source = initialize_model(client, runtime / 'projects' / ('replay_' + tag), card, data_path)
            checks['checkpoint_parameter_restored'] = abs(parameter(client, source, 'kp') - 0.00008) < 1e-14
            replay_path, replay = export_curve(client, source, out / 'control_replayed')
            max_difference = max(abs(a-b) for ra, rb in zip(after, replay) for a, b in zip(ra, rb))
            summary['checkpoint_max_difference'] = max_difference
            checks['checkpoint_simulation_restored'] = max_difference < 1e-10
            summary['checkpoint']['replayed_simulation_file'] = str(replay_path)
        finally:
            client.close()
            counts.append({'phase': 'replay_session', 'tool_calls': client.tool_calls, 'tool_successes': client.tool_successes})
        summary['status'] = 'passed' if all(checks.values()) else 'failed'
    except Exception as error:
        summary.update(status='failed', error_type=type(error).__name__, error=str(error))
    summary.update(ended=beijing_now(), sessions=counts)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    raise SystemExit(0 if summary['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
