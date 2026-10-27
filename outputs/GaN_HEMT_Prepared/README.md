# GaN HEMT 统一数据与曲线预览

已整理 **9,868 条原始观测记录**，来源为 17 个基础 CSV，分为 TLN2、GS65030 和 DFO_4x50 三个名义器件组。源数据未修改，未删点、平滑、插值或做宽度归一化。

## 文件

- `data/unified_measurements.csv`：统一主表，UTF-8 BOM 编码，一行对应一个原始观测点。
- `data/by_device/`：三个器件组分别保存的同结构 CSV。
- `curve_preview.html`：可离线打开的曲线与数据缺口预览。
- `previews/overview.png`：三种器件的总览；另有三张详细图和 16 张来源文件图。
- `data_gaps.md` / `data_gaps.csv`：14 项缺口与复核任务。
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

- 120 个点同时接近漏极电流限值并出现电压偏离，标记为 `compliance_suspected=1`。1020 个点有实际/设定电压偏离，单独标记，不能直接判为限流。
- 启发式阈值：接近限流定义为 |Id| >= 0.99 × 原限流设置；电压偏离为差值 > max(0.02 V, 设定值绝对值的 1%)。这些不是仪器状态码或比赛 QA 阈值，未据此自动删除记录。
- DFO 有 358 个负 gm 值，原样保留。反向导通的负电流、负电压也保留。
- C-V 频率均为 100 kHz，ACLevel 分别为 TLN2 0.1 V、GS65030 0.03 V；脉宽均为 150 us，周期分别为 20 ms 和 50 ms。
- TLN2 反向记录的文件名与内部日期不一致，已保留两种证据。
- 原始 DFO 模型版本 101.2 与已下载参考包 101.0.0 不同，正式提参前需核对比赛版本。

## 来源与许可

1. [Recherche Data Gouv: DOI 10.57745/IZ6LY2](https://doi.org/10.57745/IZ6LY2)，V6.0，Etalab Open License 2.0，Salim Dahmani / Xuyang Lu。来源公开元数据与许可随 `metadata/source_provenance.json` 保存。
2. [Rafael Perez Martinez 等论文配套仓库](https://github.com/rafapm/dfo_parameter_extraction)，固定提交 a8d945a1d2f70c27998be7d0071cd6602bca02b5，MIT 许可。论文 DOI：[10.1109/ACCESS.2024.3453198](https://doi.org/10.1109/ACCESS.2024.3453198)。仓库 LICENSE 已保留。

本轮只整理数据和生成预览，未开展参数拟合或运行建模 Agent。当前数据不足以完整验证 S 参数、多温度行为及陷阱/热时间常数。

## 筛选时的注意事项

按 measurement_type 及该任务所需的观测列筛选，不要对全表直接删除所有含空值的行：C-V 没有逐点 Vgs，温度也未提供。quality_flags 非空不等于记录报废。布尔标记 0 表示当前检查未触发；当所需限流设置或设定电压缺失时，也不能把 0 解释为仪器或物理 QA 已通过。

团队交接版以 CSV 为规范数据，Excel 浏览副本未提交。本次导出哈希见 `../../reports/SHA256SUMS.json`；含本机路径的元数据已经脱敏。

`raw_selected/DFO_model_context.mdl` 中上游作者的本机用户目录前缀也已脱敏；17 个基础测量 CSV 保持字节一致。原始上下文文件仍可从固定上游提交获取。
