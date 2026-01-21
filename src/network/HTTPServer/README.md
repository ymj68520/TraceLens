# HTTPServer (C++) - REST API 服务核心

## 1. 模块概述 (Overview)

**HTTPServer (C++)** 是取证分析平台的REST API服务核心，基于高性能Crow框架构建，为Web前端、移动客户端和第三方工具提供完整的HTTP接口。该模块采用异步I/O和多线程架构，能够高效处理大量并发请求，同时管理长时间运行的取证分析任务。

该模块为客户解决"取证工具需要远程访问、自动化集成、实时监控"的核心需求。无论是通过Web界面进行交互式分析，还是通过脚本批量处理多个镜像，HTTPServer都能提供稳定、可靠的API服务，是整个取证平台的服务中枢。

**核心业务价值:**
- **统一API网关**:单一入口点访问所有取证功能，简化集成复杂度
- **异步任务管理**:支持长时间运行的分析任务，不阻塞API响应
- **高性能处理**:异步I/O + 线程池，支持数百并发连接
- **标准化接口**:RESTful API设计，符合业界标准，易于对接
- **实时进度跟踪**:任务进度、阶段、ETA实时查询，用户体验友好

---

## 2. 核心功能列表 (Key Features)

### 2.1 任务管理 API (TaskRoutes)

- **任务创建与配置**
  - 支持多种分析类型：完整分析、快速扫描、特定平台分析
  - 任务优先级设置：LOW、NORMAL、HIGH、CRITICAL
  - 自定义输出目录和文件名
  - 分析选项配置（如XFS模式、过滤规则）

- **任务状态查询**
  - 实时任务进度：总体百分比和阶段进度
  - 任务阶段追踪：INITIALIZING、IMAGE_ANALYSIS、EVENT_EXTRACTION等
  - 时间估算：预计完成时间(ETA)
  - 任务历史：已完成、失败、已取消任务的记录

- **任务控制**
  - 取消正在运行的任务
  - 暂停/恢复任务（部分支持）
  - 批量任务管理
  - 任务依赖关系配置

### 2.2 取证分析 API (ForensicsRoutes)

- **时间线分析**
  - 完整时间线：所有文件的创建、修改、访问、删除事件
  - 按时间范围筛选：小时、天、周、月级别活动统计
  - 异常活动检测：大量删除、批量修改等可疑行为
  - 用户活动重建：特定用户/进程的操作轨迹

- **文件分析**
  - 文件分类统计：13类文件的分布和占比
  - 最大的文件：快速定位大文件（可能包含重要数据）
  - 最近的文件：按修改时间排序
  - 重复文件检测：基于哈希值的文件去重
  - 扩展名统计：识别文件类型分布

- **平台专项分析**
  - **Windows取证**：注册表、事件日志、浏览器历史、Prefetch
  - **Android取证**：短信、联系人、通话记录、应用使用
  - **Linux取证**：系统日志、用户账户、Shell历史、Cron任务

- **统计与报告**
  - 概览统计：文件总数、总大小、分析时长
  - 活动模式：工作时间/非工作时间活动分布
  - 删除文件分析：已删除文件的数量和类型
  - 数据导出：JSON、CSV、TOON格式导出

### 2.3 全文搜索 API (SearchRoutes)

- **索引管理**
  - 创建索引：对提取的文件内容建立全文索引
  - 索引状态查询：索引进度、文档数量
  - 索引更新：增量更新已变更的文件

- **搜索功能**
  - 关键词搜索：支持布尔查询（AND、OR、NOT）
  - 通配符搜索：支持`*`和`?`通配符
  - 路径过滤：按目录、扩展名筛选搜索范围
  - 结果高亮：搜索关键词在结果中高亮显示
  - 相关性排序：按匹配度排序结果

### 2.4 系统监控 API (SystemRoutes)

- **健康检查**
  - 服务存活状态：`/health`、`/health/live`、`/health/ready`
  - 数据库连接状态
  - 后端服务可用性
  - 磁盘空间检查

