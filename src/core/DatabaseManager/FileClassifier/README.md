# FileClassifier 子模块

位置: `DatabaseManager/FileClassifier/`

目的
- 将 `_raw.db` 中的文件按扩展名/类型分类到 `_files.db`，并创建统计视图以便快速检索。

主要文件
- `FileClassifier.h`, `FileClassifier.cpp`

公共 API（摘录）
- `FileClassifier(const std::string& sourceDbPath, const std::string& fileDbPath)`
- `bool classifyAndExtract()`

实现要点
- 初始化扩展名到 `FileCategory` 的映射（`extensionMap_`）
- 创建主 `files` 表与 13 个分类表（images/videos/.../unknown_files）
- 分类时使用预编译语句和事务优化大规模插入

分类规则
- 首先依据扩展名（小写化）匹配常用类型
- 可选 fallback: 使用内容检测（libmagic）以提高准确性

测试建议
- 用包含各种扩展名的样例数据库测试 `file_summary` 和 `extension_statistics` 视图

扩展点
- 集成 MIME/魔数检测作为扩展名的后备判定
- 支持自定义分类映射配置文件（JSON/YAML）以便用户扩展
