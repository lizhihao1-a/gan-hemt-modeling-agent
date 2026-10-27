"""Isolate Nano execution on a labelled MOS1 control with public options only."""
from pathlib import Path
import argparse
import json
import os
import re
import shutil
import sys
from probe_demo import ROOT, export_stats
sys.path.insert(0, str(ROOT.parent / 'MeQLab_Local_Integration'))
from pmms_client import PmmsClient, result_text, beijing_now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--parallel-only', action='store_true')
    parser.add_argument('--trace-agent', action='store_true')
    parser.add_argument('--engine-runtime-path', action='store_true')
    parser.add_argument('--preconfigured-project', type=Path)
    parser.add_argument('--feature', default='prim|rf_main|pnano')
    parser.add_argument('--meqlab-path', type=Path)
    parser.add_argument('--log-profile', type=Path)
    parser.add_argument('--baseline-only', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'results' / args.name
    out.mkdir()
    cfg = json.loads((ROOT / 'config.demo.local.json').read_text(encoding='utf-8'))
    original = Path(cfg['runtime_root'])
    runtime = original / 'diag_temp_runs' / args.name
    runtime.mkdir(parents=True)
    cfg['runtime_root'] = runtime.as_posix()
    cfg['project_path'] = (runtime / 'control_project').as_posix()
    cfg['feature'] = args.feature
    if args.meqlab_path:
        cfg['meqlab_path'] = args.meqlab_path.resolve().as_posix()
    if args.preconfigured_project:
        src = args.preconfigured_project.resolve()
        dest = runtime / 'asmhemtdemo'
        shutil.copytree(src.parent, dest, ignore=shutil.ignore_patterns('.meqlab.lock', '.meqlab.lock.holder', 'data.lock.db'))
        for p in dest.rglob('*'):
            if p.is_file() and p.suffix.lower() in ['.xml', '.lib', '.l']:
                text = p.read_text(encoding='utf-8')
                text = text.replace(src.parent.as_posix(), dest.as_posix()).replace(str(src.parent), str(dest))
                p.write_text(text, encoding='utf-8')
        cfg['project_path'] = (dest / src.name).as_posix()
    conf = out / 'config.json'
    conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    client = PmmsClient(conf, out / 'session', export_root=out)
    report = {'started': beijing_now(), 'purpose': 'Diagnostic MOS control, not a GaN result', 'steps': []}
    old_java_options = os.environ.get('JAVA_TOOL_OPTIONS')
    if args.trace_agent:
        jar = ROOT / 'trace_agent/nano_trace.jar'
        trace = out / 'nano_trace.log'
        base = Path(cfg['meqlab_path']).parent.parent
        ieps = base / 'MS-MeQLab/tools/IEPS.exe'
        if not ieps.is_file():
            raise FileNotFoundError(ieps)
        wrapper = out / 'ieps_capture.cmd'
        # The original executable receives identical arguments; output is captured locally.
        path_line = ''
        if args.engine_runtime_path:
            path_line = 'set "PATH='+str(base/'pei/MinGW/bin')+';'+str(base/'pei/pei/Release_Win/MinGW-Windows')+';%PATH%"\r\n'
        wrapper.write_text('@echo off\r\n'+path_line+'"'+str(ieps)+'" %* > "'+str(out/'ieps_verbose.log')+'" 2>&1\r\n', encoding='ascii')
        os.environ['JAVA_TOOL_OPTIONS'] = (old_java_options or '') + ' --add-exports=java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED ' + f'-Dlocal.nano.wrapper={wrapper.as_posix()} -javaagent:{jar.as_posix()}={trace.as_posix()}'

    def call(n, a=None):
        s = {'name': n, 'arguments': a or {}}
        try:
            res = client.call_tool(n, a, timeout=90)
            s.update(ok=True, result=res)
            print(n + ': ' + result_text(res)[:700], flush=True)
            return result_text(res)
        except Exception as e:
            s.update(ok=False, error=str(e))
            print(n + ': FAILED ' + str(e)[:650], flush=True)
            if isinstance(e, TimeoutError) or 'UNAVAILABLE' in str(e):
                raise
        finally:
            report['steps'].append(s)
            (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    def script(label, code):
        p = out / (label + '.ini')
        p.write_text('Prepare\n' + code + '\nEnd\n', encoding='utf-8')
        return call('build_filter_by_template', {'filter_template_path': p.as_posix()})

    def collect(label):
        p = out / (label + '_messages.txt')
        code = [
            f'java.io.FileWriter fw = new java.io.FileWriter("{p.as_posix()}");',
            'fw.write("parallel="+com.platformda.simulate.SimulationManager.parallelEnabled+"; peiParallel="+com.platformda.simulate.SimulationManager.peiParallelEnabled+"; PPN="+com.platformda.simulate.SimulationManager.getPPN()+"; PPNmax="+com.platformda.simulate.SimulationManager.getPPNMax()+"\\n");',
            'fw.write("fullSPPath="+com.platformda.simulate.pei.BasePeiSimulator.fullSPPath+"; readOutputFromFile="+com.platformda.simulate.pei.BasePeiSimulator.readOutputFromFile+"\\n");',
            'src = (com.platformda.extraction.ModelSource)com.platformda.extraction.processor.ProjectSetup.getWorkspace().getSourceByName("mos_control_N");',
            'fw.write("MESSAGES\\n"+src.getMessageSet()+"\\n");',
            'table = src.getMessageTableModel();',
            'if (table != null) for (int i=0; i<table.getRowCount(); i++) { for (int j=0;j<table.getColumnCount();j++) fw.write(""+table.getValueAt(i,j)+" | "); fw.write("\\n"); }',
            'bundles=src.getNetlistBundles();',
            'if (bundles != null) for (int i=0;i<bundles.size();i++) { b=bundles.get(i); fw.write("NETLIST="+b.getNetlist()+"\\nLOGS="+b.getLogs()+"\\nRESULTS="+b.getResults()+"\\n"); }',
            'fw.close();',
        ]
        script(label + '_collect', '\n'.join(code))
        if p.exists():
            print('MODEL MESSAGES: ' + p.read_text(encoding='utf-8')[:1800], flush=True)

    def export(label):
        p = out / label
        p.mkdir()
        call('save_sim_result', {'data_source_name': 'control', 'model_source_name': 'mos_control_N', 'path': p.as_posix()})
        report[label] = export_stats(p)
        print(label + ' NUMERIC: ' + json.dumps(report[label]), flush=True)
        collect(label)

    try:
        client.start()
        client.discover()
        if args.preconfigured_project:
            call('open_project', {'project_path': cfg['project_path']})
        else:
            call('generate_project', {'project_path': cfg['project_path'], 'device_type': 'Mosfet', 'device_polarity': 'NMOS'})
        script('debug', 'com.platformda.simulate.SimulationManager.setDebugEnabled(true);\n'
               'com.platformda.simulate.SimulationManager.setRetainError(true);\n'
               'com.platformda.simulate.SimulationManager.MESSAGE_COLLECTION_ENABLED=true;\n'
               'com.platformda.simulate.SimulationManager.NETLIST_COLLECTION_ENABLED=true;')
        if not args.preconfigured_project:
            call('load_model', {'path': (original / 'models/mos_control.l').as_posix(), 'format': 'hspice'})
            text = call('list_available_models')
            suite = int(re.findall(r'ID:\s*(\d+)', text)[0])
            call('add_model_source', {'model_suite_id': suite, 'model_name': 'mos_control', 'simulator': 'Nano'})
            call('load_data', {'data_type': 0, 'data_source_name': 'control', 'path': (original / 'data/dfo_dc_smoke_v2.pms').as_posix(), 'device_type': 'Mosfet', 'device_polarity': 'NMOS'})
            call('build_filter_by_data', {'data_source_name': 'control'})
        else:
            call('list_model_sources')
            call('set_param', {'model_source_name': 'mos_control_N', 'param_name': 'kp', 'param_value': '0.00008'})
        export('default')
        if args.trace_agent or args.baseline_only:
            return
        if args.parallel_only:
            for label, enabled, kp in [('parallel_on', True, '0.00008'), ('parallel_off', False, '0.00004'), ('parallel_on_again', True, '0.00004')]:
                flag = 'true' if enabled else 'false'
                script(label, f'com.platformda.simulate.SimulationManager.parallelEnabled={flag};\n'
                       f'com.platformda.simulate.SimulationManager.peiParallelEnabled={flag};\n'
                       'com.platformda.simulate.pei.PeiManager.reset();')
                call('set_param', {'model_source_name': 'mos_control_N', 'param_name': 'kp', 'param_value': kp})
                export(label)
            return
        script('full_path', 'com.platformda.simulate.pei.BasePeiSimulator.fullSPPath=true;\ncom.platformda.simulate.pei.PeiManager.reset();')
        call('set_param', {'model_source_name': 'mos_control_N', 'param_name': 'kp', 'param_value': '0.00008'})
        export('full_path')
        script('file_output', 'com.platformda.simulate.pei.BasePeiSimulator.readOutputFromFile=true;\ncom.platformda.simulate.pei.PeiManager.reset();')
        call('set_param', {'model_source_name': 'mos_control_N', 'param_name': 'kp', 'param_value': '0.00004'})
        export('file_output')
        script('nonexpanded', 'com.platformda.simulate.SimulationManager.NL_EXPANDED=false;\ncom.platformda.simulate.pei.PeiManager.reset();')
        call('set_param', {'model_source_name': 'mos_control_N', 'param_name': 'kp', 'param_value': '0.00008'})
        export('nonexpanded')
        script('one_worker', 'com.platformda.simulate.SimulationManager.parallelEnabled=false;\ncom.platformda.simulate.pei.PeiManager.reset();')
        call('set_param', {'model_source_name': 'mos_control_N', 'param_name': 'kp', 'param_value': '0.00004'})
        export('one_worker')
    except Exception as e:
        report.update(error=str(e), error_type=type(e).__name__)
        print('SESSION FAILED: ' + str(e)[:700], flush=True)
    finally:
        logs = out / 'engine_logs'
        logs.mkdir(exist_ok=True)
        profile = args.log_profile or (Path.home() / '.MS-MeQLab/dev')
        for p in (profile / 'var/log').glob('*.log'):
            shutil.copy2(p, logs / p.name)
        client.close()
        if old_java_options is None:
            os.environ.pop('JAVA_TOOL_OPTIONS', None)
        else:
            os.environ['JAVA_TOOL_OPTIONS'] = old_java_options
        report.update(ended=beijing_now(), tool_calls=client.tool_calls, tool_successes=client.tool_successes)
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
