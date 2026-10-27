from __future__ import annotations

import base64
import csv
import hashlib
import html
import json
import math
import os
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

WORK = Path(__file__).resolve().parent
WS = WORK.parent
RAW = WS / "outputs" / "GaN_HEMT_Datasets"
OUT = WS / "outputs" / "GaN_HEMT_Prepared"
os.environ["MPLCONFIGDIR"] = str(WORK / "mpl_config")
sys.path.insert(0, str(WORK / "plot_dependencies"))
sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

FIELDS = [
    "point_id", "device_id", "measurement_type", "mode", "curve_id", "train_test_split",
    "vds_V", "vgs_V", "id_A", "ig_A", "gm_S", "capacitance_F", "conductance_S", "capacitance_type",
    "vds_set_V", "vgs_set_V", "temperature_K", "temperature_context_K", "frequency_Hz", "ac_amplitude_V",
    "pulse_width_s", "pulse_period_s", "pulse_delay_s", "pulse_measurement_delay_s",
    "pulse_vds_base_V", "pulse_vgs_base_V", "drain_current_limit_A", "gate_current_limit_A",
    "near_current_limit", "bias_deviation", "compliance_suspected", "nonpositive_forward_id", "negative_gm", "quality_flags",
    "source_id", "source_file_id", "source_row", "source_file", "source_sha256", "source_record_label", "source_iteration", "record_time_local",
]
NUMERIC = set(FIELDS[6:13] + FIELDS[14:28] + ["source_row", "source_iteration"])
BOOLS = {"near_current_limit", "bias_deviation", "compliance_suspected", "nonpositive_forward_id", "negative_gm"}
for directory in ["data/by_device", "metadata", "previews/source_curves", "raw_selected"]:
    (OUT / directory).mkdir(parents=True, exist_ok=True)


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = fields or list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: int(v) if isinstance(v, bool) else v for k, v in row.items()})


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_instrument(path):
    metadata, data, names = [], [], None
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f, skipinitialspace=True)
        for row in reader:
            row = [cell.strip() for cell in row]
            if not row:
                continue
            if row[0] == "DataName":
                names = row[1:]
            elif row[0] == "DataValue":
                assert names and len(row) == len(names) + 1
                data.append((reader.line_num, dict(zip(names, map(float, row[1:])))))
            else:
                metadata.append({"line": reader.line_num, "cells": row})
    assert data
    indexed = {r["cells"][1]: r["cells"][2:] for r in metadata if len(r["cells"]) >= 2 and r["cells"][0] in {"TestParameter", "MetaData", "AnalysisSetup"}}
    dim1 = next(int(r["cells"][1]) for r in metadata if r["cells"][0] == "Dimension1")
    dim2 = next(int(r["cells"][1]) for r in metadata if r["cells"][0] == "Dimension2")
    assert dim1 * dim2 == len(data)
    return names, metadata, indexed, dim1, dim2, data


def scalar(meta, key, default=None):
    values = meta.get(key, [])
    return float(values[0]) if values and values[0] else default


def cell(meta, key, default=""):
    return meta.get(key, [default])[0] if meta.get(key) else default


def date_in_filename(name):
    match = re.search(r";\s*(\d+)_(\d+)_(\d+)\s+(\d+)_(\d+)_(\d+)\s+(AM|PM)", name)
    if not match:
        return None
    month, day, year, hour, minute, second = map(int, match.groups()[:6])
    hour = hour % 12 + (12 if match.group(7) == "PM" else 0)
    return datetime(year, month, day, hour, minute, second).isoformat()


