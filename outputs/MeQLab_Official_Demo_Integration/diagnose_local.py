"""Local diagnostics through PMMS and MeQLab's documented Prepare scripting."""
from pathlib import Path
import argparse
import json
import shutil
import sys
import time

from probe_demo import prepare, export_stats, ROOT
sys.path.insert(0, str(ROOT.parent / 'MeQLab_Local_Integration'))
from pmms_client import PmmsClient, result_text, beijing_now


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--name', required=True)
    args = p.parse_args()
    conf, out = prepare(args.name, 'Nano', 'prim|rf_main|pnano')
    client = PmmsClient(conf, out)
    report = {'started': beijing_now(), 'steps': []}

    def call(n, a=None):
        step = {'name': n, 'arguments': a or {}, 'time': beijing_now()}
        try:
            res = client.call_tool(n, a, timeout=90)
            step.update(ok=True, result=res)
            print(n + ': ' + result_text(res)[:1000], flush=True)
            return res
        except Exception as error:
            step.update(ok=False, error=str(error))
            print(n + ': FAILED ' + str(error)[:700], flush=True)
            if 'UNAVAILABLE' in str(error) or isinstance(error, TimeoutError):
                raise
        finally:
            report['steps'].append(step)
            (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def export(n):
        target = out / n
        target.mkdir()
        call('save_sim_result', {'data_source_name': 'Data1', 'model_source_name': 'MYHEMT_N', 'path': target.as_posix()})
        report[n] = export_stats(target)
        print(n + ' NUMERIC: ' + json.dumps(report[n]), flush=True)

    try:
        client.start()
        client.discover()
        if call('open_project', {'project_path': client.config['project_path']}) is None:
            raise RuntimeError('Open failed')
        call('save_current_project')
        call('get_view_group_error')
        marker = (out / 'debug_enabled.txt').as_posix()
        ini = out / 'debug.ini'
        ini.write_text('Prepare\n'
                       'com.platformda.simulate.SimulationManager.setDebugEnabled(true);\n'
                       'com.platformda.simulate.SimulationManager.setRetainError(true);\n'
                       'com.platformda.simulate.SimulationManager.MESSAGE_COLLECTION_ENABLED = true;\n'
                       'com.platformda.simulate.SimulationManager.NETLIST_COLLECTION_ENABLED = true;\n'
                       f'java.io.FileWriter fw = new java.io.FileWriter("{marker}");\n'
                       'fw.write("debug enabled through Prepare");\nfw.close();\nEnd\n', encoding='utf-8')
        call('build_filter_by_template', {'filter_template_path': ini.as_posix()})
        report['debug_marker_present'] = Path(marker).is_file()
        export('before_clear')
        call('set_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff', 'node_name': 'ASMHEMT_INT', 'param_value': '-1.9'})
        export('perturbed_before_clear')
        call('save_current_project')
        call('build_filter_by_data', {'data_source_name': 'Data1'})
        call('list_filters')
        call('clear_views')
        call('view', {'view_fields': [{'filter_string': 'name,Data1(Sweep)', 'source_string': 'Data1,MYHEMT_N', 'selection_string': 'xr(0,1)'}]})
        call('get_view_group_error')
        time.sleep(2)
        call('get_view_group_error')
        export('rebuilt_filter')
        call('save_current_project')
    except Exception as error:
        report.update(error=str(error), error_type=type(error).__name__)
        print('SESSION FAILED: ' + str(error)[:1000], flush=True)
    finally:
        logroot = Path.home() / '.MS-MeQLab/dev/var/log'
        logs = out / 'engine_logs'
        logs.mkdir(exist_ok=True)
        for f in logroot.glob('*.log'):
            shutil.copy2(f, logs / f.name)
        client.close()
        report.update(ended=beijing_now(), tool_calls=client.tool_calls, tool_successes=client.tool_successes)
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
