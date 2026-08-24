# DatabaseReader（python_service/graphiti_integration/database_reader/）

> **一句话**：取证 SQLite 的统一只读层——工厂按文件名后缀自动发现一个镜像的全部数据库（raw/files/events/windows/linux/android），并为每类库配备带分批迭代与批量统计的专用 reader。

## 1. 为什么有这个模块

C++ 对一个磁盘镜像的产出不是一个库而是一族库（`<base>_raw.db`、`<base>_files.db`、`<base>_events.db`，Windows/Linux/Android 分析各一个）。摄取流水线不应该硬编码"哪张表、哪个后缀、什么 schema"，尤其平台库的表结构随 C++ 版本演化。这个子包提供两件事：**按约定发现**（工厂）与**按类型读取**（reader 继承体系），让上层（MultiSourcePipeline、httpserver 的摄取 worker）面对统一的记录对象。

## 2. 在系统中的位置

- **谁调用它**：`pipeline.py` / `pipeline_multi_source.py`（发现 + 分批读）、httpserver 的 IngestionJobManager worker（直接用 sqlite 时自行处理）、`file_entity_ingestor.py`（导入 FileRecord 类型）。
- **它调用谁**：仅 SQLite（sqlite3 标准库，只读）；不触网络、不触 Neo4j。
- **包结构**：`__init__.py` 是门面（re-export + 工厂）；`raw_reader.py`（FileRecord + ForensicsDatabase，files 库）；`events_reader.py`（EventsDatabase）；`base_reader.py`（`_BaseForensicsReader`）；`windows_reader.py` / `linux_reader.py` / `android_reader.py`（平台 artifacts）。

## 3. 核心数据结构：FileRecord 跨语言契约

```python
# database_reader/raw_reader.py:16-41
@dataclass
class FileRecord:
    """
    Represents a file record from the database with LLM analysis.
    Mirrors the C++ FileRecordWithLLM structure from TOONExporter.
    """

    # Core file metadata
    id: int
    inode: int
    name: str
    path: str
    size: int
    extension: str
    category: str
    file_type: str
    mtime: int  # Unix timestamp
    ctime: int  # Unix timestamp
    is_deleted: bool
    md5: str

    # LLM analysis fields
    llm_summary: Optional[str] = None
    llm_description: Optional[str] = None
    llm_keywords: Optional[str] = None
    llm_analyzed_at: Optional[int] = None  # Unix timestamp
    llm_model_used: Optional[str] = None
```

前 12 个核心字段非空（C++ 建库时必有），后 5 个 llm_* 字段可空——**是否经过 LLM 分析**由 `has_llm_analysis` 属性判定（`llm_analyzed_at > 0`，:43-46），而不是看 summary 是否为空（LLM 可能写出空摘要）。`mtime_datetime`/`ctime_datetime` 属性把 Unix 时间戳惰性转 datetime（:48-60）；`keywords_list`（:62-69）兼容逗号分隔与 JSON 数组两种存储：

```python
# raw_reader.py:63-75
@property
def keywords_list(self) -> list[str]:
    """Parse keywords string into list."""
    if not self.llm_keywords:
        return []
    # Keywords may be comma-separated or JSON array
    keywords = self.llm_keywords.strip()
    if keywords.startswith("["):
        import json
        try:
            return json.loads(keywords)
        except json.JSONDecodeError:
            pass
    return [k.strip() for k in keywords.split(",") if k.strip()]
```

两格式兼容是历史演进产物：早期 LLMService 持久化逗号串，后来 schema 允许 JSON 数组；reader 侧永远输出 list，TOONTransformer 直接把它放进 analysis.keywords。行 → 记录的映射在 `_row_to_record`（raw_reader.py:276-296），注意 `file_type=row["type"]`——DB 列名叫 `type`，字段名叫 `file_type`，且所有列都做 `or 默认值` 容错。

## 4. 核心接口清单