measurements, conditions, inventory = [], {}, []
rdg_base = RAW / "01_Real_IV_CV_TLN2_GS65030" / "extracted" / "Data"
source_hashes_before = {}
for path in sorted(rdg_base.rglob("*.csv")):
    names, metadata, meta, n1, n2, raw_rows = parse_instrument(path)
    sha = digest(path)
    source_hashes_before[str(path)] = sha
    file_id = "RDG_" + sha[:12]
    device = path.parent.name
    kind = "cv" if path.name.startswith("C") else "reverse_iv" if path.name.startswith("Isd") else "output_iv" if path.name.startswith("Ids-Vds") else "transfer_iv"
    channel_v = meta["Channel.VName"]
    channel_f = meta["Channel.Func"]
    channel_mode = meta["Channel.Mode"]
    mode = "ac" if kind == "cv" else "pulsed" if "VPULSE" in channel_mode else "continuous"
    cap_kind = path.name.split("-")[0] if kind == "cv" else ""
    label_match = re.search(r"\[([^;]+?)(?:\s*;|\s+_)", path.name)
    label = label_match.group(1).strip() if label_match else ""
    record_time = datetime.strptime(cell(meta, "TestRecord.RecordTime"), "%m/%d/%Y %H:%M:%S").isoformat()
    filename_time = date_in_filename(path.name)
    date_conflict = bool(filename_time and record_time != filename_time)
    primary_start = scalar(meta, "Measurement.Primary.Start")
    primary_stop = scalar(meta, "Measurement.Primary.Stop")
    primary_step = scalar(meta, "Measurement.Primary.Step")
    grid_ambiguous = primary_step is not None and not math.isclose(primary_start + primary_step * (n1 - 1), primary_stop, rel_tol=1e-9, abs_tol=1e-9)
    channel_limits = {}
    for c, func in zip(channel_v, channel_f):
        pos = channel_v.index(c)
        if func == "VAR1":
            limit = scalar(meta, "Measurement.Primary.Compliance")
        elif func == "VAR2":
            limit = scalar(meta, "Measurement.Secondary.Compliance")
        else:
            values = meta.get("Measurement.Bias.Compliance", [])
            limit = float(values[pos]) if len(values) > pos and values[pos] else None
        channel_limits[c] = abs(limit) if limit is not None and limit != 0 else None
    cp = OUT / "raw_selected" / (file_id + ".csv")
    shutil.copyfile(path, cp)
    conditions[file_id] = {
        "source_file": path.relative_to(RAW).as_posix(), "sha256": sha, "raw_copy": cp.relative_to(OUT).as_posix(),
        "device_id": device, "source_record_label": label, "physical_specimen_id": None,
        "source_record_label_note": "Parenthesized suffix equals TestRecord.IterationIndex; it is a record iteration label, not proof of a distinct physical specimen.",
        "data_columns": names, "dimension1": n1, "dimension2": n2, "record_time_local": record_time,
        "record_time_filename": filename_time, "timestamp_timezone": None,
        "unit_evidence": "Instrument AnalysisSetup axis/list units (V, A, F where present); author idVgs.m uses Id in A and cVds.m uses C in F. G uses the conductance SI convention (S).",
        "cv_terminal_wiring": "Protocol section 9 / Figure 4 provides Ciss/Coss/Crss wiring diagrams; the CSV does not include a measured Vgs column or per-record wiring verification" if kind == "cv" else None,
        "protocol_reference": "raw_selected/Characterization_protocol.pdf, sections 6.2, 9 and 10",
        "setpoint_grid_ambiguous": grid_ambiguous,
        "setpoint_grid_note": "If declared Step and Stop disagree with Dimension1, programmed values on VAR1 are left null; original fields remain in this metadata.",
        "full_source_metadata": metadata,
    }
    for point_index, (line, raw) in enumerate(raw_rows):
        sweep, point = divmod(point_index, n1)
        setpoints = {}
        for c, func in zip(channel_v, channel_f):
            pos = channel_v.index(c)
            if func == "VAR1":
                setpoints[c] = None if grid_ambiguous else primary_start + (primary_stop - primary_start) * point / (n1 - 1) if n1 > 1 else primary_start
            elif func == "VAR2":
                setpoints[c] = scalar(meta, "Measurement.Secondary.Start") + scalar(meta, "Measurement.Secondary.Step", 0) * sweep
            else:
                values = meta.get("Measurement.Bias.Source", [])
                setpoints[c] = float(values[pos]) if len(values) > pos and values[pos] else None
        row = dict.fromkeys(FIELDS)
        row.update(point_id=f"{file_id}_{point_index+1:05}", device_id=device, measurement_type=kind, mode=mode,
                   curve_id=f"{file_id}_S{sweep+1:02}", train_test_split="unassigned", vds_V=raw.get("Vds"), vgs_V=raw.get("Vgs"),
                   id_A=raw.get("Ids"), ig_A=raw.get("Igs"), capacitance_F=raw.get("C"), conductance_S=raw.get("G"),
                   capacitance_type=cap_kind, vds_set_V=setpoints.get("Vds"), vgs_set_V=setpoints.get("Vgs"),
                   frequency_Hz=scalar(meta, "Measurement.Secondary.Frequency") if kind == "cv" else None,
                   ac_amplitude_V=scalar(meta, "Measurement.Secondary.ACLevel") if kind == "cv" else None,
                   drain_current_limit_A=channel_limits.get("Vds"), gate_current_limit_A=channel_limits.get("Vgs"),
                   source_id="RDG_IZ6LY2_V6", source_file_id=file_id, source_row=line,
                   source_file=path.relative_to(RAW).as_posix(), source_sha256=sha, source_record_label=label,
                   source_iteration=int(cell(meta, "TestRecord.IterationIndex")), record_time_local=record_time)
        if mode == "pulsed":
            for out, key in [("pulse_width_s", "Duration"), ("pulse_period_s", "Period"), ("pulse_delay_s", "Delay"), ("pulse_measurement_delay_s", "MeasurementDelay")]:
                row[out] = scalar(meta, "Measurement.Pulse." + key)
            for c in ["Vds", "Vgs"]:
                if c in channel_v and channel_mode[channel_v.index(c)] == "VPULSE":
                    row["pulse_" + c.lower() + "_base_V"] = scalar(meta, "Measurement.Pulse.Base")
        row["near_current_limit"] = bool(row["id_A"] is not None and row["drain_current_limit_A"] and abs(row["id_A"]) >= 0.99 * row["drain_current_limit_A"])
        row["bias_deviation"] = any(row[axis + "_V"] is not None and row[axis + "_set_V"] is not None and abs(row[axis + "_V"] - row[axis + "_set_V"]) > max(0.02, 0.01 * abs(row[axis + "_set_V"])) for axis in ["vds", "vgs"])
        row["compliance_suspected"] = row["near_current_limit"] and row["bias_deviation"]
        row["nonpositive_forward_id"] = row["id_A"] is not None and row["id_A"] <= 0 and kind in {"output_iv", "transfer_iv"}
        row["negative_gm"] = False
        flags = ["temperature_unreported"]
        for flag in ["near_current_limit", "bias_deviation", "compliance_suspected", "nonpositive_forward_id"]:
            if row[flag]: flags.append(flag)
        if kind == "cv": flags.append("cv_gate_bias_unreported")
        if grid_ambiguous: flags.append("setpoint_grid_ambiguous")
        if date_conflict: flags.append("record_time_conflict")
        row["quality_flags"] = ";".join(flags)
        measurements.append(row)
    inventory.append({"source_file_id": file_id, "device_id": device, "measurement_type": kind, "mode": mode,
                      "rows": len(raw_rows), "disposition": "included_primary", "source_file": path.relative_to(RAW).as_posix(),
                      "sha256": sha, "duplicate_of": "", "note": "原始 DataValue 完整保留"})

dfo_root = RAW / "02_ASM_HEMT_DFO_Measurements" / "extracted" / "notebooks" / "HEMT_ex"
clean_file = dfo_root / "ngspice_notebook_and_files" / "id_gm_meas_data.csv"
with clean_file.open(newline="", encoding="utf-8") as f:
    clean = list(csv.DictReader(f))
split_lookup = {}
for label, name in [("train", "id_gm_meas_train_clipped.csv"), ("test", "id_gm_meas_test_clipped.csv")]:
    p = dfo_root / "Clipped_Train_Val_Split" / name
    with p.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = tuple(float(r[c + "_" + label]) for c in ["vd", "vg", "id_meas", "gm_meas"])
            assert key not in split_lookup
            split_lookup[key] = label
