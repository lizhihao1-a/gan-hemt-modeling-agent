> 团队交接说明：历史数值报告已归档到 `../../reports/baseline/`。本目录保留源码、数据与模型卡，新运行从 bootstrap / fresh（或 reproduce）开始；历史结果目录和原生二进制未放回项目中。当前官方集成状态以 [STATUS.md](../../docs/STATUS.md) 为准。

# DFO_4x50 ASM-HEMT 直流拟合基线

入口：双击 `curve_preview.html` 查看曲线，阅读 `validation_report.md` 查看误差、参数与数据局限。

本项目用作者原始 ASM-HEMT 101.4.0 Verilog-A，经 OpenVAF 编译后在 ngspice 47 中计算；不是神经网络代理或经验公式替代模型。原始 4824/1206 训练/测试标签保留，模型卡及逐点预测已输出。当前只覆盖单器件、单温度上下文的直流数据。

## 结果文件

- `models/fitted_model.lib`：ngspice 模型卡；`fitted_parameters.json`：参数 JSON。
- `models/asmhemt.va`、`asmhemt.osdi`：作者原始模型及 Windows x64 编译件。
- `results/test_evaluation.json`：拟合前后误差与安全 gm 子集误差。
- `results/verification.json`：独立 ngspice 命令行读取模型卡的数值对齐结果及差分模板隔离检查。
- `results/train_predictions.csv`、`test_predictions.csv`：按原始点 ID 保留实测和拟合前后结果。
- `results/local_qa.json`、`parameter_review.csv`：本地物理与边界检查。
- `results/fit_protocol.json`、`freeze.json`、`optimization_trace.jsonl`、`training_candidates.json`：预设协议、冻结证据与优化过程。
- `audit/protocol_1/`：发现源数据 gm 跨集合依赖前的旧运行，供追溯；最终模型以项目根目录 results 为准。
- `provenance.json`、`checksums.sha256`：来源、版本与校验值。

## 数据依赖说明

源 gm 恰好是完整 Id 网格的数值导数，随机按行切分后，训练 gm 可能间接包含测试 Id。最终协议 2 会排除差分模板不完全处于当前拟合子集中的 gm；内部验证也单独检查模板。归一化只使用安全训练目标。测试反馈不进入本轮拟合和候选选择。

旧协议已查看过同一留出集的指标，因此本报告保留审计历史，不将最终数字称为从未查看过的新盲测。原始测试 gm 全集指标仅作曲线描述，更严格的同集合模板子集单独报告。需要新增器件/整条留出曲线才能更可靠地检验泛化。

## 运行

Windows x64 + Python 3.12。当前工作区已有依赖；可用以下 Python 路径：

```powershell
$pythonExe = 'python'
.\run.ps1 -Action verify -Python $pythonExe
.\run.ps1 -Action report -Python $pythonExe
```

迁移到其他目录或电脑，先准备本地依赖：

```powershell
.\run.ps1 -Action bootstrap -Python python
```

bootstrap 从固定官方 URL 下载 ngspice/OpenVAF，验证 SHA-256，放在本项目 `runtime/` 内，重新编译源码，并把固定版本 Python 包安装到 `.deps/`。不安装系统服务或修改系统 PATH。需要网络；系统若限制 PowerShell 脚本执行，应遵循本机策略，不建议修改全局策略。

固定协议复跑：

```powershell
.\run.ps1 -Action reproduce -Python python
```

每次会在 `runs/时间戳/` 建立独立目录，保留本次冻结结果；重新执行训练、一次该运行的留出评估、模型卡验证和报告生成。原始测试集已用于本项目评估，重复运行同一测试集不等于获得新的独立测试证据。

本机运行依赖路径回退至工作区 `work/dfo_deps/`；迁移后使用 bootstrap 安装的 `.deps/`。Windows 版 tar 可能对 7z 中的空目录条目给出警告；bootstrap 会检查实际所需二进制是否齐全。

## 参赛衔接

这是可复跑的本地 DC 参数提取基线。尚未接入 Primarius / MeQLab MCP、国内 LLM 或官方评分器；官方接口、ASM 版本和模型卡 schema 仍需获取。当前不含 C–V、射频、动态陷阱、跨温度或跨器件验证。

模型源码原始声明完整保留；作者仓库 MIT 文本见 `THIRD_PARTY_LICENSE.txt`，ngspice 声明见 `runtime/ngspice_COPYING.txt`。便携 DLL 随官方 ngspice Windows 发行包提供，来源及下载校验见 `provenance.json`。
