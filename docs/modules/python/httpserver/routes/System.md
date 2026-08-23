# System 路由（python_service/httpserver/routes/system.py，前缀 /api/system；并说明 system_logs.py 为未注册死代码）

> **一句话**：Python 服务（:8090）上的服务日志端点——按服务名读取 `build/logs/*.log` 的尾部若干行（结构化解析）并以 SSE 流式尾随，供前端 /logs 页与终端组件实时看双后端日志。

## 1. 这组路由承担什么职责（为什么存在）

排障需要同时看 C++（cpp_server.log）与 Python（python_service.log）两个进程的日志，而两进程都可能无头运行。system.py 把两个日志文件统一成一个 HTTP 面：拉取式（`/logs/{service}`）与订阅式（`/logs-stream/{service}` SSE）。它是**纯读文件**的端点，不接 logging 框架、不读 journal——日志文件由启动脚本/运行环境写入 `build/logs/`。

同目录还有一个 system_logs.py，定义了同类端点但**从未被注册**（见第 5 节），是死代码；线上真正生效的 /api/system/logs* 全部来自 system.py。

## 2. 典型调用方（前端哪个页面/组件）

- `/logs` 页（web/src/pages/Logs.jsx）：`fetch(`${PYTHON_BASE}/api/system/logs/${service}?lines=200`)`（:20）+ `new EventSource(`${PYTHON_BASE}/api/system/logs-stream/${service}`)`（:37）。
- 通用终端组件 `web/src/components/common/TerminalOutput.jsx`：SSE 端点 :54-55、拉取端点 :91-92（cpp/python 双 tab）。
- 服务端无调用方；C++ 不调它。注意区分：`web/src/services/systemService.js` 里的 `/api/system/health`、`/api/system/info` 等走的是 C++ 前缀（`api` 客户端），与本组无关。

## 3. 端点语义分组（散文）

完整契约见 docs/api_reference/Python_REST_API.md 第 15 节。本组只有三个端点：

- `GET /api/system/logs`（system.py:16-22）——旧组件不带服务名的兜底，等价于 `/logs/python`。
- `GET /api/system/logs/{service}`（:64-93）——service ∈ {cpp, python}，返回尾部 `lines` 行（默认 100，1-2000）的结构化数组 `{service, logs[], total_lines}`。
- `GET /api/system/logs-stream/{service}`（:95-127）——SSE（text/event-stream），`data:` 载荷为逐行解析的 JSON，follow 模式（从文件末尾起，无新行时 0.5s 轮询）。

## 4. 数据流（读什么库/服务、写什么；关键机制 file:line）

纯读路径。项目根定位有点绕——按"当前工作目录的上一级有 build/ 则用之，否则用 cwd"推断（:71-74），日志映射固定为：

```python
# system.py:76-79
log_map = {
    "cpp": os.path.join(project_root, "build", "logs", "cpp_server.log"),
    "python": os.path.join(project_root, "build", "logs", "python_service.log"),
}
```

读取用 `f.readlines()` 全量入内存后切片（:86-88）——大日志文件时是已知的简单实现取舍：

```python
# system.py:81-90
log_path = log_map.get(service)
if not log_path or not os.path.exists(log_path):
    return {"service": service, "logs": [{"timestamp": "", "level": "WARN", "message": "Log file not found"}]}

try:
    with open(log_path, 'r', errors='replace') as f:
        content = f.readlines()
        last_lines = content[-lines:] if len(content) > lines else content
        structured_logs = [_parse_line(line) for line in last_lines]
        return {"service": service, "logs": structured_logs, "total_lines": len(content)}
```

找不到文件/未知服务名共用同一个"200 + WARN 行"分支——这就是第 5 节"不会 400"的实现点。行解析 `_parse_line`（:24-62）按三种格式尝试，全部失败时退化为"当前时间戳 + INFO + 原文"（不丢日志行）：

```python
# system.py:35-54（节选）
try:
    # Format 1: 2026-03-06 14:42:47,477 - NAME - LEVEL - MSG
    match = re.search(r'(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})[,\d]*\s-\s\S+\s-\s(\w+)\s-\s(.*)', line)
    if match:
        timestamp = match.group(1).replace(' ', 'T')
        level = match.group(2)
        message = match.group(3)
    # Format 2: 14:55:04 [INFO] MSG (as seen in user output)
    else:
        match2 = re.search(r'(\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(.*)', line)
        if match2:
            timestamp = f"2026-03-06T{match2.group(1)}"
            level = match2.group(2)
            message = match2.group(3)
        # Format 3: INFO: ...
        elif ":" in line[:10]:
            parts = line.split(":", 1)
            level = parts[0].strip().upper()
            message = parts[1].strip()
except:
    pass
```