sha = digest(clean_file)
source_hashes_before[str(clean_file)] = sha
file_id = "DFO_" + sha[:12]
shutil.copyfile(clean_file, OUT / "raw_selected" / (file_id + ".csv"))
mdl = dfo_root / "ASM-HEMT_Modeling_4x50_DFO_clean.mdl"
mdl_text = mdl.read_text(encoding="utf-8", errors="replace")
assert 'element 7 "Name" "TEMP"\nelement 7 "Value" "25"' in mdl_text
conditions[file_id] = {"source_file": clean_file.relative_to(RAW).as_posix(), "sha256": sha,
    "raw_copy": "raw_selected/" + file_id + ".csv", "device_id": "DFO_4x50", "source_device_name": "Chip_4_4x50_1551p5",
    "data_columns": list(clean[0]), "temperature_measurement_K": None, "temperature_model_context_K": 298.15,
    "temperature_evidence": {"file": mdl.relative_to(RAW).as_posix(), "lines": [23, 24], "note": "Model Variable Table TEMP=25 C; this is a model setting, not independently verified measurement temperature."},
    "model_version_in_mdl": "101.2", "model_version_in_reference_package": "101.0.0",
    "bias_evidence": "vd and vg are bias coordinates supplied by the author; measured terminal voltage vs programmed voltage is not separately provided.",
    "unit_evidence": "Author IC-CAP/netlist uses standard SI device quantities; gm is transconductance dId/dVg in A/V = S. No width normalization applied.",
    "waveform_mode": "not_recorded_in_csv", "original_split": {"train": 4824, "test": 1206},
}
gate_values = sorted({float(r["vg"]) for r in clean})
for i, raw in enumerate(clean, 2):
    vd, vg, id_val, gm = (float(raw[c]) for c in ["vd", "vg", "id_meas", "gm_meas"])
    row = dict.fromkeys(FIELDS)
    row.update(point_id=f"{file_id}_{i-1:05}", device_id="DFO_4x50", measurement_type="iv_gm_grid", mode="unspecified",
               curve_id=f"{file_id}_G{gate_values.index(vg)+1:02}", train_test_split=split_lookup[(vd, vg, id_val, gm)],
               vds_V=vd, vgs_V=vg, id_A=id_val, gm_S=gm, temperature_context_K=298.15,
               near_current_limit=False, bias_deviation=False, compliance_suspected=False,
               nonpositive_forward_id=id_val <= 0, negative_gm=gm < 0,
               quality_flags="temperature_model_context_only" + (";negative_gm" if gm < 0 else ""),
               source_id="DFO_a8d945a1d2f7", source_file_id=file_id, source_row=i,
               source_file=clean_file.relative_to(RAW).as_posix(), source_sha256=sha,
               source_record_label="Chip_4_4x50_1551p5")
    measurements.append(row)

hash_first = {sha: clean_file.relative_to(RAW).as_posix()}
for p in sorted(dfo_root.rglob("*.csv"), key=lambda p: (p != clean_file, str(p))):
    h = digest(p)
    with p.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if p == clean_file: status, note = "included_primary", "基础数据；已逐行映射原作者 train/test 标签"
    elif "sim" in p.name: status, note = "excluded_fit_result", "拟合输出，不作为实测真值"
    elif "train" in p.name or "test" in p.name: status, note = "excluded_split_copy", "已有数据的划分副本，不新增样本"
    elif h in hash_first: status, note = "excluded_duplicate", "与已有文件字节相同，不新增样本"
    elif "glitched" in str(p).lower(): status, note = "excluded_author_corrupted", "作者人为加入异常点的压力测试版本，未混入基础数据"
    else: status, note = "excluded_alternate", "替代结果版本，保留原包供后续专门核实"
    inventory.append({"source_file_id": "DFO_" + h[:12], "device_id": "DFO_4x50", "measurement_type": "iv_gm_grid", "mode": "unspecified",
                      "rows": len(rows)-1, "disposition": status, "source_file": p.relative_to(RAW).as_posix(), "sha256": h,
                      "duplicate_of": hash_first.get(h, "") if p != clean_file else "", "note": note})
    hash_first.setdefault(h, p.relative_to(RAW).as_posix())

assert len(measurements) == 9868
assert len({r["point_id"] for r in measurements}) == 9868
assert Counter(r["device_id"] for r in measurements) == {"TLN2": 2121, "GS65030": 1717, "DFO_4x50": 6030}
assert all(r["temperature_K"] is None for r in measurements)
assert all(r["pulse_width_s"] is None for r in measurements if r["mode"] != "pulsed")
for r in measurements:
    for k in NUMERIC:
        assert r[k] is None or isinstance(r[k], (int, float)) and math.isfinite(r[k]), (r["point_id"], k)
    assert r["source_row"] > 0

by_file = defaultdict(list)
for r in measurements: by_file[r["source_file_id"]].append(r)
for fileid, rows in by_file.items():
    p = RAW / rows[0]["source_file"]
    assert digest(p) == rows[0]["source_sha256"]
    if rows[0]["source_id"].startswith("RDG"):
        _, _, _, _, _, source = parse_instrument(p)
        for row, (line, raw) in zip(rows, source):
            for original, unified in [("Ids", "id_A"), ("Vds", "vds_V"), ("Vgs", "vgs_V"), ("Igs", "ig_A"), ("C", "capacitance_F"), ("G", "conductance_S")]:
                assert row[unified] == raw.get(original)
            assert line == row["source_row"]

stats = {}
for device in ["TLN2", "GS65030", "DFO_4x50"]:
    selected = [r for r in measurements if r["device_id"] == device]
    stats[device] = {"records": len(selected), "files": len({r["source_file_id"] for r in selected}),
        "curves": len({r["curve_id"] for r in selected}), "compliance_suspected": sum(r["compliance_suspected"] for r in selected),
        "bias_deviation": sum(r["bias_deviation"] for r in selected), "near_current_limit": sum(r["near_current_limit"] for r in selected),
        "negative_gm": sum(r["negative_gm"] for r in selected), "nonpositive_forward_id": sum(r["nonpositive_forward_id"] for r in selected),
        "vds_range_V": [min(r["vds_V"] for r in selected), max(r["vds_V"] for r in selected)]}
curve_stats = []
for cid in dict.fromkeys(r["curve_id"] for r in measurements):
    rows = [r for r in measurements if r["curve_id"] == cid]
    curve_stats.append({"curve_id": cid, "device_id": rows[0]["device_id"], "measurement_type": rows[0]["measurement_type"], "mode": rows[0]["mode"],
        "records": len(rows), "capacitance_type": rows[0]["capacitance_type"],
        "vgs_set_V": rows[0]["vgs_set_V"] if rows[0]["measurement_type"] in {"output_iv", "reverse_iv"} else None,
        "frequency_Hz": rows[0]["frequency_Hz"], "pulse_width_s": rows[0]["pulse_width_s"],
        "compliance_suspected": sum(r["compliance_suspected"] for r in rows), "bias_deviation": sum(r["bias_deviation"] for r in rows),
        "source_file_id": rows[0]["source_file_id"]})

