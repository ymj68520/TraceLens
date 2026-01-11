# FileExtractor 子模块

位置: `DatabaseManager/FileExtractor/`

目的
- 基于数据库记录从镜像中提取文件内容，支持按名称/扩展/全部/包含已删除的提取。

主要文件
- `FileExtractor.h`, `FileExtractor.cpp`

公共 API（摘录）
- `FileExtractor(const std::string& imagePath, const std::string& dbPath)`
- `bool initialize()`
- `int extractByName(const std::string& pattern, const std::string& outputDir)`
- `int extractByExtension(const std::string& extensions, const std::string& outputDir)`
- `int extractAll(const std::string& outputDir, bool includeDeleted = false)`
- `bool extractFileByInode(int64_t inode, const std::string& outputPath)`

实现要点
- 使用 TSK API 读取文件数据（按块读取并流写入磁盘）
- 支持通配符（*, ?）匹配文件名
- 保持输出文件的时间戳/权限（如果可行），并记录提取日志

错误处理
- 对 I/O 或读取失败进行日志记录并继续处理其他文件
- 对命名冲突采用后缀重命名策略

测试建议
- 提取后对比文件大小与 MD5（可选）以验证完整性

扩展点
- 增加并发提取选项（限制并发写线程数）
- 提取后自动计算并写入 MD5/SHA256