- **数据库信息**
  - 数据库列表：所有可用的取证数据库
  - 表结构查询：数据库schema文档
  - 数据库大小、记录数统计
  - 索引信息查询

- **系统资源监控**
  - CPU使用率
  - 内存占用（当前、峰值）
  - 磁盘I/O统计
  - 网络连接数

- **API文档**
  - Swagger/OpenAPI规范：`/docs`
  - 端点列表：所有可用的API端点
  - 示例请求和响应

### 2.5 高级特性

- **异步任务调度**
  - 任务队列管理：支持多任务排队执行
  - 线程池：动态调整工作线程数量
  - 任务优先级：高优先级任务优先执行
  - 资源限制：控制并发任务数量，防止资源耗尽

- **性能优化**
  - 连接池：数据库连接复用
  - 查询缓存：缓存常用查询结果（TTL可配置）
  - 响应压缩：GZIP压缩大响应体
  - 分页支持：大数据集分页返回

- **安全特性**
  - CORS支持：跨域资源共享配置
  - 请求验证：输入参数校验和清理
  - 错误处理：统一错误响应格式
  - 日志记录：所有API请求的审计日志

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一：Web前端交互式分析平台

**背景**：某取证公司需要开发Web前端，为客户提供自助式取证分析服务。

**业务流程**：
1. **用户上传镜像**：前端通过`POST /api/tasks`上传磁盘镜像
   ```json
   {
     "image_path": "/uploads/evidence.E01",
     "analysis_type": "full",
     "priority": "HIGH",
     "options": {
       "android_analyze": true,
       "carve_deleted": true
     }
   }
   ```

2. **实时进度显示**：前端每2秒轮询`GET /api/tasks/{task_id}`
   ```json
   {
     "task_id": "task_123",
     "status": "RUNNING",
     "progress": 45,
     "current_phase": "FILE_CLASSIFICATION",
     "eta_seconds": 1800
   }
   ```

3. **结果可视化**：任务完成后，前端调用多个API获取数据
   - `GET /api/timeline?task_id=123` → 时间线图表
   - `GET /api/files?task_id=123&sort=size` → 文件列表
   - `GET /api/statistics?task_id=123` → 统计概览

4. **报告导出**：用户点击导出按钮
   ```bash
   GET /api/tasks/123/export?format=toon
   ```

**价值体现**：提供友好的Web界面，客户无需安装软件即可完成取证分析，降低使用门槛。

### 场景二：自动化批量处理流水线

**背景**：安全运营中心需要每天自动分析数百个终端镜像，检测潜在威胁。

**业务流程**：
1. **批量任务创建**：Python脚本遍历镜像目录
   ```python
   for image_path in glob.glob("/mirrors/*.E01"):
       task = requests.post("http://server:8080/api/tasks", json={
           "image_path": image_path,
           "priority": "NORMAL",
           "options": {"windows_analyze": True}
       }).json()
       task_ids.append(task["task_id"])
   ```

2. **异步等待完成**：脚本定期检查所有任务状态
   ```python
   while not all_completed(task_ids):
       time.sleep(60)
       # 更新进度到监控系统
   ```

3. **结果收集与分析**：获取所有任务的关键发现
   ```python
   for task_id in task_ids:
       timeline = requests.get(f"http://server:8080/api/timeline?task_id={task_id}").json()
       suspicious = detect_suspicious_activity(timeline)
       alert_if_needed(suspicious)
   ```

4. **自动报告生成**：汇总生成每日威胁报告

**价值体现**：实现7x24小时自动化取证分析，大幅提升安全运营效率。

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**必需的外部库**：
- **Crow Framework** 1.0+：高性能C++ HTTP框架
- **asio** 1.18.0+：异步I/O库
- **nlohmann/json** 3.10+：JSON解析和生成
- **SQLite3** 3.35.0+：数据库访问
- **boost** 1.74+：系统库（system、thread等）

