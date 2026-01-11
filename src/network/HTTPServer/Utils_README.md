# Utils 子模块

位置: `HTTPServer/Utils.h`

目的
- 通用工具函数集合，包含协程/异步包装、错误转换和常用字符串处理。

主要文件
- `Utils.h`

示例工具
- `run_async(Func&& func)` - 使用 `std::async` 启动后台任务
- `AsyncTask` - 简单的 coroutine promise/返回对象示例

并发注意
- 在协程或多线程环境共享资源时使用局部 DB 句柄或互斥保护

扩展点
- 增加一个通用的 task runner 以便把分析任务调度到后台 worker
