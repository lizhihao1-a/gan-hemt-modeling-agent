# GaN HEMT 紧凑模型建模 Agent

团队协作交接版，更新于 **2026-10-27**。入口是本文件和 [当前进展](docs/STATUS.md)。

已完成公开数据整理、真实本地 DC 拟合、规则 Agent、PMMS 连接及官方 demo 排查。当前主要阻碍是 Windows Nano 引擎返回状态 127，尚未获得有效的官方 GaN 仿真曲线。

| 内容 | 已完成结果 | 入口 |
|---|---|---|
| 数据 | 9,868 条记录，3 个名义器件组，字段/来源/缺口齐全 | [数据说明](outputs/GaN_HEMT_Prepared/README.md)、[缺口](outputs/GaN_HEMT_Prepared/data_gaps.md) |
| DC 基线 | ASM-HEMT 101.4 + ngspice，测试 Id RMSE 0.8359 mA | [报告](reports/baseline/curve_preview.html) |
| 本地 Agent | 规则规划、敏感性/耦合分析、曲线分组验证、恢复与审计；测试 Id RMSE 0.9265 mA | [总览](reports/local_agent/report/overview.html)、[验收](reports/local_agent/acceptance.md) |
| 官方接口 | PMMS 已连通；参数读写、模型卡导出、工程保存绕行通过 | [部署](docs/MEQLAB_SETUP.md) |
| 官方 Nano | GaN 电流有限值 0/5,160；最小 MOS 对照同样失败 | [诊断与下一步](docs/NANO_DIAGNOSIS.md) |

以上误差来自已查看过的公开测试集，是回归结果。这里的本地 Agent 尚未接入大模型；ngspice 调用不计为官方 MCP 调用。官方建模、国内 LLM、两器件完整评测与长时间稳定运行仍需完成。

## 队友先做这三步

1. 克隆仓库，阅读 [当前进展和待办](docs/STATUS.md) 与 [协作约定](CONTRIBUTING.md)。
2. 执行下面的离线检查，确认数据、冻结模型与记录的误差一致。
3. 根据 [分工建议](docs/ROADMAP.md) 领取任务；排查 Nano 的队友再准备比赛软件和各自的授权环境。

```powershell
git clone https://github.com/lizhihao1-a/gan-hemt-modeling-agent.git
cd gan-hemt-modeling-agent
python scripts/verify_repository.py
```

离线检查仅依赖 Python 3.10+，不需要 MeQLab、许可证或仿真器。HTML 文件下载后可以直接离线打开，GitHub 文件页本身不渲染这些交互预览。

## 复跑本地建模

完整原生仿真环境以 **Windows x64 + Python 3.12** 为已验证组合。以下 bootstrap 会下载固定哈希的 ngspice/OpenVAF/模型源文件和 Python 依赖；软件二进制不随仓库分发。

```powershell
.\outputs\GaN_HEMT_Local_Agent\run.ps1 -Action bootstrap -Python python
.\outputs\GaN_HEMT_Local_Agent\run.ps1 -Action fresh -Python python
```

`fresh` 在独立 `runs/` 目录生成新结果，完整运行需要数千次真实仿真。现有交接报告位于 `reports/`，新运行使用 `outputs/` 下的项目目录。历史检查点保留原始输入哈希，仅供追溯；迁移后从 `fresh` 开始，不把历史报告复制回新结果目录执行 resume。

DC 基线可分别执行其 `run.ps1 -Action bootstrap` 和 `-Action reproduce`。统一数据可直接读取；需要重建时见 [数据来源与重建](docs/DATA_SOURCES.md)。官方软件接入见 [MeQLab 部署](docs/MEQLAB_SETUP.md)。

## 目录

```text
outputs/GaN_HEMT_Prepared/               统一 CSV、原始选定 CSV、字段、缺口和预览
outputs/DFO_DC_Baseline/                 基线源码、训练/测试划分、模型卡
outputs/GaN_HEMT_Local_Agent/            本地规则 Agent 源码与验收工具
outputs/MeQLab_Local_Integration/        PMMS 客户端、会话队列和 MOS 对照
outputs/MeQLab_Official_Demo_Integration/ 官方 demo 排查脚本与可选诊断源代码
reports/                               已完成结果的交接快照
work/                                  数据下载、转换和核验脚本
scripts/                               离线仓库检查、模型获取和快照校验
docs/                                  部署、状态、下一步和导出追溯
licenses/                              第三方声明
```

仓库不包含 MeQLab/PMMS 安装包、许可证、授权服务器配置、官方私有 demo 压缩包或原始程序日志。第三方内容的来源与权限见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
