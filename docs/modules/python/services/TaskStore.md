# TaskStore（python_service/httpserver/services/task_store.py）

> **一句话**：HTTP 任务模式下的"任务归属路径/数据库解析"安全基石（Phase D2b）——`cpp_backend.get_task` 返回的任务记录是数据库与目录归属的唯一权威，客户端路径字段至多做**精确相等**校验（fail-closed，绝不"就近匹配"），工作区包含性检查是组件感知的 `Path.relative_to` 而非字符串前缀。

## 1. 为什么有这个模块

D2b 之前，多个转换/分析端点接受客户端提交的 `files_db_path`、输入/输出目录等字段并直接使用。这类字段一旦被用来"选择写目标"，就可能把 LLM 结果写进错误的库（历史上发生过静默写 `build/test_image_files.db` 之类的事故），或让请求触达任务工作区之外的任意路径。task_store 用一个约 190 行的Facade 把规则定死：

- 任务记录（`output_files_db` 等）是**唯一**权威；
- 客户端路径出现时只能做精确校验，不匹配即 400；
- 所有包含性判断先 resolve 再 `relative_to`，杜绝 `/t/a` 冒充 `/t/abc` 的兄弟前缀绕过；
- 读 files 表做成员校验时用只读 URI，库打不开是"存储不可用"而不是"文件不存在"。

模块头注释明确它复用了 `investigation/paths.py` 的纪律（task_store.py:10-24），且"不是 repository"：无缓存、无写入。

## 2. 在系统中的位置

- **谁调用它**（六个路由模块，均在请求入口处）：routes/markitdown.py（转换批/单文件/工作区解析，:59/:83/:117/:404/:549 五处）、routes/office.py（任务记录→工作区与库，:61-98）、routes/dll.py（DLL 分析的信任库解析与 legacy 路径校验，:145-160）、routes/multi_analysis.py（跨镜像每任务校验，:238-246）、routes/case_analysis_endpoints/_case.py（案情分析入口，:131-143）、routes/llm_endpoints/_analysis.py（LLM 分析入口，:288-299）。
- **它调用谁**：ServiceManager.cpp_backend（`get_task`）；SQLite（只读 URI 查 files.path）。
- **它被谁依赖**：本质上是 markitdown 转换、office 解析、LLM 持久化等所有"以任务为边界写文件/读库"的路由的门卫；GraphitiService 文档中的 fail-closed 持久化与它共享同一信任模型（C++ 任务记录）。

## 3. 核心概念与设计

**（a）稳定错误码。** 五个机器码（:34-38）：`task_not_found`、`task_store_unavailable`、`path_mismatch`、`path_outside_workspace`、`input_output_overlap`，全部经 `TaskStoreError(code, message)` 抛出（:41-46），路由按 code 映射 404/400/503——错误处理因此可测试且不泄内部细节。

**（b）信任解析三件套。** `get_task_record`（:55-63）空 ID 或 get_task 落空即 `task_not_found`；`files_db_from_record`（:72-78）只认 `output_files_db`/`output_files_db_path`，缺失即 `task_store_unavailable`；`workspace_from_record`（:87-101）取 files/events/raw 三个库路径的父目录，**必须一致**，不一致同样是 unavailable——宁可失败也不猜哪个是真的。

**（c）精确校验与组件感知包含。** `validate_legacy_db_path`（:104-119）是给"还带着废弃 files_db_path 字段的旧客户端"的窄门：两侧 `resolve(strict=False)` 后逐字节比较，任何偏差 `path_mismatch`：

```python
resolved_supplied = Path(str(supplied_path)).resolve(strict=False)
resolved_trusted = Path(str(trusted_path)).resolve(strict=False)
if resolved_supplied != resolved_trusted:
    raise TaskStoreError(PATH_MISMATCH, ...)
```

没有 basename/后缀/父目录/大小写兜底。`resolved_within`（:122-137）同样先 resolve 再 `relative_to`，防 `..` 与兄弟前缀。`has_symlink_component`（:140-155）特意在 **resolve 之前**逐组件查符号链接——先 resolve 会抹掉链接边界，让一个"看似在根内"的路径绕过转换路由的无符号链接契约。

**（d）只读成员校验与内部提取根。** `file_known_to_task`（:163-191）以 `mode=ro` URI 精确查 `files.path`：打不开库抛 `TASK_STORE_UNAVAILABLE`（503 语义），只有"库可读且无此行"才返回 False（404 语义）——分析员永远不该因为库损坏而看到"文件不存在"。`internal_extract_root`（:158-160）返回 `<tempdir>/forensics_llm_extract`，镜像 C++ `LLMAnalysisService::resolveFileForAnalysis` 的暂存目录，是两进程共享的"已提取文件"读锚点（office 路由用它豁免"必须在 files 表里"的检查）。

## 4. 工作流程走读：一次 markitdown 转换的入口校验

`POST /api/markitdown/convert-one`（routes/markitdown.py:399+）→ `task_store.get_task_record` + `workspace_from_record`（workspace_root 传入时也做精确校验）→ `has_symlink_component` 对 input_root/input_file/output_root 三查（:404-408）→ `resolved_within(workspace, ...)` 逐个收窄 → 提取器转换 → 输出镜像写在 output_root 之下。任何一步的 TaskStoreError 都被翻译成 400/404，而**不会有任何路径被"修正"后继续执行**。

## 5. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| CppBackendService | get_task 唯一信任源（与 investigation/paths、ingestion worker 同源） |
| routes/markitdown、office、dll、multi_analysis、case_analysis_endpoints、llm_endpoints | 六个入口的强制门卫 |
| LLMService.persist_to_files_db | 下游共享同一 fail-closed 哲学：绝不回退写别的库 |
| investigation/paths.py | 纪律出处（trusted-parents-must-agree 同款实现） |

## 6. 注意事项与已知问题

- `workspace_from_record` 只看三个 output_* 键；任务只有非常规库名时（例如只有 `_raw.db` 缺失另两个）仍可工作，但**全部缺失**即失败——这是故意的。
- `validate_legacy_db_path` 用 `resolve(strict=False)`：若客户端路径与信任路径仅符号链接差异，resolve 后可能意外相等——转换类路由因此叠加了 `has_symlink_component` 检查，新增路由时要记得同样叠加，别只依赖精确校验。
- 本模块不做缓存：每次请求都打一次 C++ get_task。高频端点若成瓶颈，缓存必须以"任务记录不可变"为前提论证，不能默认。
- `input_output_overlap` 错误码已定义但当前模块内没有使用点（防重叠的检查在 markitdown 路由层做）。

## 7. 如何验证（python_service/tests/unit/）

- `test_d2b_task_store.py`（精确校验/包含性/符号链接/错误码）、`test_d2b_db_ownership.py`（端到端归属：错误目标绝不写入）、`test_d2b_office_routes.py`、`test_d2b_standalone_contracts.py`、`test_markitdown_routes.py`（转换入口全链路门卫）。
- 手工验证：对同一任务 POST 一个 `files_db_path` 差一个字符的请求应得 400 `path_mismatch`；`GET` 一个不存在任务的任何受保护资源应得 404 而非 500。

**最后更新**: 2026-08-23（新建，解释式）
