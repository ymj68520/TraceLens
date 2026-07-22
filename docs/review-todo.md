# 待你后续审查的问题说明

## 1) Neo4j 本地报错：Unable to retrieve routing information

### 现象
在 debug 中常见：
- `Unable to retrieve routing information`
或 Nova/neo4j 相关路由探测失败。

### 当前验证结果
- 已在本机检查到安装产物：
  - `neo4j` 与 `cypher-shell` 版本均为 `2026.06.0`
- 但当前环境**未发现正在运行的 neo4j 服务/进程**
- 端口 `7687` **没有监听**

### 初步结论（待你确认）
当前该错误更像是 **“服务没启动/未监听”**，而不是 TraceLens 代码本身在路由配置上必然崩溃。
若你后续需要跨任务图谱关联，只需额外做两步之一即可：
1. 启动本地 neo4j 服务
2. 显式指定可连通 bolt 地址后重新触法路由探测

### 建议继续排查项
- 确认是否安装了 **Neo4j Desktop / Server / Aura** 其中一种运行时
- 检查 `neo4j.conf` 中 `dbms.default_listen_address` / `dbms.connector.bolt.listen_address`
- 确认 7687 未被其他进程占用，且防火墙允许本地连接

## 2) aliases.db 报错：file is not a database

### 现象
系统把 `etc/aliases.db` 交给 `SQLiteExtractor` 后报：
- `file is not a database`

### 当前结论
- `.db` 后缀**不等于 SQLite**，这里属于**误路由**
- 不是 SQLCipher 未配置问题（前面已做 fallback 处理）

### 建议修复方向
- 增加按**魔数/文件头**识别数据库类型的前置判断
- 对 `aliases.db` 这类非 SQLite 的 `.db` 文件：
  - 走 `TextDumpExtractor/Generic binary-aware` 处理
  - 或者单独映射到对应解析器
- 仅在确认数据库头为 SQLite/兼容格式时再进入 `SQLiteExtractor`

### 审查建议
- 你优先审查我补丁里的 `GenericDatabaseExtractor` / extractor mapping 是否满足你的取证口径
- 如果你希望保守处理：可先对 `aliases` 这类已知名单做白名单跳过或降级为文本导出

## 审查优先级建议
1. Neo4j 是否真的需要在线图谱关联；若不需要，当前降级逻辑已可保持主流程可用。
2. `.db` 文件路由策略：是否接受“按魔数分流”而不是按扩展名分流。

