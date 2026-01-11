# SQLiteHelper 子模块

位置: `HTTPServer/SQLiteHelper.h`

目的
- 将 SQLite 查询结果转换为 JSON，并提供常用查询封装（分页、过滤）。

主要文件
- `SQLiteHelper.h`

建议接口
- `nlohmann::json queryToJson(sqlite3* db, const std::string& sql, int limit = 100, int offset = 0)`
- `nlohmann::json getFileCategories(sqlite3* db)`
- `nlohmann::json getFilesByCategory(sqlite3* db, const std::string& category, int limit, int offset)`

实现要点
- 对每次查询进行行数限制并支持 offset 分页
- 对文本字段进行 UTF-8 验证

测试建议
- 验证 `queryToJson` 在包含 NULL 值和二进制字段时的行为