| 接口（真实签名） | 语义 | 主要调用方 | 失败行为 |
|---|---|---|---|
| `ForensicsDatabaseFactory.discover(base_name=None, output_dir=None, any_db_path=None) -> DiscoveredDatabases` | 按后缀表发现全部库 | MultiSourcePipeline、ServiceManager 旧作业 | 无法推断 base_name 抛 `DatabaseError` |
| `ForensicsDatabaseFactory.create_readers(discovered) -> dict` | {files/events/windows/linux/android} → reader 实例 | 流水线 | 不抛（缺库即缺键） |
| `ForensicsDatabase(db_path).get_files(analyzed_only=False, categories=None, limit=None, offset=0)` | 白名单 SELECT 一批 FileRecord | IngestionJobManager（FULL/SINGLE_FILE 模式） | 库不存在构造即抛 DatabaseError |
| `ForensicsDatabase.iter_files_batched(batch_size=100, analyzed_only=False, categories=None)` | OFFSET/LIMIT 生成器分批 | MultiSourcePipeline、ANALYZED_ONLY | 同上 |
| `ForensicsDatabase.count_files(...)` / `get_analysis_stats()` | 进度分母与统计 | 流水线进度回调 | 同上 |
| `EventsDatabase(db_path).iter_event_clusters_batched(...)` | 事件簇分批 | 事件通道 | 表缺失时安静返回空 |
| `get_classified_files(db_path, db_type, artifact_type, limit=None, offset=0)` | artifact_type → 平台 reader 方法的统一入口 | ForensicEpisodeTransformer | 未知类型抛 ValueError |

## 5. 核心概念与设计

**（a）发现约定与 DB_SUFFIXES。** `ForensicsDatabaseFactory.discover()`（database_reader/__init__.py:92-140）的核心是后缀表：

```python
# database_reader/__init__.py:83-90
# Suffix → attribute mapping
DB_SUFFIXES = {
    "_raw.db": "raw_db",
    "_files.db": "files_db",
    "_events.db": "events_db",
    "_windows.db": "windows_db",
    "_linux.db": "linux_db",
    "_android.db": "android_db",
}
```

三种入口：显式 `base_name + output_dir`；或只给 `any_db_path`（任一库的路径），从 stem 剥掉 `_raw/_files/...` 后缀反推 base_name（:114-122）：

```python
# database_reader/__init__.py:112-138（节选）
if any_db_path:
    p = Path(any_db_path)
    output_dir = str(p.parent) if output_dir is None else output_dir
    stem = p.stem
    for suffix_stem in ["_raw", "_files", "_events", "_windows", "_linux", "_android"]:
        if stem.endswith(suffix_stem):
            base_name = stem[: -len(suffix_stem)]
            break
    if base_name is None:
        base_name = stem
# ...
for suffix, attr in cls.DB_SUFFIXES.items():
    candidate = search_dir / f"{base_name}{suffix}"
    if candidate.exists():
        setattr(result, attr, candidate)
    else:
        # Also fall back to pure names like files.db, events.db
        pure_name = suffix.lstrip('_')
        candidate_pure = search_dir / pure_name
        if candidate_pure.exists():
            setattr(result, attr, candidate_pure)
```

找不到 `<base>_files.db` 时还接受纯名 `files.db` 兜底。产出 `DiscoveredDatabases`（:38-73），`available_types` 告诉流水线有什么可读。`create_readers()`（:142-163）把每个发现的路径映射到 reader 实例——注意 raw 库没有 reader（其内容等价于 files 库的用途）。

**（b）files 库的读取 SQL。** ForensicsDatabase 的主查询是模块级常量，白名单选列、按 path 排序、分页三段拼接：

```python
# database_reader/raw_reader.py:85-96
SELECT_FILES_SQL = """
    SELECT
        id, inode, name, path, size, extension, category, type,
        mtime, ctime, is_deleted, md5,
        llm_summary, llm_description, llm_keywords,
        llm_analyzed_at, llm_model_used
    FROM files
    {where_clause}
    ORDER BY path
    {limit_clause}
    {offset_clause}
"""
```

ORDER BY path 保证分批（OFFSET 翻页）结果稳定——没有它，OFFSET 分页在并发写入下可能漏读/重读。`get_analysis_stats`（:310-337）一条 SQL 同时算 total_files/analyzed_files/analysis_percentage，供摄取作业的进度分母。

**（c）分批迭代是内存契约。** `iter_files_batched()`（:246-274）用 OFFSET/LIMIT 生成器分批产出：

```python
# raw_reader.py:263-274
offset = 0
while True:
    batch = self.get_files(
        analyzed_only=analyzed_only,
        categories=categories,
        limit=batch_size,
        offset=offset,
    )
    if not batch:
        break
    yield batch
    offset += len(batch)
```

`EventsDatabase.iter_event_clusters_batched()`（events_reader.py:100）同构。大镜像（百万文件级）不允许一次性读入内存——`count_files` / `get_analysis_stats` 给流水线做进度分母。

