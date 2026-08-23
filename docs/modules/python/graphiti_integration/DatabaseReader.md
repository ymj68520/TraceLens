# DatabaseReader（python_service/graphiti_integration/database_reader/）

> **一句话**：取证 SQLite 的统一只读层——工厂按文件名后缀自动发现一个镜像的全部数据库（raw/files/events/windows/linux/android），并为每类库配备带分批迭代与批量统计的专用 reader。

## 1. 为什么有这个模块

C++ 对一个磁盘镜像的产出不是一个库而是一族库（`<base>_raw.db`、`<base>_files.db`、`<base>_events.db`，Windows/Linux/Android 分析各一个）。摄取流水线不应该硬编码"哪张表、哪个后缀、什么 schema"，尤其平台库的表结构随 C++ 版本演化。这个子包提供两件事：**按约定发现**（工厂）与**按类型读取**（reader 继承体系），让上层（MultiSourcePipeline、httpserver 的摄取 worker）面对统一的记录对象。

## 2. 在系统中的位置

- **谁调用它**：`pipeline.py` / `pipeline_multi_source.py`（发现 + 分批读）、httpserver 的 IngestionJobManager worker（直接用 sqlite 时自行处理）、`file_entity_ingestor.py`（导入 FileRecord 类型）。
- **它调用谁**：仅 SQLite（sqlite3 标准库，只读）；不触网络、不触 Neo4j。
- **包结构**：`__init__.py` 是门面（re-export + 工厂）；`raw_reader.py`（FileRecord + ForensicsDatabase，files 库）；`events_reader.py`（EventsDatabase）；`base_reader.py`（`_BaseForensicsReader`）；`windows_reader.py` / `linux_reader.py` / `android_reader.py`（平台 artifacts）。

## 3. 核心概念与设计

**（a）发现约定。** `ForensicsDatabaseFactory.discover()`（database_reader/__init__.py:92-140）的核心是 `DB_SUFFIXES` 后缀表（:83-92）。三种入口：显式 `base_name + output_dir`；或只给 `any_db_path`（任一库的路径），从 stem 剥掉 `_raw/_files/...` 后缀反推 base_name（:114-124）；找不到 `<base>_files.db` 时还接受纯名 `files.db` 兜底（:135-139）。产出 `DiscoveredDatabases`（:38-73），`available_types` 告诉流水线有什么可读。`create_readers()`（:142-163）把每个发现的路径映射到 reader 实例——注意 raw 库没有 reader（其内容等价于 files 库的用途）。

**（b）FileRecord 是跨语言契约。** `FileRecord`（raw_reader.py:16-40）镜像 C++ `TOONExporter` 的 `FileRecordWithLLM` 结构（docstring 明说），核心字段 + 五个 llm_* 可空字段；`has_llm_analysis`（:43）以 `llm_analyzed_at > 0` 判定；`keywords_list`（:62-69）兼容逗号分隔与 JSON 数组两种存储。它是 TOONTransformer 的输入类型，也是整个变换链的通用货币。

**（c）Base reader 防御平台库的 schema 漂移。** `_BaseForensicsReader`（base_reader.py:13）提供：`connect()` 上下文管理器（带 text factory 处理非 UTF-8 文本，:22-43）、`_table_exists` / `_count_rows`（:45-61）、通用 `_query_table`（:63）。平台 reader（Windows/Linux/Android）的每个 get_* 方法（registry_values、user_accounts、sms_messages……）都经 `get_classified_files`（__init__.py:188-238）的 artifact_type → 方法映射暴露，表不存在时安静返回空而非崩溃——旧镜像缺表是常态。

**（d）分批迭代是内存契约。** `ForensicsDatabase.iter_files_batched()`（raw_reader.py:246）与 `EventsDatabase.iter_event_clusters_batched()`（events_reader.py:100）用 OFFSET/LIMIT 生成器分批产出，`count_files` / `get_analysis_stats`（raw_reader.py:181、:310）给流水线做进度分母。大镜像（百万文件级）不允许一次性读入内存。

**（e）三个"同名文件"的现状。** 包目录之外还有两个文件：顶层的 `database_reader.py` 与 `database_reader_original.py`。**前者是无效的重复门面**——Python 里同名包（目录）优先于模块（.py），实测 `import graphiti_integration.database_reader` 解析到包的 `__init__.py`；且该 .py 内部的 `from .database_reader.raw_reader import ...` 相对导入若真被加载必然失败，可视为死文件。后者（1053 行）是拆分前的遗留单体实现，仅作历史参考。**读代码认准 `database_reader/` 包。**

## 4. 工作流程走读：MultiSourcePipeline 的发现与读取

`pipeline_multi_source.py:111-117` 调 `ForensicsDatabaseFactory.discover(base_name, output_dir, any_db_path)` → 打印 `discovered.summary()` → `create_readers(discovered)` 得到 `{files, events, windows, ...}` 字典（:127）→ 对 files 库：`count_files()` 定总量，`iter_files_batched()` 逐批产出 FileRecord → TOONTransformer 变换 → 摄取；对平台库同理经 ForensicEpisodeTransformer。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| TOONTransformer / ForensicEpisodeTransformer | 消费 FileRecord 与各 reader 的记录 |
| MultiSourcePipeline | 发现与分批读取的唯一编排方 |
| FileEntityIngestor | 复用 FileRecord 类型建 File 实体 |
| C++ 产出的 SQLite | 只读输入（llm_* 列由 httpserver LLMService 写入） |

## 6. 注意事项与已知问题

- 顶层 `database_reader.py` 是被包遮蔽的死文件（见 3e），不要往里加代码；`database_reader_original.py` 不再维护。
- reader 全部只读：没有任何写路径；写（llm 结果回写）在 httpserver 的 LLMService。
- 平台库缺表返回空列表是设计行为，摄取统计里表现为 0 条而非错误。
- `discover` 的纯名兜底（`files.db`）可能在同目录多镜像时匹配到错误文件——多镜像目录务必用带 base_name 的入口。

## 7. 如何验证与扩展

- 包内测试：`python_service/graphiti_integration/tests/test_database_reader.py`（需单独跑，不在 pytest testpaths）。
- 新增一种数据库：新建 reader（继承 `_BaseForensicsReader`）→ 在 `DB_SUFFIXES`（__init__.py:83）与 `create_readers` 注册 → 门面 `__all__` re-export → transformer 加变换分支。
- 手工验证：`python -c "from graphiti_integration import ForensicsDatabaseFactory; print(ForensicsDatabaseFactory.discover(any_db_path='<task>/files.db').summary())"`。

**最后更新**: 2026-08-23（解释式重写）
