# Nano 阻碍与排查边界

当前结论：问题位于 Nano 公共启动/执行链路，尚未确定唯一根因。

| 检查 | 观察 |
|---|---|
| 官方 GaN demo | 5,160 个电流全部 NaN，改变 voff 后仍无有限值 |
| 最小 MOS Nano / Internal | Nano 0/33 有限；Internal 33/33 有限，20 点非零，最大绝对电流约 0.0659427 A |
| Native 调用 | `pei_newSim` 返回句柄 1，`pei_get_status` 返回 127 |
| 包内状态定义 | 126 成功结束；127 工作进程启动/重启 prosim 失败；128 崩溃 |
| 32 位原生库加载 | 原始 cpei.dll 及关键导出可加载，不能简单认定缺 DLL |
| 并行授权 | PARALLEL_SPICE 检出成功；转发授权参数存在，未记录其内容 |
| 保存 | 原 API 失败；模板 `save(true)` 两次完成参数保存重开 |

已尝试 pnano / 文档 ppei、启用并行工作数、明确子进程运行库 PATH、不同读取方式、短安装路径和隔离用户目录，均未恢复有限输出。关键文件与原包校验一致。不要继续把 NaN 当作可优化误差输入。

早期把缺少 `MS_MEQLAB_SPICE` 视为重点嫌疑；重读官方 Q&A 后已修正。添加 Nano 模型源会触发单路许可检查，使用预配置工程能避免该提示，但 Nano 状态 127 仍在，因此不能据此宣称许可证是确定根因。

下一位负责环境的队友应在自己的完整 Windows 包上先运行最小 MOS 对照，记录版本、架构、并行许可状态、有限点数和退出/状态码。若其环境有正例，再逐项对比安装包、工作目录、用户目录及原生工作进程启动条件。恢复 33 个有限值且参数扰动产生非零差异后，再验证官方 GaN demo，最后开展优化。

`trace_agent/src` 仅包含本项目编写的诊断源代码，不含厂商类文件。启用后会给方法增加运行时日志，并可将 IEPS 标准输出转到专用文件；它不改变仿真参数、状态码或许可校验。插桩可能改变时序，仅用于诊断，最终正例应关闭插桩再复核。

JDK 17 编译示例（在 `outputs/MeQLab_Official_Demo_Integration/trace_agent` 内执行）：

```powershell
New-Item -ItemType Directory -Force classes | Out-Null
javac --add-exports java.base/jdk.internal.org.objectweb.asm=ALL-UNNAMED -d classes src/local/nano/Agent.java src/local/nano/Trace.java
jar cfm nano_trace.jar manifest.mf -C classes .
```

官方 Q&A：[比赛问题文档](https://docs.qq.com/doc/DQmFHdXdsckR6VXF5)。记录以 2026-10-27 核对的内容为依据；公开问答并未让本地替代仿真自动满足比赛验收。
