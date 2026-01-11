# EventExtractor 子模块

位置: `DatabaseManager/EventExtractor/`

目的
- 从 `_raw.db` 的 `files` 表生成时间线事件并写入 `_events.db`，创建视图便于分析。

主要文件
- `EventExtractor.h`, `EventExtractor.cpp`

公共 API（摘录）
- `EventExtractor(const std::string& sourceDbPath, const std::string& eventDbPath)`
- `bool extractEvents()`

行为说明
- 读取 `files` 表的 atime/mtime/ctime/crtime 等元数据
- 将时间字段逻辑映射为 CREATED/MODIFIED/ACCESSED/CHANGED/DELETED 事件
- 同时维护主 `events` 表和按事件类型的专用表（creation_events 等）
- 创建 `timeline`、`event_statistics`、`hourly_activity` 等视图

实现要点
- 使用事务批量插入以提升性能
- 对缺少 crtime 的文件需容错处理
- 可在插入前做去重策略（例如基于 inode+timestamp+type）

测试建议
- 使用包含已知时间戳的小数据库验证事件数量与排序
- 测试重复记录的去重策略

扩展点
- 增加基于哈希的变更检测事件
- 支持将事件导出为外部时间线格式（如 Plaso 等）
