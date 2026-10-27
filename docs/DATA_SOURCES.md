# 数据来源与重建

## 已固定的来源

| 来源 | 用途 | 固定标识 / 权限说明 |
|---|---|---|
| [Recherche Data Gouv 数据集](https://doi.org/10.57745/IZ6LY2) | TLN2、GS65030 连续/脉冲/反向 I-V 与 C-V | v6.0，Etalab 2.0；保留署名、来源及日期 |
| [rafapm/dfo_parameter_extraction](https://github.com/rafapm/dfo_parameter_extraction) | DFO_4x50，原始 Id/gm 网格与划分 | commit `a8d945a1d2f70c27998be7d0071cd6602bca02b5`；仓库 MIT 声明见 `licenses/DFO_MIT.txt` |
| CMC ASM-HEMT 101.0.0 参考包 | 核对官方 demo 模型版本 | 只保留来源记录/声明；源模型和手册不随仓库分发 |

完整 URL、校验和、纳入/排除理由在 `docs/sources/download_manifest.json` 和 `outputs/GaN_HEMT_Prepared/source_inventory.csv`。RDG 的作者/原始元数据在 `metadata/RDG_source_metadata.json`。发布数据以原 DOI 和原作者署名为准。

`outputs/GaN_HEMT_Prepared/data/unified_measurements.csv` 是规范主表；各器件 CSV 是同结构子集。`raw_selected/` 保留 17 个基础 CSV 与公开测试协议，可用来源哈希核对。导出的 Excel 浏览副本未纳入仓库，以免与主表重复维护。

保持空值、SI 单位、原始 train/test 和质量标记，不直接合并三个名义器件做一次拟合。DFO gm 为网格差分，拟合和曲线验证只使用差分依赖均在当前子集内的点。

## 从来源重新获取

当前快照可直接使用。需要重新验证下载/转换时，在新克隆目录中执行，下载和转换会写入 `outputs/` 对应目录：

```powershell
python -m pip install -r requirements.txt
python work/download_gan_datasets.py
python work/verify_gan_data.py
python work/prepare_gan_data.py
python work/finalize_gan_prepared.py
```

原始大压缩包和完整参考资料会被 `.gitignore` 排除。首次下载依赖来源站点可用性；不要因当前链接提供新版而覆盖固定版本或更改原划分。快照哈希变化时明确创建新数据版本并更新说明。

ASM-HEMT 101.4.0 模型源文件在 bootstrap 时从固定提交获取，SHA-256 必须为 `189002cdd52996994cb4dcf7171050374237832f61dbfa1a3a43cc4439c94edc`；源文件版权头予以保留，不将它归入本项目自有版权。