**编译器要求**：
- GCC 9.0+ 或 Clang 10.0+
- C++20标准支持
- CMake 3.15+

**系统要求**：
- **操作系统**：Linux（推荐Ubuntu 20.04+）、Windows 10+、macOS 11+
- **内存**：最低4GB，推荐8GB+（处理大量并发请求）
- **网络**：开放指定端口（默认8080）
- **文件描述符**：`ulimit -n`建议设置为65536

### 关键配置项

**服务器配置**：
```cpp
HTTPServer::Config config;

// 绑定地址和端口
config.host = "0.0.0.0";  // 监听所有网卡
config.port = 8080;

// 线程池配置
config.workerThreads = 8;  // 工作线程数
config.maxConnections = 1000;  // 最大并发连接
config.requestTimeout = 300;  // 请求超时(秒)

// 任务管理配置
config.maxConcurrentTasks = 4;  // 最大并发分析任务
config.taskQueueSize = 100;  // 任务队列大小

// 缓存配置
config.enableCache = true;
config.cacheTTL = 300;  // 缓存生存时间(秒)
config.maxCacheSize = 1000;  // 最大缓存条目数

// 日志配置
config.logLevel = "INFO";
config.accessLog = "/var/log/forensic/access.log";
config.errorLog = "/var/log/forensic/error.log";

// CORS配置
config.enableCORS = true;
config.allowedOrigins = {"*"};  // 生产环境应限制具体域名
```

**命令行参数**：
```bash
# 启动HTTP服务器
forensic_analyzer --http-server 8080

# 指定线程数
forensic_analyzer --http-server 8080 --threads 16

# 启用详细日志
forensic_analyzer --http-server 8080 --verbose

# 仅监听本地回环（仅用于本地测试）
forensic_analyzer --http-server 127.0.0.1:8080
```

### 性能优化建议

**提高并发处理能力**：
1. 增加工作线程数（`--threads`参数）
2. 调整数据库连接池大小
3. 启用HTTP keep-alive复用连接
4. 使用反向代理（如Nginx）做负载均衡

**加速API响应**：
1. 启用查询缓存（对统计类API效果显著）
2. 使用数据库索引优化慢查询
3. 对大响应启用GZIP压缩
4. 实现分页，避免一次性返回大量数据

**生产环境部署**：
```nginx
# Nginx反向代理配置示例
upstream forensic_backend {
    server 127.0.0.1:8080;
    server 127.0.0.1:8081;  # 多实例部署
}

server {
    listen 443 ssl;
    server_name forensic.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location /api/ {
        proxy_pass http://forensic_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 3600s;  # 长时间任务
    }
}
```

---

## 5. 接口与集成说明 (API & Integration)

### 核心API端点

**任务管理**：
```bash
# 创建分析任务
POST /api/tasks
Content-Type: application/json

{
  "image_path": "/path/to/evidence.dd",
  "analysis_type": "full",  # full, quick, windows, android, linux
  "priority": "NORMAL",  # LOW, NORMAL, HIGH, CRITICAL
  "options": {
    "android_analyze": true,
    "carve_deleted": false,
    "xfs_mode": "auto"
  }
}

# 响应
{
  "success": true,
  "task_id": "task_abc123",
  "status": "PENDING",
  "message": "Task created successfully"
}

# 查询任务状态
GET /api/tasks/{task_id}

# 列出所有任务
GET /api/tasks?status=RUNNING&limit=10

# 取消任务
DELETE /api/tasks/{task_id}
```

**时间线分析**：
```bash
# 获取完整时间线
GET /api/timeline?task_id=123&start=2024-01-01&end=2024-01-31

# 按事件类型筛选
GET /api/timeline?task_id=123&type=DELETED&type=MODIFIED

# 获取活动统计
GET /api/activity/hourly?task_id=123

# 检测异常活动
GET /api/activity/suspicious?task_id=123
```