compliance_total = sum(r["compliance_suspected"] for r in measurements)
bias_total = sum(r["bias_deviation"] for r in measurements)
negative_gm = sum(r["negative_gm"] for r in measurements)
gaps = []


def gap(code, priority, scope, missing, evidence, effect, action):
    gaps.append({"gap_id": code, "priority": priority, "scope": scope, "gap": missing, "evidence": evidence, "modeling_effect": effect, "next_action": action, "status": "待补充或复核"})


gap("G01", "高", "全部器件", "缺少 S 参数", "全部输入文件均无复数 S11/S12/S21/S22 或 Touchstone 数据", "无法独立验证 RF 寄生网络与频率响应", "获取带偏置、频率、参考阻抗、校准/去嵌说明的 S 参数")
gap("G02", "高", "全部器件", "缺少可核实的逐点测量温度与温度扫描", "9,868 条 temperature_K 均为空；DFO 模型 TEMP=25 C 仅放入 temperature_context_K=298.15", "温度外推和自热参数缺少测量约束", "补充环境/台面温度、稳态条件及多个温度点，不用模型默认温度替代实测温度")
gap("G03", "高", "TLN2 / GS65030", "限流与实际偏置偏离需复核", f"{compliance_total} 点同时接近漏极限流设置并偏离标称电压；{bias_total} 点存在设定/实际电压偏离；协议 6.2 明确说明高电流回路压降", "直接按标称固定 Vds 拟合可能错误；脉冲中的设定/实际压差不自动等同数据错误", "使用实际 vds_V/vgs_V；按标记复核仪器状态和测试回路，暂不自动删点")
gap("G04", "高", "TLN2 / GS65030", "脉冲时序覆盖不足", "已有脉宽均为 150 us；周期 TLN2=20 ms、GS65030=50 ms；没有多脉宽与恢复时间扫描", "不足以唯一约束陷阱与热时间常数", "补充脉宽、周期、静态预偏置和恢复过程；确认未脉冲端的静态偏置")
gap("G05", "中", "TLN2 / GS65030", "C-V 仅单频与单一偏置路径", "6 个电容文件频率均为 100 kHz；ACLevel TLN2=0.1 V、GS65030=0.03 V；协议图 4 有接线说明，但 CSV 没有逐点 Vgs", "已有端接协议，仍缺完整的多频与二维偏置电容网格", "按协议图 4 核对各记录实际端接、AC 幅值约定及去嵌，补充多频/多栅偏置 C-V")
gap("G06", "中", "全部器件", "几何与同一物理样品关系不完整", "TLN2/GS65030 缺少可追溯的栅宽/栅长和样品序列号；括号后缀与记录迭代号一致", "无法可靠做宽度归一化或确认跨测量的样品一致性", "补齐几何、封装/接触与样品关系；DFO 的 4x50/模型参数只作为来源上下文")
gap("G07", "中", "DFO_4x50", "模型版本需与比赛环境对齐", "原始 MDL 的 ModelVersion=101.2；已下载官方参考包为 101.0.0", "参数名称、默认值或物理子模块可能不一致", "取得比赛 ASM-HEMT 精确版本与模型卡 Schema 后再建立参数映射")
gap("G08", "中", "全部器件", "未覆盖比赛式隐藏网格验证", "DFO 保留作者 4,824/1,206 行划分，但 train/test 共享偏置轴取值；RDG 未提供划分", "行级留出不能证明对未知温度/偏置区间的泛化", "后续在明确开发目标后设计偏置区域/温度留出，保留当前作者划分作基线")
gap("G09", "中", "DFO_4x50 / RDG 正向电流", "低信号符号与噪声需评估", f"DFO 有 {negative_gm} 个负 gm 值；RDG 正向测量有非正电流；反向导通负 Id 属保留的符号约定", "对数损失不能直接应用非正值，噪声可能影响导数和 QA", "保留原值；后续依据仪器不确定度与信号区间选择损失，不做无依据裁剪")
gap("G10", "中", "全部器件", "缺少逐点仪器状态和不确定度", "协议有通用标准电容核对说明，但未给各记录误差条、逐点 compliance 状态或可追溯的校准结果", "不能把标记等同于仪器确认事件，也不能给出可靠测量置信区间", "补充原始状态码、逐记录校准、重复测量和测量误差")
gap("G11", "低", "TLN2 反向脉冲记录", "文件名时间与文件内记录时间不一致", "文件名为 2025-08-18 12:20:14；TestRecord.RecordTime 为 2025-08-12 12:20:14", "影响批次与测试先后顺序追溯", "向原作者核实日期；保留两种证据，不自动改写")
gap("G12", "中", "DFO 作者附带文件", "重复/异常点/拟合输出需保持区分", "25 个 HEMT CSV 中仅基础文件的 6,030 行进入主表；其余划分与结果未重复并入", "重复计数或把拟合结果当真值会造成泄漏", "依据 source_inventory.csv 选择压力测试版本，独立于基础提参数据")
gap("G13", "高", "比赛接口资料", "官方 Q&A、MCP 工具定义与模型卡 Schema 尚未接入", "当前资料包中没有这些接口和提交规范文件", "可做离线数据开发，暂不能验证正式提参与提交兼容性", "获得官方文档、版本、服务权限后另行开展接口适配")
gap("G14", "低", "GS65030 三个 C-V 文件", "扫描步长和停止值不完全一致", "Step=6.4995 V、Dimension1=101，对应末点 649.95 V；Stop 字段为 649.9995 V", "无法从元数据唯一确认编程扫描网格；实际 Vds 记录仍可使用", "保留实际电压，将这三份文件的 vds_set_V 留空，核对原始仪器设置")

