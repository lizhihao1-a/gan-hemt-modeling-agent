# 官方 ASM-HEMT demo 集成

先阅读 [当前进展](../../docs/STATUS.md)、[部署](../../docs/MEQLAB_SETUP.md) 和 [Nano 排查](../../docs/NANO_DIAGNOSIS.md)。填写 `config.demo.local.json`，将官方 demo 放入独立 pristine 目录。每次运行使用新名称。

- `probe_demo.py`：复制工作工程、修正本地模型路径、参数扰动和数值导出。
- `diagnose_control.py`：Nano / Internal 最小 MOS 对照，模板保存与重开参数恢复。
- `diagnose_local.py`：通过模板记录本地环境与执行状态。
- `diagnose_nano_transport.py`：隔离临时目录与可选原生调用插桩；`trace_agent/src` 是额外诊断源代码，默认无需编译。

这些脚本保留排查能力，部分实验预期失败。实际成功标准是有限电流值和参数响应，不能以工具返回成功替代。官方软件、demo、许可证和原始日志不包含在仓库中。