**文件查询**：
```bash
# 获取文件列表（分页）
GET /api/files?task_id=123&page=1&page_size=50

# 按类型筛选
GET /api/files?task_id=123&category=documents

# 查询大文件
GET /api/files?task_id=123&sort=size&order=desc&limit=100

# 查询最近修改的文件
GET /api/files?task_id=123&sort=mtime&order=desc&limit=50

# 查询重复文件
GET /api/files/duplicates?task_id=123
```

**统计信息**：
```bash
# 获取概览统计
GET /api/statistics?task_id=123

# 文件类型分布
GET /api/statistics/files-by-type?task_id=123

# 扩展名统计
GET /api/statistics/extensions?task_id=123

# 删除文件统计
GET /api/statistics/deleted?task_id=123
```

**数据导出**：
```bash
# 导出为JSON
GET /api/tasks/123/export?format=json

# 导出为TOON格式（高效LLM提示）
GET /api/tasks/123/export?format=toon

# 导出为CSV
GET /api/tasks/123/export?format=csv

# 导出特定表
GET /api/tasks/123/export?table=files&format=json
```

### 编程接口示例

**JavaScript (前端)**：
```javascript
// 创建任务
const createTask = async (imagePath) => {
  const response = await fetch('http://localhost:8080/api/tasks', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      image_path: imagePath,
      analysis_type: 'full',
      priority: 'HIGH'
    })
  });
  const data = await response.json();
  return data.task_id;
};

// 轮询任务进度
const pollTaskProgress = async (taskId) => {
  const interval = setInterval(async () => {
    const response = await fetch(`http://localhost:8080/api/tasks/${taskId}`);
    const task = await response.json();

    updateProgressBar(task.progress);
    updatePhase(task.current_phase);

    if (task.status === 'COMPLETED' || task.status === 'FAILED') {
      clearInterval(interval);
      showResults(task);
    }
  }, 2000);
};
```

**Python (自动化脚本)**：
```python
import requests
import time

class ForensicClient:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url

    def create_task(self, image_path, analysis_type="full"):
        """创建分析任务"""
        response = requests.post(f"{self.base_url}/api/tasks", json={
            "image_path": image_path,
            "analysis_type": analysis_type,
            "priority": "NORMAL"
        })
        return response.json()["task_id"]

    def wait_for_completion(self, task_id, check_interval=30):
        """等待任务完成"""
        while True:
            response = requests.get(f"{self.base_url}/api/tasks/{task_id}")
            task = response.json()

            if task["status"] == "COMPLETED":
                return True
            elif task["status"] == "FAILED":
                raise Exception(f"Task failed: {task['error']}")

            print(f"Progress: {task['progress']}% - {task['current_phase']}")
            time.sleep(check_interval)

    def get_timeline(self, task_id):
        """获取时间线"""
        response = requests.get(f"{self.base_url}/api/timeline",
                               params={"task_id": task_id})
        return response.json()

    def export_results(self, task_id, format="toon"):
        """导出结果"""
        response = requests.get(f"{self.base_url}/api/tasks/{task_id}/export",
                               params={"format": format})
        return response.content