**（d）Base reader 防御平台库的 schema 漂移。** `_BaseForensicsReader`（base_reader.py:13）提供：`connect()` 上下文管理器（带 text factory 处理非 UTF-8 文本，:22-43）、`_table_exists` / `_count_rows`（:45-61）、通用 `_query_table`（:63）。平台 reader（Windows/Linux/Android）的每个 get_* 方法（registry_values、user_accounts、sms_messages……）都经 `get_classified_files`（__init__.py:188-238）的 artifact_type → 方法映射暴露（Windows 7 项 / Linux 4 项 / Android 6 项，:211-232），表不存在时安静返回空而非崩溃——旧镜像缺表是常态。

**（e）三个"同名文件"的现状。** 包目录之外还有两个文件：顶层的 `database_reader.py` 与 `database_reader_original.py`。**前者是无效的重复门面**——Python 里同名包（目录）优先于模块（.py），实测 `import graphiti_integration.database_reader` 解析到包的 `__init__.py`；且该 .py 内部的 `from .database_reader.raw_reader import ...` 相对导入若真被加载必然失败，可视为死文件。后者（1053 行）是拆分前的遗留单体实现，仅作历史参考。**读代码认准 `database_reader/` 包。**

## 6. 工作流程走读：MultiSourcePipeline 的发现与读取

`pipeline_multi_source.py:111-117` 调 `ForensicsDatabaseFactory.discover(base_name, output_dir, any_db_path)` → 打印 `discovered.summary()` → `create_readers(discovered)` 得到 `{files, events, windows, ...}` 字典（:127）→ 对 files 库：`count_files()` 定总量，`iter_files_batched()` 逐批产出 FileRecord → TOONTransformer 变换 → 摄取；对平台库同理经 ForensicEpisodeTransformer。

## 7. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| TOONTransformer / ForensicEpisodeTransformer | 消费 FileRecord 与各 reader 的记录 |
| MultiSourcePipeline | 发现与分批读取的唯一编排方 |
| FileEntityIngestor | 复用 FileRecord 类型建 File 实体 |
| C++ 产出的 SQLite | 只读输入（llm_* 列由 httpserver LLMService 写入） |

## 8. 注意事项与已知问题

- 顶层 `database_reader.py` 是被包遮蔽的死文件（见 5e），不要往里加代码；`database_reader_original.py` 不再维护。
- reader 全部只读：没有任何写路径；写（llm 结果回写）在 httpserver 的 LLMService。
- 平台库缺表返回空列表是设计行为，摄取统计里表现为 0 条而非错误。
- `discover` 的纯名兜底（`files.db`）可能在同目录多镜像时匹配到错误文件——多镜像目录务必用带 base_name 的入口。
- OFFSET 翻页在摄取期间若有并发写库（例如同时跑 LLM 批量分析回写 llm_* 列），分页边界可能漂移；统计意义上无害，但严格一致性场景应在摄取窗口内避免写库。

## 9. 如何验证与扩展

- 包内测试：`python_service/graphiti_integration/tests/test_database_reader.py`（需单独跑，不在 pytest testpaths）。
- 新增一种数据库：新建 reader（继承 `_BaseForensicsReader`）→ 在 `DB_SUFFIXES`（__init__.py:83）与 `create_readers` 注册 → 门面 `__all__` re-export → transformer 加变换分支。
- 手工验证：`python -c "from graphiti_integration import ForensicsDatabaseFactory; print(ForensicsDatabaseFactory.discover(any_db_path='<task>/files.db').summary())"`。

## 10. 二轮深化 A：artifact_type → reader 方法全清单（17 项，get_classified_files 的 method_map）

| db_type | artifact_type | 方法 | 数据语义 |
|---|---|---|---|
| windows | registry_values | get_registry_values | 注册表值 |
| windows | event_logs | get_event_logs | 事件日志行 |
| windows | prefetch_files | get_prefetch_files | 预取文件 |
| windows | user_accounts | get_user_accounts | 账户 |
| windows | usb_devices | get_usb_devices | USB 设备 |
| windows | browser_history | get_browser_history | 浏览历史 |
| windows | services | get_services | 服务 |
| linux | log_entries | get_log_entries | 日志行 |
| linux | shell_history | get_shell_history | shell 历史 |
| linux | login_records | get_login_records | 登录记录 |
| linux | groups | get_groups | 用户组 |
| android | contacts | get_contacts | 联系人 |
| android | sms_messages | get_sms_messages | 短信 |
| android | call_logs | get_call_logs | 通话记录 |
| android | chrome_history | get_chrome_history | Chrome 历史 |
| android | installed_packages | get_installed_packages | 已装应用 |
| android | wifi_networks | get_wifi_networks | WiFi 记录 |

