# 取证场景选择系统 (Forensic Scenario Selection)

## 概述

取证场景选择系统允许用户在创建分析任务时选择一个或多个平台取证场景（Android、Windows、Linux、服务器/云），后端自动运行对应的特化分析器，生成独立的分析数据库。

## 功能特性

- **多场景选择**：支持 Android、Windows、Linux、服务器/云四种取证场景
- **多选支持**：单个任务可同时选择多个场景（如 Android + Windows）
- **独立数据库**：每个场景生成独立的分析数据库文件
- **向后兼容**：兼容旧版 `android_analyze` 布尔标志
- **统一管线**：核心分析流程只运行一次，场景特化分析在其后按序执行

## 架构设计

### 数据模型

```cpp
enum class ForensicScenario {
    ANDROID,        // Android 设备取证
    WINDOWS,        // Windows 系统取证
    LINUX,          // Linux 系统取证
    SERVER_CLOUD    // 服务器/云环境取证
};
```

`AnalysisTask` 结构体使用 `std::vector<ForensicScenario> scenarios` 替代原有的 `bool android_analyze`。

### 管线执行流程

```
图像分析 → 事件提取 → 文件分类 → LLM 分析
                                        ↓
                            ┌───────────────────────┐
                            │  PLATFORM_ANALYSIS    │
                            │                       │
                            │  1. Android (如选中)   │
                            │     → _android.db     │
                            │                       │
                            │  2. Windows (如选中)   │
                            │     → _windows.db     │
                            │                       │
                            │  3. Linux (如选中)     │
                            │     → _linux.db       │
                            │                       │
                            │  4. 服务器/云 (如选中) │
                            │     → _server.db      │
                            └───────────────────────┘
                                        ↓
                                知识图谱入库
```

核心管线（步骤 1-5）只运行一次，所有场景共享同一份 `_raw.db`、`_events.db`、`_files.db`。平台特化分析（步骤 6）按场景顺序依次运行，每个场景写入独立数据库。

### 数据库路径

| 场景 | 数据库路径 |
|------|-----------|
| Android | `{task_dir}/android.db` |
| Windows | `{task_dir}/windows.db` |
| Linux | `{task_dir}/linux.db` |
| 服务器/云 | `{task_dir}/oss.db` |

## API 变更

### 创建任务请求

`POST /api/tasks`

```json
{
  "image_path": "/path/to/image.dd",
  "priority": "normal",
  "case_description": "案情描述",
  "scenarios": ["android", "windows"],
  "filter_profile": "telecom_fraud",
  "xfs_mode": "auto",
  "llm_analyze": true,
  "llm_mode": "smart"
}
```

**向后兼容**：如果请求中没有 `scenarios` 但有 `android_analyze: true`，系统自动转换为 `scenarios: ["android"]`。

### 任务响应

```json
{
  "id": "task-uuid",
  "scenarios": ["android", "windows"],
  "scenario_databases": {
    "android": "/path/to/android.db",
    "windows": "/path/to/windows.db"
  },
  "android_analyze": true,
  "status": "created"
}
```

### 任务详情响应

`GET /api/tasks/{id}`

响应中包含 `scenarios` 数组、`scenario_databases` 映射和向后兼容的 `android_analyze` 布尔值。

## 前端 UI

创建任务表单中，原来的单个 "启用深度 Android 分析" 复选框替换为场景多选组：

- 📱 **Android** — SMS、联系人、通话记录、应用数据
- 🪟 **Windows** — 注册表、事件日志、Prefetch、浏览器历史
- 🐧 **Linux** — 系统日志、用户账户、Shell 历史、SSH
- ☁️ **服务器/云** — Docker、Nginx/Apache、K8s、云配置

用户可通过复选框选择一个或多个场景。

## 场景分析器

### Android 分析器

类：`AndroidAnalyzer`

分析内容：
- SMS/MMS 短信
- 联系人信息
- 通话记录
- 应用使用统计
- 设备信息
- 媒体文件分析

### Windows 分析器

类：`WindowsFilesAnalyzer`

分析内容：
- 注册表配置单元（SAM、SYSTEM、SOFTWARE、NTUSER.DAT）
- 事件日志（.evtx）
- Prefetch 文件
- 快捷方式（.lnk）
- 跳转列表
- 回收站
- NTFS 元数据（MFT）
- 浏览器历史
- 用户配置文件

### Linux 分析器

类：`LinuxFilesAnalyzer`

分析内容：
- 系统日志（syslog、messages）
- 认证日志（auth.log、secure）
- 用户账户（/etc/passwd、shadow）
- Shell 历史（bash、zsh）
- SSH 密钥和配置
- 定时任务（cron）
- systemd 服务
- 网络配置
- 防火墙规则
- 审计日志

### 服务器/云分析器

