# 已解密的华为鸿蒙备份

本适配器处理 `.info.json`（`BackupFileHeaderInfo`、`BackupFileModuleInfo`）与 `files/BASIC|SYSTEM|APPLICATION` 组成的备份目录。支持同一清单中的已解密 TAR 和独立大文件，优先读取 `manage.jsonx`、`part.N.tarx`、哈希文件名加 `x` 的副本，也接受内容、清单大小校验通过的无 `x` 文件。它不实现备份外层解密、设备提取或手机仿真；外层已解密不代表应用内部数据库或字段全部明文。

## 使用原有任务入口

在原任务创建窗口选择“华为鸿蒙备份”，填写已解密目录。选择“Android 目录”时也会自动识别此布局。后端仍使用 `/api/tasks`，在同一任务中运行逻辑索引、过滤、分类、文件读取、手机解析、时间线、已有智能分析与摄取/报告尾段。没有独立的鸿蒙导入服务或任务系统。

```bash
./build/forensic_analyzer /path/to/decrypted-backup \
  --android-source harmony-backup --no-ai --db-dir /path/to/results
```

Windows 上运行 WSL 后端时使用后端可见的路径，例如 `/mnt/e/第三届盘古石杯决赛_解密文件/技术人员手机`。输出目录必须与检材分离。CLI 结果保持原 `_raw.db`、`_files.db`、`_events.db` 结构；HTTP 手机结果放在同一任务的 `android.db`，通过 `metadata.android_db` 绑定，`output_files_db` 继续指向通用文件库。

## 数据与来源

- 使用 libarchive 读取 GNU 长文件名及鸿蒙目录头；按应用包名、`appIndex` 和原始路径隔离。非 UTF-8 名称按字节编码保存，不把同名应用数据合并。
- 统一解析清单中的 TAR 成员和独立文件，配齐 SQLite 主库、WAL、SHM、journal 后只读查询临时副本。
- 备份清单及数据容器记录 SHA-256；分析末尾再次验证输入。逐条业务记录保留源库、表、主键、主库/WAL 哈希及解析器版本。没有做 WAL 帧定位或物理删除恢复。
- `harmony_source_files` 是来源定位索引。通用 `files.inode` 在此来源中承载稳定的**逻辑文件编号**，没有物理 inode/分区含义。文件名中的特殊字节使用可逆编码，来源记录保留原路径。
- `mobile_backup_manifest` 保存设备和备份信息；`backup_version` 是备份组件版本，不能直接当作手机系统版本。`installed_apps` 在此模式中表示清单列出的备份模块，不代表全部已安装应用。
- `mobile_artifacts` 保存日历、录音、通话录音、媒体元数据、华为备忘录/待办、思源内容块及可读 QQ 联系人、群资料和最近会话。FTS 搜索表、备份副本和从库不重复计入业务记录。
- `related_path` 关联备份中的文件；仅使用同应用内的精确路径或已知恢复目录映射。云媒体路径映射同时校验大小，不做跨应用文件名猜测。未解析出关联文件不等于设备上不存在该文件。
- `android_source_coverage` 和 `app_db_inventory` 区分可读、空表、缺失、未支持及错误。无法统计的表行数为 NULL，页面显示“未知”。缺少 FTS5 或自定义排序规则时，正常业务表继续解析。

## 下游接入与限制

原文件页面的浏览/提取使用冻结的来源索引。已验证的 epoch 时间转换为秒进入现有时间线；思源的本地时间字符串缺少时区时保留原值，不虚构 UTC 时间。

原手机页面显示鸿蒙概览、应用和数据库清单，以及分页业务记录。记录可沿用现有冻结、调查研判、证据采纳和报告引用链。智能分析沿用原模型配置和数量限制；自动报告尾段可采纳已分析的鸿蒙记录，并保留已有人工判定。图谱沿用原文件/事件摄取，不声称建立完整手机社交关系图。

NT/SQLCipher 消息库、保密柜、非 SQLite 数据库、`1120_sa.data` 等未验证格式只记录覆盖状态，不保证解密。媒体表行数不等于原图数量；笔记内容块数不等于用户撰写的笔记篇数；通话录音不等于完整通话记录。单文件索引上限为 8 GiB，数据库及每个 WAL 暂存上限为 256 MiB，业务表和总记录另有读取上限，达到限制会记录未完整解析。

## 验证

```bash
cmake --build build --target forensic_analyzer test_harmony_backup_gtest
ctest --test-dir build --output-on-failure \
  -R 'HarmonyBackupTests|HarmonyBackupCliEndToEndTests|HarmonyBackupHttpEndToEndTests'
```

合成测试覆盖 GNU 长文件名、目录头、应用路径隔离、清单缺失、来源变化、独立 WAL、逐条来源、重复解析、不可用搜索索引、通用分类/提取/时间线及原 HTTP 摄取尾段。HTTP 测试使用本地桩，不调用真实模型。

真实备份测试需显式指定外部检材及独立输出位置：

```bash
python3 tests/integration/test_harmony_backup_cli.py \
  --analyzer build/forensic_analyzer \
  --source /path/to/decrypted-backup --output /path/to/results
```

检材和解析出的个人数据不进入仓库。Python 的 `test_harmony_artifacts.py` 验证记录冻结、原表/主键追溯及自动报告幂等接入；原 Android、MIUI、归档与文件提取测试同时保留。