# 使用示例
client = ForensicClient()
task_id = client.create_task("/evidence/suspect.dd")
client.wait_for_completion(task_id)
timeline = client.get_timeline(task_id)
print(f"Found {len(timeline)} events")
```

---

## 6. 常见问题 (FAQ)

**Q1:服务支持多少并发连接？如何提高并发能力？**

A:默认配置下，服务支持约500-1000个并发连接。

**提升并发能力的方法**：
1. 增加工作线程数：`--threads 16`（默认为CPU核心数）
2. 调整最大连接数：`config.maxConnections = 5000`
3. 使用反向代理做负载均衡（部署多实例）
4. 优化数据库连接池，减少数据库锁等待

**性能参考**：
- 单实例，8线程：约300 QPS（简单查询）
- 单实例，16线程：约500 QPS
- 3实例集群，16线程：约1500 QPS

---

**Q2:长时间运行的分析任务会阻塞其他请求吗？**

A:不会。所有分析任务在独立线程中异步执行，不会阻塞API响应。

**工作原理**：
- API请求由I/O线程快速处理，立即返回task_id
- 分析任务交给工作线程池执行
- 客户端通过轮询`GET /api/tasks/{id}`获取进度
- 多个任务可并发执行（由`maxConcurrentTasks`限制）

**示例时间线**：
```
0s   客户端: POST /api/tasks → 立即返回 {"task_id": "123", "status": "PENDING"}
1s   服务端: 开始执行任务，状态变为 RUNNING
30s  客户端: GET /api/tasks/123 → {"progress": 25%, "phase": "IMAGE_ANALYSIS"}
60s  客户端: GET /api/tasks/123 → {"progress": 50%, "phase": "EVENT_EXTRACTION"}
...
```

---

**Q3:如何保护API安全？防止未授权访问？**

A:建议在生产环境实施以下安全措施：

**1. 身份认证**：
```cpp
// JWT认证中间件（需自行实现）
bool authenticateRequest(const crow::request& req) {
    std::string token = req.get_header_value("Authorization");
    return verifyJWT(token);  // 验证JWT令牌
}
```

**2. HTTPS加密**：使用Nginx反向代理配置SSL
**3. 速率限制**：防止API滥用和DDoS攻击
**4. IP白名单**：仅允许特定IP访问
**5. 审计日志**：记录所有API请求，便于安全审计

**Nginx配置示例**：
```nginx
# 速率限制
limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

location /api/ {
    limit_req zone=api burst=20;
    allow 192.168.1.0/24;  # IP白名单
    deny all;

    # 只允许HTTPS
    if ($scheme != "https") {
        return 301 https://$host$request_uri;
    }
}
```

---

**Q4:任务执行失败如何排查？**

A:任务失败可能有多种原因，以下是排查步骤：

**1. 查看任务详情**：
```bash
GET /api/tasks/123
# 响应包含错误信息
{
  "status": "FAILED",
  "error": "File not found: /path/to/image.dd",
  "error_code": "FILE_NOT_FOUND",
  "failed_at": "2024-01-19T10:30:00Z"
}
```

**2. 检查服务器日志**：
```bash
tail -f /var/log/forensic/error.log
# 查看详细错误堆栈
```

**3. 常见错误原因**：
- **FILE_NOT_FOUND**：镜像文件路径错误或权限不足
- **UNSUPPORTED_FORMAT**：不支持的镜像格式
- **DATABASE_ERROR**：数据库损坏或权限问题
- **OUT_OF_MEMORY**：系统内存不足
- **TIMEOUT**：任务超时（可增加超时时间）

**4. 处理建议**：
- 检查文件路径和权限：`ls -l /path/to/image.dd`
- 检查磁盘空间：`df -h`
- 检查内存使用：`free -h`
- 增加任务超时时间
- 查看详细日志定位具体问题

---

**Q5:能否自定义API端点？如何扩展功能？**

A:可以。模块化路由设计使得添加新端点非常简单。

**步骤**：
1. 在对应的Routes文件中添加处理函数
   ```cpp
   // routes/ForensicsRoutes.cpp
   crow::response customEndpoint(const crow::request& req) {
       auto param = req.url_params.get("param");
       // 业务逻辑
       return crow::response(200, "Result");
   }
   ```

2. 在`HTTPServer::run()`中注册路由
   ```cpp
   CROW_ROUTE(app, "/api/custom").methods("GET"_method)
       (&ForensicsRoutes::customEndpoint, this);
   ```

3. 重新编译并部署
   ```bash
   cmake --build . && systemctl restart forensic-server
   ```

**最佳实践**：
- 遵循RESTful设计原则
- 使用语义化的URL（`/api/files/{id}`而非`/api/get_file`）
- 提供OpenAPI文档
- 编写单元测试
- 添加错误处理和日志

---

**技术支持：**
- API参考：https://api.forensics-project.com/swagger
