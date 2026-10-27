from pathlib import Path
from collections import Counter
import csv
import hashlib
import json
import math
import sys
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
root = Path(__file__).resolve().parent.parent / "outputs" / "GaN_HEMT_Datasets"
report = {"archives": [], "rdg_csv": [], "dfo_csv": []}


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for data in iter(lambda: f.read(1024 * 1024), b""):
            h.update(data)
    return h.hexdigest()


for archive in sorted(root.glob("*/original/*.zip")):
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    report["archives"].append({"file": str(archive.relative_to(root)), "bytes": archive.stat().st_size, "sha256": sha256(archive), "zip_crc_pass": True})

for path in sorted((root / "01_Real_IV_CV_TLN2_GS65030" / "extracted" / "Data").rglob("*.csv")):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, skipinitialspace=True))
    names = next(row[1:] for row in rows if row and row[0].strip() == "DataName")
    data = [row[1:] for row in rows if row and row[0].strip() == "DataValue"]
    assert data and all(len(row) == len(names) for row in data), path.name
    values = [float(value.strip()) for row in data for value in row]
    nonfinite = sum(not math.isfinite(value) for value in values)
    assert not nonfinite, path.name
    report["rdg_csv"].append({"file": str(path.relative_to(root)), "records": len(data), "columns": names, "all_values_numeric_and_finite": True})

dfo = root / "02_ASM_HEMT_DFO_Measurements"
for path in sorted((dfo / "extracted" / "notebooks" / "HEMT_ex").rglob("*.csv")):
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        data = list(reader)
    assert columns and data
    assert all(set(row) == set(columns) and all(value is not None for value in row.values()) for row in data), path.name
    assert all(math.isfinite(float(value)) for row in data for value in row.values()), path.name
    report["dfo_csv"].append({"file": str(path.relative_to(root)), "records": len(data), "columns": columns, "all_values_numeric_and_finite": True})


def numeric_rows(relative):
    with (dfo / "extracted" / "notebooks" / "HEMT_ex" / relative).open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader)
        return [tuple(float(v) for v in row) for row in reader]


clean = numeric_rows("ngspice_notebook_and_files/id_gm_meas_data.csv")
train = numeric_rows("Clipped_Train_Val_Split/id_gm_meas_train_clipped.csv")
test = numeric_rows("Clipped_Train_Val_Split/id_gm_meas_test_clipped.csv")
assert len(clean) == 6030 and len(train) == 4824 and len(test) == 1206
assert not set(train).intersection(test)
assert Counter(train + test) == Counter(clean)
report["dfo_clean_split"] = {"clean_rows": len(clean), "train_rows": len(train), "test_rows": len(test), "no_row_overlap": True, "union_equals_full_data": True}

commit = "a8d945a1d2f70c27998be7d0071cd6602bca02b5"
tree_path = dfo / "source_git_tree.json"
if not tree_path.exists():
    url = f"https://api.github.com/repos/rafapm/dfo_parameter_extraction/git/trees/{commit}?recursive=1"
    request = urllib.request.Request(url, headers={"User-Agent": "GaN-HEMT-dataset-verification"})
    with urllib.request.urlopen(request, timeout=25) as response:
        tree_path.write_bytes(response.read())
tree = json.loads(tree_path.read_text(encoding="utf-8"))
assert not tree.get("truncated")
expected = {x["path"]: x["sha"] for x in tree["tree"] if x["type"] == "blob"}
verified = 0
for path in (dfo / "extracted").rglob("*"):
    if path.is_file():
        relative = path.relative_to(dfo / "extracted").as_posix()
        data = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        assert actual == expected[relative], relative
        verified += 1
report["dfo_git_blob_verification"] = {"commit": commit, "verified_files": verified, "all_match": True}

manifest = json.loads((root / "download_manifest.json").read_text(encoding="utf-8"))
assert not manifest["errors"] and len(manifest["sources"]) == 3
assert manifest["sources"][0]["publisher_md5_verified"]
report["summary"] = {
    "rdg_measurement_csv_files": len(report["rdg_csv"]),
    "rdg_measurement_records": sum(x["records"] for x in report["rdg_csv"]),
    "dfo_extracted_csv_files": len(report["dfo_csv"]),
    "dfo_unique_clean_records": len(clean),
    "official_model_package_is_dataset": False,
    "download_errors": [],
}
(root / "validation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
checksums = [f"{sha256(path)}  {path.relative_to(root).as_posix()}" for path in sorted(root.rglob("*")) if path.is_file() and path.name != "SHA256SUMS.txt"]
(root / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
print(json.dumps({"summary": report["summary"], "dfo_split": report["dfo_clean_split"], "git_blob_verification": report["dfo_git_blob_verification"]}, ensure_ascii=False))
