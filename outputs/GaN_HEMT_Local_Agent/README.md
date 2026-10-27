> 团队交接说明：历史数值报告已归档到 `../../reports/local_agent/`。本目录保留源码、数据与模型卡，新运行从 bootstrap / fresh（或 reproduce）开始；历史结果目录和原生二进制未放回项目中。当前官方集成状态以 [STATUS.md](../../docs/STATUS.md) 为准。

# GaN HEMT 本地建模 Agent

这是从数据读取到模型导出的可运行规则状态机工程。它使用真实 ASM-HEMT 101.4.0 / OpenVAF 编译件 / ngspice 47，包含参数敏感性与耦合诊断、连续栅压曲线分组验证、候选拟合、误差反馈、物理检查、必要的参数细化、冻结导出、失败恢复与审计日志。

当前规划器是确定性规则，未接入大模型。官方 MCP 和国内 LLM 实际调用均为 0；待补资料见 `integration_requirements.md`，不能将本地仿真次数作为正式 MCP 次数。

## 查看结果

- `results/report/overview.html`：自包含曲线与参数诊断预览。
- `results/report/validation_report.md`：诊断、曲线分组验证、最终模型和局限说明。
- `results/acceptance.json`、`acceptance.md`：运行验收与故障恢复测试。
- `results/diagnostics/`：局部 Jacobian、奇异值、参数敏感性、耦合和边界内侧扰动。
- `results/curve_validation/curve_cv.json`、`curve_oof_predictions.csv`：三组曲线验证与逐点结果。
- `results/agent/`：候选、规则决策、重拟合、模型冻结记录和预测。
- `models/fitted_model.lib`、`fitted_parameters.json`：本轮导出的模型卡与参数。
- `results/events.jsonl`：每次真实本地仿真调用、错误、重试、状态与决策。
- `results/run_state.json`：源码/输入校验、阶段检查点和产物校验。

## 当前数据与隔离规则

保留作者原始 4824 个训练点和 1206 个测试点；模型温度 25 °C 是上下文设置，测量温度未获独立确认。源 gm 是完整 Id 网格的数值导数，目标函数只采用差分所需 Id 都位于当前拟合子集的 gm。内部验证也应用相同隔离规则，归一化尺度仅从安全训练目标计算。

三折分组验证按 Vgs 连续区间切分，每个留出曲线组在对应拟合集中完全不存在。每一折从公开范围中点重新拟合，不用旧最佳参数暖启动；可用点仅限原作者训练域，因此这是已知数据上的曲线分组交叉验证，不是新的盲测。

规则 Agent 另用预先指定的 Vgs 组作内部验证：先拟合 16 个核心参数，依据固定误差/QA 阈值决定是否细化全部 23 个参数。候选选定后只用完整训练集重拟合，冻结后才读取作者测试目标作回归检查。旧基线参数只用于诊断，不用于新 Agent 或曲线分组拟合初始化。公开范围本身含器件先验。

原始测试集之前已经查看，最终指标不能当作从未查看过的独立盲测。参数局部秩、边界命中和曲线组误差用于揭示局限；本地 QA 也不是官方 QA_pass_rate。

## 运行

Windows x64、Python 3.12。当前工作区已有所需依赖，可执行：

```powershell
$pythonExe = 'python'
.\run.ps1 -Action status -Python $pythonExe
.\run.ps1 -Action resume -Python $pythonExe
.\run.ps1 -Action acceptance -Python $pythonExe
```

已完成的运行使用 resume 只验证哈希并跳过已完成阶段，不重新拟合。源码、输入或冻结产物变化会拒绝恢复。

新目录从头复跑：

```powershell
.\run.ps1 -Action fresh -Python $pythonExe
```

该命令在 `runs/时间戳/` 建立独立副本，不覆盖当前结果。标准演示先运行诊断与分组验证、保存检查点，再执行故障恢复测试并恢复后续拟合与导出，最后验收。直接 CLI 也可运行：

```powershell
python agent.py run --stop-after curve_validate
python tests/acceptance.py backend
python agent.py run --resume
python tests/acceptance.py final
```

项目迁移后，使用 `run.ps1 -Action bootstrap` 从固定官方 URL 准备本项目内的工具和固定 Python 依赖。bootstrap 验证下载 SHA-256，编译模型，不修改系统 PATH。当前目录优先使用 `.deps/`，本工作区还可回退到 `work/dfo_deps/`。

## 超时与恢复边界

- 单独进程运行 ngspice；单次仿真默认 10 秒超时，最多重试一次。超时/崩溃会终止并重新建立仿真进程，日志保留失败与重试。
- 参数范围和有限值在调用原生仿真前检查；每项优化另有限制：真实仿真次数（含失败与重试）、时间与 SciPy 函数评估次数。作业时间预算在评估之间检查，单次原生调用另受独立硬超时约束；没有声称操作系统级整作业硬截止。
- 检查点按已完成阶段/优化作业保存；未完成的优化作业从固定输入重新运行，不是逐迭代无损恢复。
- 输入/源码和已完成产物校验不匹配时停止，运行锁阻止同一目录并发执行两个控制器。
- 故障注入测试单独记录，未混入正式流水线仿真统计。

原有 `DFO_DC_Baseline` 冻结模型不修改，并在验收时与此前 SHA-256 快照比较。版权与来源见 `THIRD_PARTY_LICENSE.txt`、`runtime/ngspice_COPYING.txt`、`provenance.json`。
