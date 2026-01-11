# TaskManager 子模块

位置: `HTTPServer/TaskManager.h`

目的
- 单例线程安全的任务生命周期管理

主要文件
- `TaskManager.h`

公共 API（摘录）
- `static TaskManager& instance()`
- `std::string create_task(const std::string& path)`
- `void update_status(const std::string& id, TaskStatus status, const std::string& msg = "")`
- `void set_result_db(const std::string& id, const std::string& db_path)`
- `AnalysisTask get_task(const std::string& id)`

实现要点
- 使用 `std::map<std::string, AnalysisTask>` 存储任务，`std::mutex` 保护并发访问
- 使用 Boost.Uuid 生成唯一的 task_id

扩展点
- 持久化任务状态以支持重启恢复
- 添加任务优先级与超时自动失败处理
