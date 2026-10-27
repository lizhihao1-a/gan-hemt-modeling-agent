"""Compare Nano and Internal on a MOS control, and test UI-aware saving."""
from pathlib import Path
import argparse
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from probe_demo import prepare, export_stats, ROOT
sys.path.insert(0, str(ROOT.parent / 'MeQLab_Local_Integration'))
from pmms_client import PmmsClient, result_text, beijing_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--initialize-workers', action='store_true')
    args = parser.parse_args()
    conf, out = prepare(args.name, 'Nano', 'prim|rf_main|pnano')
    cfg = json.loads(conf.read_text(encoding='utf-8'))
    original_runtime = Path(cfg['runtime_root'])
    isolated = original_runtime / 'diag_temp_runs' / args.name
    isolated.mkdir(parents=True)
    cfg['runtime_root'] = isolated.as_posix()
    conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    client = PmmsClient(conf, out / 'session', export_root=out)
    report = {'started': beijing_now(), 'steps': []}

    def call(n, a=None):
        s = {'name': n, 'arguments': a or {}}
        try:
            r = client.call_tool(n, a, timeout=90)
            s.update(ok=True, result=r)
            print(n + ': ' + result_text(r)[:700], flush=True)
            return result_text(r)
        except Exception as e:
            s.update(ok=False, error=str(e))
            print(n + ': FAILED ' + str(e)[:500], flush=True)
            if isinstance(e, TimeoutError) or 'UNAVAILABLE' in str(e):
                raise
        finally:
            report['steps'].append(s)
            (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def script(label, code):
        p = out / (label + '.ini')
        p.write_text('Prepare\n' + code + '\nEnd\n', encoding='utf-8')
        return call('build_filter_by_template', {'filter_template_path': p.as_posix()})

    def export(label, data, model):
        p = out / label
        p.mkdir()
        call('save_sim_result', {'data_source_name': data, 'model_source_name': model, 'path': p.as_posix()})
        stats = export_stats(p)
        report[label] = stats
        print(label + ' NUMERIC: ' + json.dumps(stats), flush=True)

    try:
        client.start()
        client.discover()
        if call('open_project', {'project_path': cfg['project_path']}) is None:
            raise RuntimeError('Open failed')
        script('debug', 'com.platformda.simulate.SimulationManager.setDebugEnabled(true);\n'
               'com.platformda.simulate.SimulationManager.setRetainError(true);\n'
               'com.platformda.simulate.SimulationManager.MESSAGE_COLLECTION_ENABLED = true;\n'
               'com.platformda.simulate.SimulationManager.NETLIST_COLLECTION_ENABLED = true;')
        if args.initialize_workers:
            statefile = (out / 'nano_worker_state.txt').as_posix()
            script('initialize_workers',
                   'int before = com.platformda.simulate.SimulationManager.getPPN();\n'
                   'int licensed = com.platformda.simulate.SimulationManager.getPPNMax();\n'
                   'if (licensed <= 0) throw new RuntimeException("No checked-out Nano capacity");\n'
                   'com.platformda.simulate.SimulationManager.updatePPNToMax();\n'
                   f'java.io.FileWriter fw = new java.io.FileWriter("{statefile}");\n'
                   'fw.write("before="+before+"; licensed_max="+licensed+"; after="+com.platformda.simulate.SimulationManager.getPPN());\n'
                   'fw.close();')
            if Path(statefile).exists():
                report['nano_worker_state'] = Path(statefile).read_text(encoding='utf-8')
                print('NANO WORKERS: ' + report['nano_worker_state'], flush=True)
            call('set_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff', 'node_name': 'ASMHEMT_INT', 'param_value': '-1.9'})
        export('gan_fresh_temp', 'Data1', 'MYHEMT_N')
        call('load_model', {'path': (original_runtime / 'models/mos_control.l').as_posix(), 'format': 'hspice'})
        text = call('list_available_models')
        ids = re.findall(r'ID:\s*(\d+)', text or '')
        if not ids:
            raise RuntimeError('No model suite IDs')
        suite = int(ids[-1])
        call('add_model_source', {'model_suite_id': suite, 'model_name': 'mos_control', 'simulator': 'Nano'})
        call('add_model_source', {'model_suite_id': suite, 'model_name': 'mos_control', 'simulator': 'Internal'})
        call('load_data', {'data_type': 0, 'data_source_name': 'control', 'path': (original_runtime / 'data/dfo_dc_smoke_v2.pms').as_posix(), 'device_type': 'Mosfet', 'device_polarity': 'NMOS'})
        call('build_filter_by_data', {'data_source_name': 'control'})
        export('mos_nano', 'control', 'mos_control_N')
        export('mos_internal', 'control', 'mos_control_I')
        call('set_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff', 'node_name': 'ASMHEMT_INT', 'param_value': '-1.9'})
        script('save_ui_state', 'com.platformda.extraction.processor.ProjectSetup.getCurrentProject().save(true);')
        x = ET.parse(Path(cfg['project_path']) / 'data/workspace.xml').getroot()
        report['saved_workspace_xml_valid'] = True
        report['saved_view_groups'] = len(x.findall('./ViewGroups/ViewGroup'))
        call('close_current_project')
        call('open_project', {'project_path': cfg['project_path']})
        readback = call('get_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff'})
        report['voff_after_reopen'] = readback
    except Exception as e:
        report.update(error=str(e), error_type=type(e).__name__)
        print('SESSION FAILED: ' + str(e)[:700], flush=True)
    finally:
        logs = out / 'engine_logs'
        logs.mkdir(exist_ok=True)
        for p in (Path.home() / '.MS-MeQLab/dev/var/log').glob('*.log'):
            shutil.copy2(p, logs / p.name)
        client.close()
        report.update(ended=beijing_now(), tool_calls=client.tool_calls, tool_successes=client.tool_successes)
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