进入分支前的默认值就是兜底语义（:30-33）：`timestamp = datetime.now().isoformat()`、`level = "INFO"`、`message = line`——三个分支全不中时原始行原样进 message，绝不丢行；`except: pass` 把解析器自身异常也吞回默认值。无服务名兜底端点直接复用 python 分支（:16-22）：

```python
# system.py:16-22
@router.get("/logs")
async def get_all_logs(
    lines: int = Query(default=100, ge=1, le=2000),
    settings: Settings = Depends(get_settings),
):
    """Fallback for old components requesting /logs without service name."""
    return await get_service_logs("python", lines, settings)
```

即直接调用 `/logs/{service}` 的处理函数（FastAPI handler 可当普通函数复用），把旧组件的 `/api/system/logs` 归一到 python 日志。

三个分支对应双后端的日志配置：Format 1 是 Python logging 的 `%(asctime)s - %(name)s - %(levelname)s - %(message)s`（main.py:29-35）；Format 2/3 覆盖 C++ 侧输出。注意 Format 2 的时间戳补的是**硬编码日期** `2026-03-06`（原始行只有时分秒）——展示层够用，但不能当真实日期用。

SSE 生成器（:112-125）`seek(0, SEEK_END)` 起步后循环 `readline()`，空行 `await asyncio.sleep(0.5)`——这是经典的 tail -f 轮询模式，不是 inotify；文件截断（轮转）场景不会自动重开句柄：

```python
# system.py:112-125（节选）
async def log_generator():
    import json
    with open(log_path, 'r', errors='replace') as f:
        # Start at the end
        f.seek(0, os.SEEK_END)
        import asyncio
        while True:
            line = f.readline()
            if not line:
                await asyncio.sleep(0.5)
                continue
            # Parse to JSON
            structured = _parse_line(line)
            yield f"data: {json.dumps(structured)}\n\n"
```

`errors='replace'` 容错编码（:86、:114）保证半行/坏字节不炸流。

## 5. 边界与已知状态（死代码/404/无鉴权）

- **system_logs.py 是未注册死代码**：main.py::_register_routes 只 import 并挂载 system.py（main.py:199、:243），system_logs.py 的 router 没有任何 `include_router`。它的 `/api/system/logs`（system_logs.py:108）与 `/api/system/logs/stream`（:151，固定 501 占位）从未生效；其探测路径（`logs/httpserver.log`、`/tmp/forensics_python.log`，:81-86）也与真实落点 `build/logs/*.log` 不符。线上 `/api/system/logs` 的实际行为一律以 system.py 为准——本节即为此留下记录。
- **拉取 vs 流式的错误语义不一致**：`/logs/{service}` 找不到文件时返回 200 + 一条 `WARN "Log file not found"`（:82-83）；`/logs-stream/{service}` 同样情况抛 404（:109-110）。前端 Logs.jsx 对两种都做了兜底。
- `service` 不在 {cpp, python} 时拉取端点也返回 200 + "Log file not found"（log_map 未命中走同一分支），不会 400。
- 端点无鉴权、无行数上限以外的限流；日志内容原样外发（`errors='replace'` 容错编码，:86）。
- SSE 连接没有心跳/超时机制，客户端断开靠框架回收。
- env：无；路径推断完全依赖 cwd（uvicorn 以 `python_service/` 为 cwd 启动时，`os.getcwd()/..` 恰好命中仓库根——换启动目录会读不到日志，这是隐式耦合）。

## 6. 如何验证

- 本组**没有单元测试**（tests/unit 下无 system 相关文件）——改动时靠手工验证：`curl ':8090/api/system/logs/python?lines=20'` 看结构化输出；`curl -N ':8090/api/system/logs-stream/cpp'` 触发一次 C++ 请求观察增量行。
- 交叉验证死代码结论：`grep -rn "system_logs" python_service/httpserver/main.py` 无结果，而 `system` 在 main.py:243 挂载。
- 回归注意点：若改 `_parse_line` 的正则，用真实 build/logs 双格式样本对照（两种格式分别来自 C++ 与 Python 的日志配置）。

相关阅读：[HTTPRoutes.md](../HTTPRoutes.md)、[Main.md](../Main.md)（:8090 生命周期与日志落盘）、[Health.md](Health.md)。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