descriptions = {
"point_id": "来源文件哈希及原记录位置构成的稳定记录 ID", "device_id": "名义器件组；不等于已确认的物理样品序列号", "measurement_type": "output_iv / transfer_iv / reverse_iv / cv / iv_gm_grid", "mode": "continuous / pulsed / ac / unspecified；DFO CSV 未记录波形模式", "curve_id": "RDG 按 Dimension1/Dimension2 分组；DFO 按原 vg 坐标分组", "train_test_split": "DFO 原作者 train/test；RDG 为 unassigned", "vds_V": "RDG 实际记录漏源电压；DFO 原 vd 偏置坐标", "vgs_V": "RDG 实际记录栅源电压；DFO 原 vg 偏置坐标", "id_A": "保留原始带符号 Ids / id_meas，未归一化", "ig_A": "原始 Igs", "gm_S": "原作者 gm_meas，保留负值；未对 RDG 估算 gm", "capacitance_F": "原始 C；物理类型见 capacitance_type", "conductance_S": "原始 G，按电导 SI 约定标记；负值保留", "capacitance_type": "Ciss / Coss / Crss；未转为本征 Cgs/Cgd/Cds", "vds_set_V": "由原始扫描参数重建的漏极设定电压，区别于实际值", "vgs_set_V": "由原始扫描参数重建的栅极设定电压，区别于实际值", "temperature_K": "可核实的实际测量温度；当前全部缺失", "temperature_context_K": "DFO MDL TEMP=25 C 转换为 298.15 K，仅为模型上下文", "frequency_Hz": "C-V 的原始 Measurement.Secondary.Frequency", "ac_amplitude_V": "原始 ACLevel；RMS/峰值约定未在 CSV 中明确", "pulse_width_s": "仅 VPULSE 模式采用原 Duration，单位秒", "pulse_period_s": "仅 VPULSE 模式采用原 Period，单位秒", "pulse_delay_s": "原脉冲 Delay，单位秒", "pulse_measurement_delay_s": "原脉冲 MeasurementDelay，单位秒", "pulse_vds_base_V": "仅当 Vds 通道为 VPULSE 时填写原 Base", "pulse_vgs_base_V": "仅当 Vgs 通道为 VPULSE 时填写原 Base；当前缺失", "drain_current_limit_A": "按通道功能映射的原电流限值绝对值", "gate_current_limit_A": "按通道功能映射的原电流限值绝对值", "near_current_limit": "|Id| >= 0.99 × 漏极限流设置，仅启发式标记", "bias_deviation": "任一实际电压与设定值之差 > max(0.02 V, 设定值绝对值的 1%)", "compliance_suspected": "near_current_limit 与 bias_deviation 同时满足；非仪器状态码", "nonpositive_forward_id": "正向 output/transfer 数据 Id <= 0；未删除", "negative_gm": "原始 gm < 0；未删除或平滑", "quality_flags": "分号分隔；包含缺失条件与需复核信息", "source_id": "公开数据来源及版本标识", "source_file_id": "来源文件哈希标识，与 metadata/conditions.json 对应", "source_row": "原 CSV 物理行号，从 1 开始，可直接追溯", "source_file": "相对原 GaN_HEMT_Datasets 根目录的路径", "source_sha256": "原始来源文件 SHA-256", "source_record_label": "原始记录/设备标签，不据此推断独立样品", "source_iteration": "RDG TestRecord.IterationIndex", "record_time_local": "原记录时间 ISO 表达，时区未知"}
units = {k: "V" if k.endswith("_V") else "A" if k.endswith("_A") else "S" if k.endswith("_S") else "F" if k.endswith("_F") else "K" if k.endswith("_K") else "Hz" if k.endswith("_Hz") else "s" if k.endswith("_s") else "" for k in FIELDS}
dictionary = [{"field": k, "type": "boolean (0/1 in CSV)" if k in BOOLS else "number" if k in NUMERIC else "string", "unit": units[k], "missing": "空单元格 / JSON null", "description": descriptions[k]} for k in FIELDS]
write_csv(OUT / "data/unified_measurements.csv", measurements, FIELDS)
for device in stats:
    write_csv(OUT / "data/by_device" / (device + ".csv"), [r for r in measurements if r["device_id"] == device], FIELDS)
write_csv(OUT / "source_inventory.csv", inventory)
write_csv(OUT / "data_gaps.csv", gaps)
write_csv(OUT / "field_dictionary.csv", dictionary)
write_csv(OUT / "curve_summary.csv", curve_stats)
write_json(OUT / "metadata/conditions.json", conditions)
write_json(OUT / "metadata/schema.json", {"schema_version": "1.0", "fields": dictionary, "null_policy": "CSV empty cell / JSON null; never fill absent conditions with zero.", "sign_policy": "Preserve measured Vds/Ids signs, including reverse conduction.", "transformations": ["Source-column mapping", "Dimension-based grouping", "Reconstructed programmed bias stored separately", "Original DFO split mapping", "Model-only temperature context separated from measurement temperature", "Review flags; no point deletion/smoothing/interpolation/width normalization"]})
write_json(WORK / "gan_normalized_payload.json", {"fields": FIELDS, "numeric_fields": sorted(NUMERIC), "boolean_fields": sorted(BOOLS), "measurements": measurements, "stats": stats, "gaps": gaps, "inventory": inventory, "dictionary": dictionary})

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.alpha": .2, "axes.titleweight": "semibold", "savefig.facecolor": "white"})
COLORS = plt.get_cmap("tab10")


def groups(rows):
    grouped = defaultdict(list)
    for r in rows: grouped[r["curve_id"]].append(r)
    return list(grouped.values())


def line_plot(ax, rows, kind="output_iv", select_mode=None, legend=True):
    selected = [r for r in rows if r["measurement_type"] == kind and (select_mode is None or r["mode"] == select_mode)]
    if not selected:
        ax.text(.5, .5, "Not available", ha="center", va="center", transform=ax.transAxes); return
    for j, curve in enumerate(groups(selected)):
        r = curve[0]
        label = f"VGS set={r['vgs_set_V']:g} V" if kind in {"output_iv", "reverse_iv"} else r["mode"]
        x = [p["vgs_V"] if kind == "transfer_iv" else p["vds_V"] for p in curve]
        y = [p["id_A"] for p in curve]
        color = COLORS(j % 10)
        ax.plot(x, y, color=color, lw=1.3, ls="--" if r["mode"] == "continuous" else "-", label=label)
        bad = [p for p in curve if p["compliance_suspected"]]
        if bad: ax.scatter([p["vgs_V"] if kind == "transfer_iv" else p["vds_V"] for p in bad], [p["id_A"] for p in bad], s=20, facecolors="none", edgecolors="#c0392b", linewidths=.8, zorder=4)
    ax.set_xlabel("Measured $V_{GS}$ (V)" if kind == "transfer_iv" else "Measured $V_{DS}$ (V)")
    ax.set_ylabel("$I_D$ (A)")
    if legend: ax.legend(fontsize=7, loc="best", ncol=2 if len(groups(selected)) > 5 else 1, frameon=False)


