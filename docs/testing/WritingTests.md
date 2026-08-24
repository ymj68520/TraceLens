# 如何为 TraceLens 写测试

> 面向贡献者：给新功能补测试时的接入点、约定与范例。三个栈（C++/Python/前端）各一节，最后是验收旅程扩展。现有测试全景见 [CppTestCatalog](CppTestCatalog.md) / [PythonTestCatalog](PythonTestCatalog.md) / [web/Testing](../modules/web/Testing.md)。

## 1. C++（GTest + CTest）

### 接入步骤（以给某分析器加测试为例）
1. 在 `tests/UnitTest/` 新建 `test_<模块>_gtest.cpp`，套用现成模板（推荐抄 `test_thread_pool.cpp` 或同域测试——结构与命名最贴近）：
```cpp
#include <gtest/gtest.h>
#include "<模块头文件>.h"

namespace { class <Module>Tests : public ::testing::Test {
protected:
    void SetUp() override { /* 每用例准备：临时目录/小 fixture */ }
    void TearDown() override { /* 清理 */ }
}; }

TEST_F(<Module>Tests, BasicBehavior) {
    // 用最小 fixture 断言可观察行为（落库结果/返回值），不断言内部日志
}
```
2. 在 `tests/CMakeLists.txt` 注册（跟随现有目标的写法）：
```cmake
add_executable(test_<模块>_gtest UnitTest/test_<模块>_gtest.cpp ${LIB_SOURCES})
target_include_directories(test_<模块>_gtest PRIVATE ${CMAKE_SOURCE_DIR}/src)
target_link_libraries(test_<模块>_gtest ${GTEST_LIBRARIES} ...)
add_test(NAME <Module>Tests COMMAND test_<模块>_gtest)
```
3. 跑：`cd build && cmake --build . --target test_<模块>_gtest && ctest -R <Module>Tests`。

### 约定与注意
- **命名**：目标 `test_<模块>_gtest`、测试名 `<Module>Tests`（`ctest -R` 直接可用）。
- **依赖外部工具的目标**（SQLCipher、LLM 端点、本机 mysql）在 CMakeLists 里有 `find_package/if` 守卫——参考 WeChat/SQLCipher 目标的条件注册，并在目标旁注释依赖。
- **fixture 纪律**：测试数据放 `tests/`（见 [TestFixtures](TestFixtures.md) 的分布）；生成型 fixture 优先用仓库内脚本而不是硬编码绝对路径（历史教训：`create_pe_sample.py` 因硬编码旧路径已断）。
- **不要学**：独立 main（如 `llm_files_test.cpp`）脱离 ctest、失败不可感知——新测试一律走 add_test。

## 2. Python（pytest）

### 选择落点
| 测什么 | 放哪 | 范例 |
|--------|------|------|
| httpserver 路由契约 | `python_service/tests/unit/test_<域>_*.py` | test_dll_route.py |
| 调查/报告/evidence 域 | `tests/unit/<子包>/` | investigation/ 26 个文件 |
| server（C/S）应用 | `python_service/tests/` 顶层 | test_auth_*.py |
| graphiti_integration 包 | `graphiti_integration/tests/`（**不在 testpaths，单独跑**） | test_toon_transformer.py |

### 约定
- `pytest.ini`：`asyncio_mode = auto`（async 测试函数不用装 marker）；六标记（integration/unit/slow/concurrency/migration_matrix）用 `--strict-markers` 校验——新标记必须登记。
- **依赖真实外部服务的测试标 `integration`**（Neo4j/PG）；PG fixture 测试读 `TEST_DATABASE_URL`（conftest 自建引擎，不跑 SQL 迁移）。
- **异步属性测试**（ServiceManager 的 property/wiring 类）已有稳定模式，抄 `test_startup_reliability.py` 的写法（还断言"LLM 客户端初始化不发网络请求"这类边界）。
- **档案联动**：新测试若该进 fast 档（默认 CI 面），确认不带 slow/concurrency 标记——`scripts/test.py fast` = tests/unit 减三标记。
- 别把测试写成隐式写仓库：需要数据集时用 fixture 显式准备（反面案例：test_wechat_dataset.py 缺 fixture 会自动跑生成脚本）。

### 双应用注意
顶层测试 import `server.app` 系列、unit 测试 import `httpserver` 系列——同一 venv、不同前缀；写测试时别串（server 的 TestClient 用 `from starlette.testclient`，httpserver 的路由测试多用依赖注入替身）。

## 3. 前端（Vitest + RTL）

- 新测试与组件同目录（`*.test.jsx`）；环境是 jsdom + globals（`vite.config.js` test 块）。
- 三类既有模式直接抄：
  1. **service 层 axios mock**（`src/services/*.test.js`）：mock 模块工厂、断言 URL/方法/参数形状；
  2. **hooks 轮询测试**（`src/hooks/*.test.js`）：fake timers + 身份切换断言"晚到的旧响应被丢弃"（这是 D4b 行为的回归线）；
  3. **页面渲染**：`renderWithRouter`（`src/test/renderWithRouter.jsx`）包 MemoryRouter，必要时注入 Redux store 或 FixtureReportDataSource（离线数据源）。
- 断言用 testid 协议（CaseIntelligence 的既有约定）而不是脆弱的样式选择器。

## 4. 验收旅程扩展（live_services.py）

给真实链路加旅程的入口（详见 [AcceptanceHarness](AcceptanceHarness.md)）：
1. 新旅程做成独立 profile 或并入现有（task=Journey A、analyst=Journey B）；
2. 遵守隔离契约：临时工作区、自写 .env、断言只打工作区内路径；
3. 依赖 LLM 的步骤走 fake provider 的 prompt 路由表（新增响应形态时同步加）；
4. 终态断言前保留"句柄释放窗口"（现有 3 秒规则的由来）；
5. 跑法：`python3 scripts/acceptance/live_services.py --profile <p> --keep-on-failure`。

## 5. 什么时候必须补测试（约定）

- 动了 D2b/D4b 边界（路径解析/删除后写保护/资源关闭）→ 必须带回归测试（历史先例：c1ebf49"align regression fakes with lifecycle boundaries"）。
- 新增/修改 HTTP 契约（字段名/状态码）→ 路由契约测试 + 若前端受影响则前端 service 测试。
- 新分析器 → 至少一个 GTest（小 fixture 落库断言）+ 按需 e2e 脚本（参考 test_miui_backup_e2e.sh 的形态，但路径要修——见 CppTestCatalog 的"脚本路径漂移"坑）。

---

**最后更新**: 2026-08-24（新建：测试编写指南）
