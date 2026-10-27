from __future__ import annotations

import hashlib
import json
import shutil
import stat
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
WORKSPACE = Path(__file__).resolve().parent.parent
ROOT = WORKSPACE / "outputs" / "GaN_HEMT_Datasets"
ROOT.mkdir(parents=True, exist_ok=True)
HEADERS = {"User-Agent": "Mozilla/5.0 (GaN HEMT research dataset acquisition)"}
COMMIT = "a8d945a1d2f70c27998be7d0071cd6602bca02b5"
report = {"downloaded_at_utc": datetime.now(timezone.utc).isoformat(), "sources": [], "errors": []}


def log(message):
    print(message, flush=True)


def fetch(url, target, limit=100 * 1024 * 1024):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        log(f"Reusing {target.relative_to(ROOT)} ({target.stat().st_size} bytes)")
        return target
    partial = target.with_name(target.name + ".part")
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=35) as response, partial.open("wb") as out:
                if int(response.headers.get("Content-Length", "0")) > limit:
                    raise ValueError("Download exceeds size limit")
                total = 0
                while True:
                    chunk = response.read(512 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > limit:
                        raise ValueError("Download exceeds size limit")
                    out.write(chunk)
                if not total:
                    raise ValueError("Empty download")
            partial.replace(target)
            log(f"Downloaded {target.relative_to(ROOT)} ({total} bytes)")
            return target
        except Exception as exc:
            if partial.exists():
                partial.unlink()
            if attempt == 3:
                raise
            log(f"Retry {attempt}: {target.name}: {exc}")
            time.sleep(1)


def checksum(path, algorithm="sha256"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unpack(archive, destination, select=None):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(archive) as source:
        bad = source.testzip()
        if bad:
            raise ValueError(f"Archive CRC failure: {bad}")
        if sum(info.file_size for info in source.infolist()) > 500 * 1024 * 1024:
            raise ValueError("Archive expands beyond limit")
        for info in source.infolist():
            if info.is_dir():
                continue
            member = PurePosixPath(info.filename)
            if member.is_absolute() or ".." in member.parts or "\\" in info.filename or ":" in info.filename:
                raise ValueError(f"Unsafe archive member: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"Archive symlink: {info.filename}")
            relative = select(member) if select else member
            if relative is None:
                continue
            target = (destination / Path(*relative.parts)).resolve()
            target.relative_to(destination)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as original, target.open("wb") as out:
                shutil.copyfileobj(original, out)
            extracted.append(str(target.relative_to(ROOT)))
    log(f"Verified ZIP and extracted {len(extracted)} files: {destination.relative_to(ROOT)}")
    return extracted


def rdg():
    directory = ROOT / "01_Real_IV_CV_TLN2_GS65030"
    metadata_url = "https://entrepot.recherche.data.gouv.fr/api/datasets/:persistentId/?persistentId=doi:10.57745/IZ6LY2"
    metadata_file = fetch(metadata_url, directory / "source_metadata.json", 10 * 1024 * 1024)
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    version = metadata["data"]["latestVersion"]
    files = version["files"]
    assert len(files) == 1 and not files[0]["restricted"]
    file = files[0]["dataFile"]
    download_url = "https://entrepot.recherche.data.gouv.fr/api/access/datafile/" + str(file["id"])
    archive = fetch(download_url, directory / "original" / file["filename"])
    assert archive.stat().st_size == file["filesize"], "Dataverse size mismatch"
    assert checksum(archive, "md5") == file["checksum"]["value"], "Dataverse MD5 mismatch"
    # Remove the redundant top-level package directory so source filenames fit Windows paths.
    extracted = unpack(archive, directory / "extracted", lambda member: PurePosixPath(*member.parts[1:]))
    report["sources"].append({
        "id": "rdg_iv_cv", "title": "Characterization flowchart and data for Compact Models of GaN-on-Si HEMTs Driven by Wide-Range Current",
        "source_url": "https://doi.org/10.57745/IZ6LY2", "metadata_url": metadata_url,
        "version": str(version["versionNumber"]) + "." + str(version["versionMinorNumber"]),
        "license": version.get("license"), "download_url": download_url,
        "original_archive": str(archive.relative_to(ROOT)), "publisher_md5_verified": True,
        "archive_sha256": checksum(archive), "extracted_files": extracted,
        "coverage": ["Measured I-V", "Measured C-V", "TLN2", "GS65030"],
    })


def dfo():
    directory = ROOT / "02_ASM_HEMT_DFO_Measurements"
    archive_url = f"https://codeload.github.com/rafapm/dfo_parameter_extraction/zip/{COMMIT}"
    archive = fetch(archive_url, directory / "original" / f"dfo_parameter_extraction_{COMMIT[:12]}.zip")

    def select(member):
        relative = PurePosixPath(*member.parts[1:])
        if str(relative) in {"README.md", "LICENSE"}:
            return relative
        if str(relative).startswith("notebooks/HEMT_ex/"):
            if relative.suffix.lower() == ".csv" and "optuna" not in relative.name.lower():
                return relative
            if relative.suffix.lower() == ".json" or relative.name == "ASM-HEMT_Modeling_4x50_DFO_clean.mdl":
                return relative
        return None

    extracted = unpack(archive, directory / "extracted", select)
    report["sources"].append({
        "id": "asm_hemt_dfo", "title": "Compact Model Parameter Extraction via Derivative-Free Optimization: GaN HEMT data",
        "source_url": "https://github.com/rafapm/dfo_parameter_extraction", "commit": COMMIT,
        "download_url": archive_url, "license": "Repository MIT license; retain embedded third-party notices",
        "original_archive": str(archive.relative_to(ROOT)), "archive_sha256": checksum(archive),
        "extracted_files": extracted, "coverage": ["Measured Id and gm", "Original clean train/test split", "Author-provided outlier-corrupted variants", "Fitted curves and parameters"],
        "selection_note": "Full upstream ZIP preserved. Only HEMT measurement/result CSVs, parameter JSONs, original ICCAP model, README and LICENSE extracted. No downloaded code or binary executed.",
    })


def asm_benchmarks():
    directory = ROOT / "03_ASM_HEMT_Model_Reference"
    url = "https://www.iitk.ac.in/asm/asm_package/CMC.zip"
    archive = fetch(url, directory / "original" / "CMC.zip", 20 * 1024 * 1024)
    extracted = unpack(archive, directory / "extracted")
    report["sources"].append({
        "id": "asm_official_model_reference", "title": "IIT Kanpur ASM-HEMT 101.0.0 standard release",
        "source_url": "https://www.iitk.ac.in/asm/", "download_url": url, "version": "101.0.0",
        "license": "See bundled copyright/license notices. Verilog-A code uses ECL-2.0; do not infer the website license for all bundled files.",
        "original_archive": str(archive.relative_to(ROOT)), "archive_sha256": checksum(archive),
        "extracted_files": extracted, "coverage": ["Verilog-A model source", "Technical manual", "License and copyright notices"],
        "selection_note": "Supplementary model reference, not a numerical dataset. Although the publisher page mentions benchmarks, the downloaded ZIP contains only the manual, Verilog-A source, LICENSE and NOTICE. No simulation was run.",
    })


for name, operation in [("rdg", rdg), ("dfo", dfo), ("asm_benchmarks", asm_benchmarks)]:
    try:
        log(f"Starting {name}")
        operation()
    except Exception as exc:
        log(f"FAILED {name}: {exc}")
        report["errors"].append({"source": name, "error": str(exc)})
    (ROOT / "download_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

log(json.dumps({"completed": [x["id"] for x in report["sources"]], "errors": report["errors"]}, ensure_ascii=False))
