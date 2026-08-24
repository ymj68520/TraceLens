# Schema 一致性检查手册

> 这不是第三份字段清单，而是回答“代码、SQLite 文件、Python reader、前端查询是否仍然说同一种 schema”的检查手册。TraceLens 的 schema 有三层来源：C++ SQL 头文件、分析器写入代码、Python/HTTP 查询代码；任何一层漂移，通常都会表现为某类工件静默为空，而不是启动时报错。

## 1. 三份事实源

| 层 | 位置 | 可信用途 | 常见漂移 |
|---|---|---|---|
| 建表定义 | `src/core/DatabaseManager/SQL/*.h` | 列名、类型、默认值、索引 | `*_crud.h` 有坏占位符副本 |
| 写入实现 | 各 Analyzer `Database/`、`*_Operations_*.cpp` | 实际 INSERT 列顺序与条件 | 解析器已写但没有调用方 |
| 读取/LLM | `SQLiteHelper`、Python `database_reader/`、LLM 服务 | 真实 SELECT 列名与库发现 | 7 个 Linux LLM SELECT 引用了不存在列 |

不要只看 SQL 头文件就宣布“功能可用”：Windows 的 shimcache 表有 DDL，但解析器没有接线；OSS 表有完整 schema，但 OSSAnalyzer 没有生产调用方。

## 2. 每次 schema 变更的五步检查

1. **加表或列**：先改 SQL 头文件，确认 CREATE/ALTER 的真实列；
2. **写入**：检查 INSERT 的列数、placeholder 数、类型绑定；
3. **读取**：全文搜索表名与列名，逐个确认 SELECT 与 DDL 一致；
4. **发现器**：若是新库后缀，更新 `ForensicsDatabaseFactory.DB_SUFFIXES` 与对应 reader；
5. **测试/文档**：加最小 fixture，更新 `docs/schema/`、模块文档和 API 映射。

## 3. 自动化 SQL 检查

### 3.1 建表后检查对象

```sql
SELECT type, name, tbl_name
FROM sqlite_master
WHERE type IN ('table','index','view')
ORDER BY type, name;
```

用法：在任务目录逐个 `.db` 执行，先确认对象存在，再解释“空表”。`sqlite_master` 的对象集合比接口返回的摘要更接近实际。

### 3.2 列名核对

```sql
PRAGMA table_info(files);
PRAGMA table_info(events);
PRAGMA index_list(files);
```

把输出和 `docs/schema/<库>.md` 对照。`PRAGMA table_info` 返回的顺序就是 CREATE TABLE 顺序，INSERT 代码使用位置绑定时尤其重要。

### 3.3 写入前后的行数检查

```sql
SELECT name,
       (SELECT COUNT(*) FROM sqlite_master sm2 WHERE sm2.name=sm.name) object_exists
FROM sqlite_master sm
WHERE type='table';
```

实际分析时更有价值的是按业务表对照：raw.files → files.files → 平台库。数量不必相等，但差异必须能用过滤、场景或解析器覆盖解释。

## 4. 当前已知不一致矩阵

| 区域 | 现象 | 影响 | 诊断 |
|---|---|---|---|
| raw.db | `llm_*` 五列建出但从不写 | 永远 NULL | 直接查 `SUM(llm_summary IS NOT NULL)` |
| events.db | extractor 版 `event_correlations` 与 engine 版 DDL 列集不同 | 引擎接线会 INSERT 失败 | 先统一 DDL 再接线 |
| Linux LLM | 7 组 SELECT 取不存在列 | 这些工件 LLM 静默空转 | 看 prepare 错误与 `linux_analysis_sql_llm.h` |
| Windows CRUD | MFT/browser cookie 占位符少一个 | 坏副本不可用 | 生产写入走 Operations 内联版本 |
| Windows | shimcache/user_assist/rdp/wifi 无调用方 | 表恒空 | 搜 Core 编排调用点 |
| Android | analysis_progress 无主键 | 重复 task 行可能存在 | `PRAGMA table_info` + 行数检查 |
| OSS | timestamp 恒 0 | 访问日志无法按真实时间排序 | 查 parser TODO；当前无生产调用方 |
| PG | 001 种子凭据坏、002/003 不自动应用 | super_admin 401 | 查 index 与邮箱 |

## 5. “表为空”诊断树

```text
表为空
├─ DDL 对象不存在？ → 建库路径/版本初始化问题
├─ DDL 存在、写入方不存在？ → 未接线（恒空，文档应明确标注）
├─ 写入方存在、调用点不存在？ → 解析器孤儿代码
├─ 调用点存在、输入文件未发现？ → 路径/镜像类型/权限问题
├─ INSERT 执行失败？ → 查列名、placeholder、类型绑定
└─ 有行但 LLM 列为空？ → llm_analyze 门控/端点/坏 SELECT
```

每个分支都应留下证据：DDL、调用点、日志、行数，而不是只看前端的空数组。

## 6. Python reader 的契约

Python 通过后缀发现库：`_raw.db`、`_files.db`、`_events.db`、`_windows.db`、`_linux.db`、`_android.db`。HTTP 任务使用 `raw.db` 等短名称时，`task_store` 负责把任务目录解析成真实路径；Graphiti reader 使用后缀发现时，CLI 与 HTTP 的命名布局不完全相同。

对新库的最小契约：

| 检查 | 问题 |
|---|---|
| 后缀注册 | factory 能否发现文件 |
| reader | 缺表时返回空还是抛异常 |
| FileRecord | path、size、mtime、description 是否有值 |
| task_id | episode group 是否隔离 |
| 关闭 | sqlite connection 是否在 finally 关闭 |

## 7. 提交前清单

- [ ] `CREATE TABLE` 与每个 INSERT 列数一致；
- [ ] 生产调用路径不是只在单测中出现；
- [ ] 读写列名逐字匹配；
- [ ] 过滤后库与原库的语义写进文档；
- [ ] 空表是预期还是缺陷有明确结论；
- [ ] Python reader、Graphiti transformer、API 查询都能识别新字段；
- [ ] schema 文档给出至少一条可执行 SQL；
- [ ] 迁移/回滚或“无版本自愈”的边界写清；
- [ ] 相关测试目标被 ctest/pytest/vitest 收录。

## 相关文档

- [DatabaseSchema](../architecture/DatabaseSchema.md)
- [schema 字段参考](../schema/FilesDB.md)
- [WritingTests](../testing/WritingTests.md)
- [SqlCookbook](SqlCookbook.md)

---

**最后更新**: 2026-08-24（新建：schema 一致性检查）