def cv_plot(ax, rows):
    selected = [r for r in rows if r["measurement_type"] == "cv"]
    for curve in groups(selected):
        ax.semilogy([r["vds_V"] for r in curve], [r["capacitance_F"] * 1e12 for r in curve], label=curve[0]["capacitance_type"], lw=1.7)
    ax.set_xlabel("Measured $V_{DS}$ (V)"); ax.set_ylabel("Capacitance (pF)")
    ax.legend(frameon=False, fontsize=8)


def finish(fig, name, title, footnote):
    fig.suptitle(title, fontsize=16, y=.99, fontweight="semibold")
    fig.text(.5, .015, footnote, ha="center", fontsize=8, color="#4b5563")
    fig.tight_layout(rect=(0, .04, 1, .96), h_pad=2.5, w_pad=2)
    fig.savefig(OUT / "previews" / name, dpi=155)
    plt.close(fig)


for device in ["TLN2", "GS65030"]:
    rows = [r for r in measurements if r["device_id"] == device]
    fig, axs = plt.subplots(2, 3, figsize=(15, 8.5))
    line_plot(axs[0,0], rows, select_mode="continuous"); axs[0,0].set_title("Continuous output")
    line_plot(axs[0,1], rows, select_mode="pulsed"); axs[0,1].set_title("Pulsed output (150 us)")
    line_plot(axs[0,2], rows, "transfer_iv"); axs[0,2].set_title("Transfer: actual measured bias")
    cv_plot(axs[1,0], rows); axs[1,0].set_title("C-V at 100 kHz")
    line_plot(axs[1,1], rows, "reverse_iv"); axs[1,1].set_title("Reverse conduction (signed data)")
    for curve in groups([r for r in rows if r["measurement_type"] == "transfer_iv"]):
        axs[1,2].plot([r["vgs_V"] for r in curve], [r["vds_V"] for r in curve], label=curve[0]["mode"], lw=1.6)
        axs[1,2].axhline(curve[0]["vds_set_V"], color="#9ca3af", ls=":", lw=1)
    axs[1,2].set(xlabel="Measured $V_{GS}$ (V)", ylabel="Measured $V_{DS}$ (V)", title="Drain-bias tracking during transfer")
    axs[1,2].legend(frameon=False, fontsize=8)
    finish(fig, f"{device}_curves.png", device + " | measured curves and bias review", "Open red circles: current near configured limit + bias deviation (heuristic). Raw values retained; no fit or smoothing.")

dfo_rows = [r for r in measurements if r["device_id"] == "DFO_4x50"]
fig, axs = plt.subplots(2, 2, figsize=(12, 8.5))
for target in [-3, -2.5, -2, -1.5, -1, -.5, -.1]:
    vg = min(gate_values, key=lambda x: abs(x-target))
    curve = sorted([r for r in dfo_rows if r["vgs_V"] == vg], key=lambda r:r["vds_V"])
    axs[0,0].plot([r["vds_V"] for r in curve], [r["id_A"] for r in curve], label=f"VGS={vg:g} V")
for vd in [.1, 1, 5, 10, 20]:
    curve = sorted([r for r in dfo_rows if r["vds_V"] == vd], key=lambda r:r["vgs_V"])
    axs[0,1].semilogy([r["vgs_V"] for r in curve], [r["id_A"] for r in curve], label=f"VDS={vd:g} V")
    axs[1,0].plot([r["vgs_V"] for r in curve], [r["gm_S"] for r in curve], label=f"VDS={vd:g} V")
for label, color in [("train", "#1f77b4"), ("test", "#d97706")]:
    points = [r for r in dfo_rows if r["train_test_split"] == label]
    axs[1,1].scatter([r["vds_V"] for r in points], [r["vgs_V"] for r in points], s=3, color=color, alpha=.6, label=f"{label} (n={len(points):,})")
axs[0,0].set(xlabel="$V_{DS}$ coordinate (V)", ylabel="$I_D$ (A)", title="Output slices")
axs[0,1].set(xlabel="$V_{GS}$ coordinate (V)", ylabel="$I_D$ (A)", title="Transfer slices (log scale)")
axs[1,0].set(xlabel="$V_{GS}$ coordinate (V)", ylabel="$g_m$ (S)", title="Author-supplied transconductance")
axs[1,1].set(xlabel="$V_{DS}$ coordinate (V)", ylabel="$V_{GS}$ coordinate (V)", title="Original author train/test allocation")
for ax in axs.flat: ax.legend(fontsize=8, frameon=False, ncol=2)
finish(fig, "DFO_4x50_curves.png", "DFO GaN-on-SiC HEMT | 6,030 unique bias records", "Model TEMP=25 C is context only; verified measurement temperature is not supplied. Negative gm values are retained.")

fig, axs = plt.subplots(3, 3, figsize=(16, 11))
for col, device in enumerate(["TLN2", "GS65030"]):
    rows = [r for r in measurements if r["device_id"] == device]
    line_plot(axs[0,col], rows, select_mode="pulsed"); axs[0,col].set_title(device + " | pulsed output")
    line_plot(axs[1,col], rows, "transfer_iv"); axs[1,col].set_title(device + " | continuous / pulse transfer")
    cv_plot(axs[2,col], rows); axs[2,col].set_title(device + " | C-V, 100 kHz")
for target in [-2.5, -2, -1.5, -1, -.5, -.1]:
    vg = min(gate_values, key=lambda x:abs(x-target)); curve = [r for r in dfo_rows if r["vgs_V"]==vg]
    axs[0,2].plot([r["vds_V"] for r in curve], [r["id_A"] for r in curve], label=f"{vg:g} V")
for vd in [1, 5, 10, 20]:
    curve=sorted([r for r in dfo_rows if r["vds_V"]==vd],key=lambda r:r["vgs_V"])
    axs[1,2].semilogy([r["vgs_V"] for r in curve],[r["id_A"] for r in curve],label=f"{vd:g} V")
    axs[2,2].plot([r["vgs_V"] for r in curve],[r["gm_S"] for r in curve],label=f"{vd:g} V")
