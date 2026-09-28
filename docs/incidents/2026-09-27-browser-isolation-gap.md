# 2026-09-27 隔离浏览器误连风险记录（保留，不被后续 PASS 覆盖）

状态：`IMPACT_UNCONFIRMED`。这是对 6B 首次浏览器冒烟的**回溯性记录**，不是当时产生的完整访问日志。旧构建的 Python API 默认目标为 `localhost:8090`；当时隔离模拟服务只接管了随机前端端口，浏览器可能向同机既有 8090 发出合成 Task ID 的业务查询（包括 POST 搜索）。首次测试输出路径后来被重用，原始逐请求事件表未完整保留。后续在 `VITE_PYTHON_API_URL=/python` 的 mock 服务上通过，**不能**据此推断首次没有请求或影响。

已有只读核查：

- 检查范围约北京时间 9 月 27 日 16:00–19:00；现有 `build/logs/python_service.log` 最后更新在 9 月 26 日，`cpp_server.log` 更早，相关 PID 在 journald 未见该窗口的记录。
- 未找到可确认的目标 URL、方法/状态码、请求 ID 或认证头。没有读取/输出密码、JWT、真实聊天正文或响应体。
- `tasks.json` 和 `reports.db` 的 mtime 早于该窗口，不能代表所有派生库、日志或缓存完全未变。

机器化只读核查结果：`/tmp/tracelens-6c-incident-audit.json`。缺少原始访问记录时，影响继续标记 `IMPACT_UNCONFIRMED`；如以后取得可信日志，按实际目标、方法、状态码、请求 ID 和业务副作用重新评估，不改写本记录。

针对再次发生的防护：field 前端缺配置时不回退旧 8090/8091；隔离测试在仅 loopback 的独立网络命名空间运行，页面首个请求前启用 CDP 目标白名单并绕过 Service Worker，Vite 测试代理缺显式实例身份/随机目标时拒绝启动。受控禁止端口的请求在发送前被阻断，测试服务收到 0 次；任何其他越界尝试使测试失败。见 [`android-release-6c.md`](../android-release-6c.md)。
