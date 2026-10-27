from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps, ImageDraw

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
ws=Path(__file__).resolve().parent.parent
out=ws/'outputs/GaN_HEMT_Prepared'
work=ws/'work'
with (out/'data/unified_measurements.csv').open(encoding='utf-8-sig',newline='') as f:
    reader=csv.DictReader(f); columns=reader.fieldnames; rows=list(reader)
assert len(rows)==9868 and len(columns)==42
ids={r['point_id'] for r in rows}
assert len(ids)==9868
device_rows=[]
for p in (out/'data/by_device').glob('*.csv'):
    with p.open(encoding='utf-8-sig',newline='') as f: device_rows.extend(csv.DictReader(f))
assert Counter(tuple(r[k] for k in columns) for r in device_rows)==Counter(tuple(r[k] for k in columns) for r in rows)
assert all(r['temperature_K']=='' for r in rows)
assert Counter(r['train_test_split'] for r in rows if r['device_id']=='DFO_4x50')=={'train':4824,'test':1206}

ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
with zipfile.ZipFile(out/'normalized_measurements.xlsx') as z:
    assert z.testzip() is None
    book=ET.fromstring(z.read('xl/workbook.xml'))
    names=[s.attrib['name'] for s in book.find('s:sheets',ns)]
    assert names==['Overview','Measurements','Gaps','Fields','Sources']
    shared=[]
    if 'xl/sharedStrings.xml' in z.namelist():
        st=ET.fromstring(z.read('xl/sharedStrings.xml'))
        shared=[''.join(item.itertext()) for item in st]
    sheet=ET.fromstring(z.read('xl/worksheets/sheet2.xml'))
    excel_rows=sheet.find('s:sheetData',ns)
    assert len(excel_rows)==9869
    def value(c):
        v=c.find('s:v',ns)
        if c.attrib.get('t')=='s':return shared[int(v.text)] if v is not None else ''
        if c.attrib.get('t')=='inlineStr':return ''.join(c.find('s:is',ns).itertext())
        return v.text if v is not None else ''
    def col_index(address):
        n=0
        for ch in re.match('[A-Z]+',address).group():n=n*26+ord(ch)-64
        return n-1
    header={col_index(c.attrib['r']):value(c) for c in excel_rows[0]}
    assert [header[i] for i in range(42)]==columns
    payload=json.loads((work/'gan_normalized_payload.json').read_text(encoding='utf-8'))
    numeric=set(payload['numeric_fields'])|set(payload['boolean_fields'])
    compared=0
    for row, xr in zip(rows,excel_rows[1:]):
        cells={col_index(c.attrib['r']):c for c in xr}
        for i,key in enumerate(columns):
            actual=value(cells[i]) if i in cells else ''
            expected=row[key]
            if expected=='':assert actual=='',(key,xr.attrib['r'],actual)
            elif key in numeric:
                assert i in cells and cells[i].attrib.get('t') not in {'s','inlineStr'}
                assert math.isclose(float(actual),float(expected),rel_tol=2e-14,abs_tol=1e-25),(key,xr.attrib['r'])
            else: assert actual==expected,(key,xr.attrib['r'])
            compared+=1
    gap_sheet=ET.fromstring(z.read('xl/worksheets/sheet3.xml'))
    assert len(gap_sheet.find('s:sheetData',ns))==15

conditions=json.loads((out/'metadata/conditions.json').read_text(encoding='utf-8'))
assert len(conditions)==17
for fid, entry in conditions.items():
    raw_copy=out/entry['raw_copy']
    assert hashlib.sha256(raw_copy.read_bytes()).hexdigest()==entry['sha256']

readme=out/'README.md'
text=readme.read_text(encoding='utf-8')
extra='\n## 筛选时的注意事项\n\n按 measurement_type 及该任务所需的观测列筛选，不要对全表直接删除所有含空值的行：C-V 没有逐点 Vgs，温度也未提供。quality_flags 非空不等于记录报废。布尔标记 0 表示当前检查未触发；当所需限流设置或设定电压缺失时，也不能把 0 解释为仪器或物理 QA 已通过。\n'
if '## 筛选时的注意事项' not in text:readme.write_text(text+extra,encoding='utf-8')
mdl=ws/'outputs/GaN_HEMT_Datasets/02_ASM_HEMT_DFO_Measurements/extracted/notebooks/HEMT_ex/ASM-HEMT_Modeling_4x50_DFO_clean.mdl'
shutil.copyfile(mdl,out/'raw_selected/DFO_model_context.mdl')
for fid, entry in conditions.items():
    if fid.startswith('DFO'):
        entry['model_context_copy']='raw_selected/DFO_model_context.mdl'
        entry['model_context_sha256']=hashlib.sha256(mdl.read_bytes()).hexdigest()
(out/'metadata/conditions.json').write_text(json.dumps(conditions,ensure_ascii=False,indent=2),encoding='utf-8')

html=(out/'curve_preview.html').read_text(encoding='utf-8')
assert html.count('data:image/png;base64,')==4
for target in re.findall(r'href="([^"]+)"',html):
    if not target.startswith('https://'):assert (out/target).exists(),target
pngs=list((out/'previews').rglob('*.png'))
assert len(pngs)==20
for p in pngs:
    with Image.open(p) as im:im.verify()
tiles=sorted((out/'previews/source_curves').glob('*.png'))
canvas=Image.new('RGB',(2400,1600),'#e5e7eb')
for i,p in enumerate(tiles):
    with Image.open(p) as im:
        tile=ImageOps.contain(im.convert('RGB'),(595,395))
        canvas.paste(tile,((i%4)*600,(i//4)*400))
canvas.save(work/'gan_source_curves_contact_sheet.png')

validation=json.loads((out/'metadata/validation.json').read_text(encoding='utf-8'))
validation['export_checks']={'csv_by_device_reconciles':True,'xlsx_all_cells_match_csv':True,'xlsx_cells_checked':compared,'xlsx_numeric_cells_are_typed_numbers':True,'xlsx_missing_values_are_empty':True,'xlsx_gap_rows':14,'all_17_raw_copies_match_source_sha256':True,'preview_pngs_verified':20,'html_local_links_resolve':True}
(out/'metadata/validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
checksums=[]
for p in sorted(out.rglob('*')):
    if p.is_file() and p.name not in {'SHA256SUMS.txt','normalized_measurements.xlsx.inspect.ndjson'}:
        checksums.append(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(out).as_posix())
(out/'SHA256SUMS.txt').write_text('\n'.join(checksums)+'\n',encoding='utf-8')
archive=ws/'outputs/GaN_HEMT_Prepared.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(out.rglob('*')):
        if p.is_file() and p.name!='normalized_measurements.xlsx.inspect.ndjson':z.write(p,p.relative_to(out.parent).as_posix())
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
print(json.dumps({'records':9868,'xlsx_cells_reconciled':compared,'pngs':len(pngs),'gaps':14,'archive_bytes':archive.stat().st_size,'archive':str(archive),'files':len(checksums)+1,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},ensure_ascii=False))