for ax, title, xlab, ylab in [(axs[0,2],"DFO 4x50 | output", "$V_{DS}$ coordinate (V)","$I_D$ (A)"),(axs[1,2],"DFO 4x50 | transfer", "$V_{GS}$ coordinate (V)","$I_D$ (A)"),(axs[2,2],"DFO 4x50 | transconductance", "$V_{GS}$ coordinate (V)","$g_m$ (S)")]:
    ax.set(title=title,xlabel=xlab,ylabel=ylab);ax.legend(fontsize=7,frameon=False,ncol=2)
finish(fig,"overview.png","GaN HEMT data preview | three separate nominal device groups", "Curves use source values. Red open circles indicate suspected compliance; column axes are independent. No parameter fitting performed.")

for fid, rows in by_file.items():
    if not fid.startswith("RDG"): continue
    fig, ax=plt.subplots(figsize=(7.5,4.7))
    if rows[0]["measurement_type"]=="cv": cv_plot(ax,rows)
    else: line_plot(ax,rows,rows[0]["measurement_type"])
    r=rows[0]
    title=f"{r['device_id']} | {r['capacitance_type'] or r['measurement_type']} | {r['mode']}"
    finish(fig, "source_curves/"+fid+".png",title,"Original values; acquisition order retained. Source file ID: "+fid)

gap_md = ["# 数据缺口与复核清单", "", "本清单根据已下载原始文件生成。限流和偏置偏离标记为启发式检查，不代表官方 QA 结论。", "", "| 编号 | 优先级 | 范围 | 缺口 | 证据 | 影响 | 下一步 |", "|---|---|---|---|---|---|---|"]
for r in gaps: gap_md.append("|"+"|".join(str(r[k]).replace("|","/") for k in ["gap_id","priority","scope","gap","evidence","modeling_effect","next_action"])+"|")
(OUT/"data_gaps.md").write_text("\n".join(gap_md)+"\n",encoding="utf-8")
summary = {"total_records":len(measurements),"primary_source_files":len(conditions),"source_csv_inventory":len(inventory),"by_device":stats,"total_curves":len(curve_stats),"gap_items":len(gaps),"compliance_suspected_points":compliance_total,"bias_deviation_points":bias_total,"negative_gm_points":negative_gm,"original_dfo_split":dict(Counter(r["train_test_split"] for r in dfo_rows)),"read_only_source_hashes":source_hashes_before,"checks":{"point_ids_unique":True,"all_numeric_values_finite":True,"all_RGD_mapped_measurements_equal_original":True,"no_source_points_deleted":True,"unknown_temperatures_not_filled":True,"original_dfo_split_preserved":True,"pulse_settings_not_assigned_to_continuous_data":True,"raw_source_files_unchanged":all(digest(Path(p))==h for p,h in source_hashes_before.items())}}
write_json(OUT/"metadata/validation.json",summary)
readme = f"""# GaN HEMT 统一数据与曲线预览

已整理 **{len(measurements):,} 条原始观测记录**，来源为 17 个基础 CSV，分为 TLN2、GS65030 和 DFO_4x50 三个名义器件组。源数据未修改，未删点、平滑、插值或做宽度归一化。

## 文件

- `data/unified_measurements.csv`：统一主表，UTF-8 BOM 编码，一行对应一个原始观测点。
- `data/by_device/`：三个器件组分别保存的同结构 CSV。
- `normalized_measurements.xlsx`：用于浏览的同一份统一数据及目录/缺口。
- `curve_preview.html`：可离线打开的曲线与数据缺口预览。
- `previews/overview.png`：三种器件的总览；另有三张详细图和 16 张来源文件图。
- `data_gaps.md` / `data_gaps.csv`：{len(gaps)} 项缺口与复核任务。
- `field_dictionary.csv` / `metadata/schema.json`：字段、单位、缺失值与变换规则。
- `metadata/conditions.json`：完整仪器头、原始列名、时序和模型上下文。
- `source_inventory.csv`：全部 41 个源 CSV 的纳入/排除理由；25 个 DFO 文件不计为 25 份独立数据。
- `curve_summary.csv`：按扫描维度分组的曲线索引。
- `raw_selected/`：17 个基础来源文件的逐字节副本，文件名使用来源哈希 ID。
- `metadata/validation.json`：行数、映射、划分和源文件未改动的检查结果。

## 数据量

| 器件组 | 观测点 | 基础文件 | 内容 |
|---|---:|---:|---|
| TLN2 | 2,121 | 8 | 连续/脉冲 I-V、反向 I-V、Ciss/Coss/Crss |
| GS65030 | 1,717 | 8 | 连续/脉冲 I-V、反向 I-V、Ciss/Coss/Crss |
| DFO_4x50 | 6,030 | 1 | 原作者 Id/gm 偏置网格，train=4,824，test=1,206 |

## 读取约定

`vds_V/vgs_V/id_A/ig_A/gm_S/capacitance_F` 以 SI 单位表达。RDG 的实际记录电压与从扫描头重建的 `vds_set_V/vgs_set_V` 分开保存。DFO 的 vd/vg 是作者提供的偏置坐标，不额外宣称它们是独立监测端电压。

所有缺失数值使用空单元格，JSON 中用 null，不能按 0 读取。当前 `temperature_K` 全为空；DFO MDL 中 TEMP=25 C 仅作为 `temperature_context_K=298.15`，不代替测量温度。连续模式 CSV 即使保留有 Pulse.Period 头字段，也不会据此填充脉冲条件。

`curve_id` 对 RDG 使用原始 Dimension1/Dimension2 分组，而不按带噪声的实际 Vgs 四舍五入。原始记录号保存在 `source_row`；配合 `source_file_id` 可定位 `raw_selected`，配合 `source_file` 可定位原下载数据包。源文件的 absIds/absIgs 为冗余派生显示列，保存在原始副本中；主表保留带符号 Id/Ig。

器件组用于区分来源和名义类型。文件名括号号与原始记录迭代号对应，不据此推断独立物理样品。Ciss/Coss/Crss 保持原类型，不在未确认端接条件时转换为本征电容。

原始测试协议已复制到 `raw_selected/Characterization_protocol.pdf`。第 6.2 节说明高电流回路压降，第 9 节及图 4 给出电容接线，第 10 节表 19 说明文件名括号中的测试编号。GS65030 三个 C-V 文件的 Step/Stop 元数据存在小幅矛盾，其 `vds_set_V` 留空并标记，不任意选择重建网格。

## 需要特别复核的发现

- {compliance_total} 个点同时接近漏极电流限值并出现电压偏离，标记为 `compliance_suspected=1`。{bias_total} 个点有实际/设定电压偏离，单独标记，不能直接判为限流。
- 启发式阈值：接近限流定义为 |Id| >= 0.99 × 原限流设置；电压偏离为差值 > max(0.02 V, 设定值绝对值的 1%)。这些不是仪器状态码或比赛 QA 阈值，未据此自动删除记录。
- DFO 有 {negative_gm} 个负 gm 值，原样保留。反向导通的负电流、负电压也保留。
- C-V 频率均为 100 kHz，ACLevel 分别为 TLN2 0.1 V、GS65030 0.03 V；脉宽均为 150 us，周期分别为 20 ms 和 50 ms。
- TLN2 反向记录的文件名与内部日期不一致，已保留两种证据。
- 原始 DFO 模型版本 101.2 与已下载参考包 101.0.0 不同，正式提参前需核对比赛版本。

## 来源与许可

1. [Recherche Data Gouv: DOI 10.57745/IZ6LY2](https://doi.org/10.57745/IZ6LY2)，V6.0，Etalab Open License 2.0，Salim Dahmani / Xuyang Lu。来源公开元数据与许可随 `metadata/source_provenance.json` 保存。
2. [Rafael Perez Martinez 等论文配套仓库](https://github.com/rafapm/dfo_parameter_extraction)，固定提交 a8d945a1d2f70c27998be7d0071cd6602bca02b5，MIT 许可。论文 DOI：[10.1109/ACCESS.2024.3453198](https://doi.org/10.1109/ACCESS.2024.3453198)。仓库 LICENSE 已保留。

本轮只整理数据和生成预览，未开展参数拟合或运行建模 Agent。当前数据不足以完整验证 S 参数、多温度行为及陷阱/热时间常数。
"""
(OUT/"README.md").write_text(readme,encoding="utf-8")
provenance=json.loads((RAW/"download_manifest.json").read_text(encoding="utf-8"))
write_json(OUT/"metadata/source_provenance.json",provenance)
shutil.copyfile(RAW/"02_ASM_HEMT_DFO_Measurements/extracted/LICENSE",OUT/"metadata/DFO_LICENSE.txt")
shutil.copyfile(RAW/"01_Real_IV_CV_TLN2_GS65030/extracted/Characterization_flowchart.pdf",OUT/"raw_selected/Characterization_protocol.pdf")
write_json(OUT/"metadata/RDG_source_metadata.json",json.loads((RAW/"01_Real_IV_CV_TLN2_GS65030/source_metadata.json").read_text(encoding="utf-8")))