17 个键是 ForensicEpisodeTransformer 侧 episode 命名（`windows:{artifact_type}:...`）的取值域；未知键抛 ValueError（__init__.py:234-236）。跨库错配（db_type=windows + artifact_type=contacts）会以"未知 artifact"失败——method_map 不按 db_type 分组校验，但 reader 实例只挂对应域方法，错配实际抛 AttributeError 而非返回空，属可接受的防御深度。

## 11. 二轮深化 B：SELECT 白名单 ↔ files 表列对照（17 列）

SELECT_FILES_SQL（raw_reader.py:85-96）的 17 列与 [FilesDB.md](../../../schema/FilesDB.md) 主表逐列对上：12 个核心（id/inode/name/path/size/extension/category/type/mtime/ctime/is_deleted/md5）+ 5 个 llm_*（summary/description/keywords/analyzed_at/model_used）。两处命名差异：DB 列 `type` → 字段 `file_type`（_row_to_record，:276-296）；atime/crtime **不在白名单**（它们在 raw.db，files 库没有——与 associations 路由的四时间戳分工一致）。llm_is_relevant 同样不读——摄取不按人工相关性过滤（GraphitiService.md 第 3 节的"is_relevant=0 仍是 episode 候选"在此有列级依据）。

## 12. 二轮深化 C：events reader 读取面

两条主查询（events_reader.py:30、:68）都以 `id, timestamp, event_type, file_path, inode` 起头——事件记录与簇记录共享定位五元组；簇聚合查询（:122）按 `(timestamp/60, event_type)` 分组（与 associations/LLM 路由的簇口径一致，bucket_seconds=60 硬编码）；`get_analysis_stats` 用 `GROUP BY event_type` 计数（:166）。与 files 侧一致的契约：iter_*_batched 分批生成器、表缺失安静空、OFFSET 翻页靠 ORDER BY 稳定。

## 13. 二轮深化 D：新走读——connect() 的 GBK 兜底 text_factory（base_reader.py:22-43）

```python
# base_reader.py:24-42（骨架）
conn = sqlite3.connect(str(self.db_path))
conn.row_factory = sqlite3.Row
def _text_factory(bytes_):
    try:
        return bytes_.decode('utf-8')
    except UnicodeDecodeError:
        return bytes_.decode('gbk', errors='replace')
conn.text_factory = _text_factory
yield conn
```

逐块解释：sqlite3 默认 text_factory 是 `str`（按 UTF-8 严格解码）——中文 Windows 镜像里 GBK 编码的文件名会让**任何** SELECT 直接抛 UnicodeDecodeError，整个摄取作业失败。这里换成自定义工厂：先试 UTF-8，失败退 GBK（errors='replace' 保不抛）。代价是坏字节变成 U+FFFD 替换字符——**同一文件名在"纯 UTF-8 库"与"GBK 兜底路径"下可能产生不同字符串**，进而影响 FileRecord.path 的一致性（FileEntityIngestor 的 SHA-256 实体 ID 以 path 为输入——同文件两次摄取理论上可能得到两个实体）。这是已知取舍：可用性优先于字节级幂等。同款兜底也出现在 httpserver 摄取 worker（_worker.py:476-485 附近，path-B 的 JOIN 处理）。

## 14. 二轮深化 E：DiscoveredDatabases 字段表

| 字段 | 类型 | 填充条件 |
|---|---|---|
| base_name / output_dir | str | 显式传入或 any_db_path 反推 |
| raw_db / files_db / events_db | Optional[Path] | `<base>_<suffix>` 存在，或纯名 `raw.db/files.db/events.db` 兜底 |
| windows_db / linux_db / android_db | Optional[Path] | 同上 |
| available_types | list[str] | 以上非 None 者的名字（流水线据此选通道） |

`summary()`（人读字符串）被 pipeline 打日志用；`create_readers` 对 raw_db **不建 reader**（:142-163）——raw 库的四时间戳数据在图谱链路无消费者，只被 associations 路由直连。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