类：`LinuxFilesAnalyzer`（扩展）

基于 Linux 分析器，增加以下分析：

- Docker 容器、镜像、卷
- Podman 容器
- Apache/Nginx 服务器配置
- Kubernetes 配置（configmaps、secrets）
- 云实例元数据（cloud-init）
- 容器编排配置（Docker Compose）
- CI/CD 管道配置（Jenkins、GitLab CI、GitHub Actions）

入口方法：`analyzeServerCloudArtifacts()`

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/network/HTTPServer/HTTPServerDataTypes.h` | 修改 | 新增 ForensicScenario 枚举，修改 AnalysisTask 和 TaskPhase |
| `src/network/HTTPServer/TaskSerialization.cpp` | 修改 | 序列化/反序列化 scenarios，向后兼容 |
| `src/network/HTTPServer/TaskManager.cpp` | 修改 | 管线重构，统一 PLATFORM_ANALYSIS 阶段 |
| `src/network/HTTPServer/TaskManager.h` | 修改 | 更新 create_task 签名，新增 set_scenarios |
| `src/network/HTTPServer/routes/TaskCRUDRoutes.cpp` | 修改 | API 解析 scenarios 数组 |
| `src/network/HTTPServer/routes/TaskHelpers.cpp` | 修改 | API 响应输出 scenarios 和 scenario_databases |
| `web/src/components/tasks/CreateTaskModal.jsx` | 修改 | 场景多选 UI |
| `src/analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h` | 修改 | 新增服务器/云分析方法声明 |
| `src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp` | 修改 | 实现服务器/云分析方法 |
| `tests/UnitTest/test_task_scenarios_gtest.cpp` | 新增 | 10 个单元测试 |
| `tests/CMakeLists.txt` | 修改 | 注册新测试 |

## 测试

### 单元测试

测试文件：`tests/UnitTest/test_task_scenarios_gtest.cpp`

测试覆盖：
- `ForensicScenario` 枚举字符串转换
- nlohmann::json 序列化/反序列化往返
- `AnalysisTask` 的 `to_json`/`from_json`
- 向后兼容：`android_analyze: true` → `scenarios: [ANDROID]`
- 空场景处理
- 拷贝构造保留 scenarios
- `get_android_analyze()` 计算属性

运行测试：
```bash
cd build
ctest -R TaskScenarioTests --output-on-failure
```

### 集成测试

API 测试：
```bash
# 创建多场景任务
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"image_path":"/tmp/test.dd","scenarios":["android","linux"],"llm_analyze":true}'

# 向后兼容测试
curl -X POST http://localhost:8080/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"image_path":"/tmp/test.dd","android_analyze":true}'
```

## 向后兼容性

### 旧版任务 JSON

旧版任务 JSON 文件中只有 `android_analyze: true`，没有 `scenarios` 字段。反序列化逻辑自动处理：

```cpp
if (j.contains("scenarios")) {
    j.at("scenarios").get_to(t.scenarios);
} else if (j.contains("android_analyze") && j["android_analyze"].get<bool>()) {
    t.scenarios = {ForensicScenario::ANDROID};
}
```

### 旧版 API 请求

旧版 API 请求中的 `android_analyze: true` 自动转换：

```cpp
if (!body.contains("scenarios") && body.value("android_analyze", false)) {
    scenarios = {ForensicScenario::ANDROID};
}
```

### 旧版 API 响应

响应中同时包含新版 `scenarios` 数组和旧版 `android_analyze` 布尔值：

```json
{
  "scenarios": ["android"],
  "android_analyze": true
}
```

## 扩展指南

### 添加新场景

1. 在 `ForensicScenario` 枚举中添加新值
2. 在 `scenario_to_string()` 和 `string_to_scenario()` 中添加映射
3. 在 `TaskSerialization.cpp` 的 `NLOHMANN_JSON_SERIALIZE_ENUM` 中添加映射
4. 在 `TaskManager.cpp` 的 PLATFORM_ANALYSIS switch 中添加 case
5. 在 `CreateTaskModal.jsx` 的场景列表中添加 UI 选项
6. 在 `TaskHelpers.cpp` 的 `scenario_databases` switch 中添加 case
7. 编写对应的分析器类
8. 添加单元测试

### 分析器接口约定

每个场景分析器应遵循以下模式：

```cpp
// 1. 创建 DatabaseManager
auto dbManager = std::make_unique<DatabaseManager>(rawDbPath);

// 2. 创建分析器
auto analyzer = std::make_unique<PlatformAnalyzer>(imagePath, dbManager.get());

// 3. 设置输出数据库路径
analyzer->setOutputDatabasePath(outputDbPath);

// 4. 初始化
if (analyzer->initialize()) {
    // 5. 运行分析
    analyzer->analyzePlatformData();
}
```