def image_embed(filename):
    return '<img alt="'+html.escape(filename)+'" src="data:image/png;base64,'+base64.b64encode((OUT/"previews"/filename).read_bytes()).decode("ascii")+'">'

table_rows="".join(f"<tr><td>{d}</td><td>{s['records']:,}</td><td>{s['files']}</td><td>{s['compliance_suspected']}</td><td>{s['bias_deviation']}</td></tr>" for d,s in stats.items())
gap_rows="".join("<tr>"+"".join("<td>"+html.escape(str(r[k]))+"</td>" for k in ["gap_id","priority","scope","gap","evidence","next_action"])+"</tr>" for r in gaps)
report_html=f"""<!DOCTYPE html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>GaN HEMT 数据与曲线预览</title><style>body{{font-family:Arial,'Microsoft YaHei',sans-serif;max-width:1320px;margin:40px auto;padding:0 22px;color:#203047;line-height:1.65;background:#fafbfc}}h1{{font-size:30px}}h2{{margin-top:38px}}img{{width:100%;height:auto;background:white;border:1px solid #dce1e8;border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:14px;background:white}}th,td{{text-align:left;padding:10px 12px;border-bottom:1px solid #dce1e8;vertical-align:top}}th{{background:#203047;color:white}}.note{{border-left:4px solid #d59b30;background:#fff8e8;padding:14px 18px}}.links a{{margin-right:20px}}code{{background:#edf0f4;padding:2px 5px}}a{{color:#1e6091}}</style><h1>GaN HEMT 数据与曲线预览</h1><p>9,868 条原始观测记录，17 个基础文件，3 个独立保留的名义器件组。源文件未改动，未删点或平滑。</p><p class="links"><a href="data/unified_measurements.csv">统一 CSV</a><a href="normalized_measurements.xlsx">Excel 浏览版</a><a href="data_gaps.csv">缺口清单</a><a href="README.md">字段与处理说明</a></p><table><thead><tr><th>器件组</th><th>观测点</th><th>基础文件</th><th>疑似限流点</th><th>偏置偏离点</th></tr></thead><tbody>{table_rows}</tbody></table><p class="note">“疑似限流”要求接近电流限值与电压偏离同时出现，只用于复核。实际测量电压与标称设定值已分开存储。温度缺失未补零，DFO 模型的 25°C 仅存作上下文。</p><h2>曲线总览</h2><p>各器件坐标轴独立。红色空心圈表示疑似限流；曲线采用原始数值。</p>{image_embed('overview.png')}<h2>TLN2 详细曲线</h2>{image_embed('TLN2_curves.png')}<h2>GS65030 详细曲线</h2>{image_embed('GS65030_curves.png')}<h2>DFO 4x50 详细曲线</h2>{image_embed('DFO_4x50_curves.png')}<h2>数据缺口与复核任务</h2><table><thead><tr><th>ID</th><th>优先级</th><th>范围</th><th>缺口</th><th>证据</th><th>下一步</th></tr></thead><tbody>{gap_rows}</tbody></table><p>原始数据来源：<a href="https://doi.org/10.57745/IZ6LY2">Recherche Data Gouv V6</a>、<a href="https://github.com/rafapm/dfo_parameter_extraction">论文作者仓库</a>。完整来源、许可与字段证据见数据包。图为数据预览，尚未进行参数拟合。</p></html>"""
(OUT/"curve_preview.html").write_text(report_html,encoding="utf-8")
print(json.dumps({"records":len(measurements),"devices":stats,"gaps":len(gaps),"previews":len(list((OUT/"previews").rglob("*.png"))),"checks":summary["checks"]},ensure_ascii=False))
