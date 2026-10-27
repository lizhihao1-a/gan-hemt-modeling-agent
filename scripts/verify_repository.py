"""Check the exported handoff without proprietary software or third-party packages."""
from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def load(path): return json.loads(path.read_text(encoding='utf-8-sig'))
def rows(path):
    with path.open(encoding='utf-8-sig',newline='') as stream:
        return list(csv.DictReader(stream))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok,message):
    if not ok: raise RuntimeError(message)

def main():
    files=[p for p in ROOT.rglob('*') if p.is_file() and '.git' not in p.parts
           and not any(x in p.parts for x in ['.cache','.deps','.venv','__pycache__','runtime','runs','results'])]
    for p in files:
        if p.suffix=='.py':compile(p.read_text(encoding='utf-8-sig'),str(p),'exec')
        if p.suffix=='.json':load(p)
    print('PASS Python syntax and JSON readability')

    expected=load(ROOT/'reports/SHA256SUMS.json')
    for name,digest in expected.items():
        require((ROOT/name).is_file() and sha(ROOT/name)==digest, f'Snapshot changed: {name}')
    print(f'PASS {len(expected)} frozen export hashes')

    prepared=ROOT/'outputs/GaN_HEMT_Prepared'
    data=rows(prepared/'data/unified_measurements.csv')
    require(len(data)==9868,'Unified row count differs')
    require(len({r['point_id'] for r in data})==9868,'Duplicate point IDs')
    require(Counter(r['device_id'] for r in data)==Counter({'TLN2':2121,'GS65030':1717,'DFO_4x50':6030}), 'Device counts differ')
    for r in data:
        for key in ['vds_V','vgs_V','id_A','ig_A','gm_S','capacitance_F','temperature_K']:
            if r[key]!='':require(math.isfinite(float(r[key])), f'Nonfinite value at {r["point_id"]}')
        require(r['temperature_K']=='','Unknown measurement temperature was filled')
    print('PASS 9,868 measurements, unique IDs, finite numeric fields and unknown temperature')

    for project in ['DFO_DC_Baseline','GaN_HEMT_Local_Agent']:
        root=ROOT/'outputs'/project
        train,test=rows(root/'data/train.csv'),rows(root/'data/test.csv')
        require(len(train)==4824 and len(test)==1206,'Split counts differ')
        a,b={r['point_id'] for r in train},{r['point_id'] for r in test}
        require(not a&b and len(a|b)==6030,'Original split overlap or missing points')
        manifest=load(root/'data/manifest.json')
        for split in ['train','test']:
            require(sha(root/f'data/{split}.csv')==manifest[split+'_sha256'],'Original split bytes changed')
    print('PASS original train/test split and hashes in both projects')

    for short,table,measured,predicted,metric in [
        ('baseline','test_predictions.csv','id_A','id_after_A',load(ROOT/'reports/baseline/test_evaluation.json')['metrics']['test']['after']['id_A']['rmse']),
        ('local_agent','verification/test_predictions.csv','measured_id_A','predicted_id_A',load(ROOT/'reports/local_agent/verification/test_metrics.json')['metrics']['test']['full_metrics']['id_A']['rmse'])]:
        table_rows=rows(ROOT/'reports'/short/table)
        require(len(table_rows)==1206,'Prediction count differs')
        rmse=math.sqrt(sum((float(r[measured])-float(r[predicted]))**2 for r in table_rows)/len(table_rows))
        require(math.isclose(rmse,metric,rel_tol=1e-10,abs_tol=1e-14),f'{short}: metric differs from prediction CSV')
        print(f'PASS {short} archived test Id RMSE = {rmse*1000:.6f} mA')

    snapshot=load(ROOT/'outputs/GaN_HEMT_Local_Agent/reference/baseline_snapshot.json')
    for name,digest in snapshot.items():
        path=ROOT/'outputs/DFO_DC_Baseline'/name
        if not path.exists() and name.startswith('results/'):
            path=ROOT/'reports/baseline'/name.removeprefix('results/')
        require(sha(path)==digest,'Frozen reference baseline changed')
    status=load(ROOT/'reports/meqlab/current_status.json')
    require(status['official_gan']['valid'] is False and status['domestic_llm_connected'] is False,'Completion status changed; review evidence explicitly')
    print('PASS frozen reference and explicit official integration limitations')

    # Inspect tracked content after git init; omit user-local ignored artifacts.
    if (ROOT/'.git').exists():
        result=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True)
        tracked=[ROOT/p.decode('utf-8') for p in result.stdout.split(b'\0') if p]
        if tracked:files=tracked
    forbidden={'.exe','.dll','.osdi','.jar','.class','.zip','.7z','.lic','.log'}
    for p in files:
        require(p.suffix.lower() not in forbidden,f'Local software or raw log included: {p.relative_to(ROOT)}')
        require(not p.name.endswith('.local.json'),'Local configuration included')
        require(p.stat().st_size<15_000_000,'Oversized export file')
        if p.suffix.lower() in ['.png','.pdf','.npz']:continue
        require(not p.read_bytes().startswith((b'!<arch>',b'MZ')),f'Compiled artifact included: {p.relative_to(ROOT)}')
        try:text=p.read_text(encoding='utf-8-sig')
        except UnicodeDecodeError:continue
        require(not re.search(r'C:[/\\]+Users[/\\]+[A-Za-z0-9_.-]+',text,re.I),f'Personal machine path in {p.relative_to(ROOT)}')
        require(not re.search(r'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}',text),f'Credential pattern in {p.relative_to(ROOT)}')
    print(f'PASS export hygiene across {len(files)} files (pattern scan, not a credential audit)')
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,check=True)
    print('Repository handoff checks passed. Native simulation has not been rerun by this command.')

if __name__=='__main__':main()
