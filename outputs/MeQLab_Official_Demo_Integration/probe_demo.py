"""Reproducible, isolated checks of the user-provided ASM-HEMT demo."""
from pathlib import Path
import argparse
import json
import math
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / 'MeQLab_Local_Integration'))
from pmms_client import PmmsClient, beijing_now, result_text


def export_stats(folder):
    values = []
    files = []
    for path in sorted(Path(folder).glob('*.dat')):
        count = 0
        for line in path.read_text(encoding='utf-8').splitlines():
            cells = line.split(',')
            try:
                row = [float(v) for v in cells]
            except ValueError:
                continue
            if len(row) > 1:
                values.extend(row[1:])
                count += len(row) - 1
        files.append({'name': path.name, 'current_values': count})
    finite = [x for x in values if math.isfinite(x)]
    return {'files': files, 'points': len(values), 'finite': len(finite),
            'nonzero': sum(abs(x) > 1e-12 for x in finite),
            'max_abs_current': max(map(abs, finite), default=None)}


def prepare(name, simulator, feature):
    cfg = json.loads((ROOT / 'config.demo.local.json').read_text(encoding='utf-8'))
    runtime = Path(cfg['runtime_root']) / 'official_demo'
    source = runtime / 'pristine' / 'asmhemtdemo'
    dest = runtime / name / 'asmhemtdemo'
    if dest.exists():
        raise FileExistsError(f'Use a new run name: {dest}')
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns('.meqlab.lock', '.meqlab.lock.holder', 'data.lock.db'))
    va = (dest / 'asmhemt.va').as_posix()
    card = dest / 'GaN_full.lib'
    content = card.read_text(encoding='utf-8')
    content = content.replace(".hdl './asmhemt.va'", f".hdl '{va}'")
    card.write_text(content, encoding='utf-8')
    shutil.copy2(card, dest / 'BestFittingProject/model/0/GaN_full.lib')
    for p in [dest / 'BestFittingProject/data/workspace.xml', dest / 'BestFittingProject/model/0/0.xml']:
        tree = ET.parse(p)
        for el in tree.iter():
            if el.tag == 'ModelSuite' and el.get('loadedFrom'):
                el.set('loadedFrom', card.as_posix())
            if el.tag == 'prop' and el.get('name') == 'hspice':
                el.set('value', card.as_posix())
            if el.tag == 'prop' and el.get('name') == 'va':
                value = el.get('value', '')
                if 'weipeng0792' in value:
                    el.set('value', va)
                elif value == "'./asmhemt.va'":
                    el.set('value', f"'{va}'")
            if el.tag == 'Source' and el.get('type') == '1':
                el.set('simulator', simulator)
        tree.write(p, encoding='utf-8', xml_declaration=True)
    cfg['feature'] = feature
    cfg['project_path'] = (dest / 'BestFittingProject').as_posix()
    out = ROOT / 'results' / name
    out.mkdir(parents=True)
    conf = out / 'config.json'
    conf.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    return conf, out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    parser.add_argument('--simulator', default='Nano', choices=['Nano', 'Internal'])
    parser.add_argument('--feature', default='prim|rf_main|pnano')
    parser.add_argument('--package-runtime-path', action='store_true')
    args = parser.parse_args()
    conf, out = prepare(args.name, args.simulator, args.feature)
    client = PmmsClient(conf, out)
    report = {'started': beijing_now(), 'simulator': args.simulator, 'feature': args.feature,
              'absolute_hdl_path': True, 'steps': []}
    original_path = os.environ.get('PATH', '')
    if args.package_runtime_path:
        base = Path(client.config['meqlab_path']).parent.parent
        extra = [base / 'pei/MinGW/bin', base / 'pei/pei/Release_Win/MinGW-Windows',
                 base / 'jre17/bin', base / 'MS-MeQLab/modules/lib']
        if not all(p.is_dir() for p in extra):
            raise FileNotFoundError('A package runtime directory is absent')
        os.environ['PATH'] = ';'.join(map(str, extra)) + ';' + original_path
        report['extra_child_path'] = list(map(str, extra))

    def call(name, arguments=None, timeout=90):
        record = {'name': name, 'arguments': arguments or {}}
        try:
            r = client.call_tool(name, arguments, timeout)
            record.update(ok=True, result=r)
            print(name + ': ' + result_text(r)[:1300], flush=True)
            return r
        except Exception as error:
            record.update(ok=False, error=str(error), error_type=type(error).__name__)
            print(name + ': FAILED ' + str(error)[:700], flush=True)
            if 'StatusCode.UNAVAILABLE' in str(error) or isinstance(error, TimeoutError):
                raise RuntimeError('Transport failed; remaining calls were skipped') from error
            return None
        finally:
            report['steps'].append(record)
            (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        client.start()
        client.discover()
        if call('open_project', {'project_path': client.config['project_path']}) is None:
            raise RuntimeError('Project open failed; remaining checks were skipped')
        call('list_model_sources')
        call('get_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff'})
        call('clear_views')
        call('view', {'view_fields': [
            {'filter_string': 'name,Data1(Sweep)', 'source_string': 'Data1,MYHEMT_N',
             'page_string': p, 'selection_string': 'xr(0,1)'} for p in ['Id_Vgs', 'Id_Vds']]})
        call('get_view_group_error')
        exp = out / 'baseline'
        exp.mkdir()
        call('save_sim_result', {'data_source_name': 'Data1', 'model_source_name': 'MYHEMT_N', 'path': exp.as_posix()})
        report['baseline'] = export_stats(exp)
        print('NUMERIC BASELINE ' + json.dumps(report['baseline']), flush=True)
        call('set_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff', 'node_name': 'ASMHEMT_INT', 'param_value': '-1.9'})
        call('get_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff'})
        exp = out / 'perturbed'
        exp.mkdir()
        call('save_sim_result', {'data_source_name': 'Data1', 'model_source_name': 'MYHEMT_N', 'path': exp.as_posix()})
        report['perturbed'] = export_stats(exp)
        call('set_param', {'model_source_name': 'MYHEMT_N', 'param_name': 'voff', 'node_name': 'ASMHEMT_INT', 'param_value': '-2.0'})
        model = out / 'saved_model'
        model.mkdir()
        call('save_model', {'model_suite_id': 0, 'path': (model / 'requested.lib').as_posix()})
        call('save_current_project')
    except Exception as error:
        report.update(error=str(error), error_type=type(error).__name__)
        print('SESSION FAILED ' + str(error), flush=True)
    finally:
        logs = out / 'engine_logs'
        logs.mkdir(exist_ok=True)
        logroot = Path.home() / '.MS-MeQLab/dev/var/log'
        for p in logroot.glob('*.log'):
            shutil.copy2(p, logs / p.name)
        client.close()
        os.environ['PATH'] = original_path
        report.update(ended=beijing_now(), tool_calls=client.tool_calls, tool_successes=client.tool_successes)
        (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
