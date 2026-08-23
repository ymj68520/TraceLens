# TaskStore（python_service/httpserver/services/task_store.py）

> **一句话**：HTTP 任务模式下的"任务归属路径/数据库解析"安全基石（Phase D2b）——`cpp_backend.get_task` 返回的任务记录是数据库与目录归属的唯一权威，客户端路径字段至多做**精确相等**校验（fail-closed，绝不"就近匹配"），工作区包含性检查是组件感知的 `Path.relative_to` 而非字符串前缀。

## 1. 为什么有这个模块

D2b 之前，多个转换/分析端点接受客户端提交的 `files_db_path`、输入/输出目录等字段并直接使用。这类字段一旦被用来"选择写目标"，就可能把 LLM 结果写进错误的库（历史上发生过静默写 `build/test_image_files.db` 之类的事故），或让请求触达任务工作区之外的任意路径。task_store 用一个约 190 行的 Facade 把规则定死：

- 任务记录（`output_files_db` 等）是**唯一**权威；
- 客户端路径出现时只能做精确校验，不匹配即 400；
- 所有包含性判断先 resolve 再 `relative_to`，杜绝 `/t/a` 冒充 `/t/abc` 的兄弟前缀绕过；
- 读 files 表做成员校验时用只读 URI，库打不开是"存储不可用"而不是"文件不存在"。

模块头注释明确它复用了 `investigation/paths.py` 的纪律（task_store.py:10-24），且"不是 repository"：无缓存、无写入。

## 2. 在系统中的位置

- **谁调用它**（六个路由模块，均在请求入口处）：routes/markitdown.py（转换批/单文件/工作区解析，:59/:83/:117/:404/:549 五处）、routes/office.py（任务记录→工作区与库，:61-98）、routes/dll.py（DLL 分析的信任库解析与 legacy 路径校验，:145-160）、routes/multi_analysis.py（跨镜像每任务校验，:238-246）、routes/case_analysis_endpoints/_case.py（案情分析入口，:131-143）、routes/llm_endpoints/_analysis.py（LLM 分析入口，:288-299）。
- **它调用谁**：ServiceManager.cpp_backend（`get_task`）；SQLite（只读 URI 查 files.path）。
- **它被谁依赖**：本质上是 markitdown 转换、office 解析、LLM 持久化等所有"以任务为边界写文件/读库"的路由的门卫；GraphitiService 文档中的 fail-closed 持久化与它共享同一信任模型（C++ 任务记录）。

## 3. 核心数据结构：错误码枚举与异常

```python
# task_store.py:34-46
TASK_NOT_FOUND = "task_not_found"
TASK_STORE_UNAVAILABLE = "task_store_unavailable"
PATH_MISMATCH = "path_mismatch"
PATH_OUTSIDE_WORKSPACE = "path_outside_workspace"
INPUT_OUTPUT_OVERLAP = "input_output_overlap"


class TaskStoreError(Exception):
    """Typed task-store resolution failure (``code`` is a stable machine code)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
```

五个机器码是模块的全部失败词汇表，语义与路由映射：

| code | 语义 | 路由典型映射 |
|---|---|---|
| `task_not_found` | 空 ID 或 get_task 落空 | 404 |
| `task_store_unavailable` | 任务记录缺库路径 / 三库父目录不一致 / files.db 打不开 | 503（"存储坏了"绝不冒充"没有"） |
| `path_mismatch` | 客户端路径与信任路径精确比较失败 | 400 |
| `path_outside_workspace` | resolved_within 包含性失败 | 400 |
| `input_output_overlap` | 预留（当前模块内无使用点，防重叠检查在 markitdown 路由层做） | — |

`TaskStoreError(code, message)` 把机器码挂在 `.code` 上，路由按 code 分流而不是解析 message 文本——错误处理因此可测试且不泄内部细节。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `async get_task_record(task_id: str) -> dict` | 信任的任务记录 | 六路由入口 | task_not_found |
| `async resolve_task_files_db(task_id: str) -> Path` | 任务归属 `_files.db`（唯一持久化目标） | LLM/案情分析入口 | task_not_found / unavailable |
| `files_db_from_record(task: dict) -> Path` | 记录 → files.db 路径 | 上述两步的第二段 | 缺 output_files_db* 即 unavailable |
| `async resolve_task_workspace(task_id) -> Path` / `workspace_from_record(task)` | 三库父目录一致才返回工作区根 | markitdown/office | 不一致 unavailable |
| `validate_legacy_db_path(supplied_path, trusted_path) -> None` | 废弃字段的精确校验 | 带 files_db_path 的旧客户端 | path_mismatch |
| `resolved_within(root, candidate) -> Path` | 组件感知包含性 | markitdown 输出收窄 | path_outside_workspace |
| `has_symlink_component(path) -> bool` | resolve 前逐组件查符号链接 | markitdown 三查 | 布尔，调用方决定 400 |
| `internal_extract_root() -> Path` | `<tempdir>/forensics_llm_extract` | office 路由豁免检查 | 不失败 |
| `file_known_to_task(files_db, file_path: str) -> bool` | 只读成员校验 | 文件级端点 | 库不可用抛 unavailable |

## 5. 核心概念与设计

**（a）信任解析三件套。** `get_task_record`（:55-63）空 ID 或 get_task 落空即 `task_not_found`；`files_db_from_record`（:72-78）只认 `output_files_db`/`output_files_db_path`，缺失即 `task_store_unavailable`；`workspace_from_record`（:87-101）取 files/events/raw 三个库路径的父目录，**必须一致**：

```python
# task_store.py:87-101
def workspace_from_record(task: dict) -> Path:
    parents = []
    for key in ("output_files_db", "output_events_db", "output_raw_db"):
        value = task.get(key)
        if value:
            parents.append(Path(str(value)).resolve(strict=False).parent)
    if not parents:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task has no trusted database path"
        )
    if len(set(parents)) != 1:
        raise TaskStoreError(
            TASK_STORE_UNAVAILABLE, "task database directories are inconsistent"
        )
    return parents[0]
```

`set(parents)` 长度不等于 1 即拒绝——宁可失败也不猜哪个是真的（与 investigation/paths.py 的 trusted-parents-must-agree 同款）。

**（b）精确校验与组件感知包含。** `validate_legacy_db_path`（:104-119）是给"还带着废弃 files_db_path 字段的旧客户端"的窄门：

```python
resolved_supplied = Path(str(supplied_path)).resolve(strict=False)
resolved_trusted = Path(str(trusted_path)).resolve(strict=False)
if resolved_supplied != resolved_trusted:
    raise TaskStoreError(PATH_MISMATCH, ...)
```

没有 basename/后缀/父目录/大小写兜底。`resolved_within`（:122-137）同样先 resolve 再 `relative_to`，防 `..` 与兄弟前缀。`has_symlink_component`（:140-155）特意在 **resolve 之前**逐组件查符号链接——先 resolve 会抹掉链接边界，让一个"看似在根内"的路径绕过转换路由的无符号链接契约：

```python
# task_store.py:147-155（节选）
candidate = Path(str(path))
if not candidate.is_absolute():
    candidate = Path.cwd() / candidate
current = Path(candidate.anchor)
for component in candidate.parts[1:]:
    current = current / component
    if current.is_symlink():
        return True
return False
```

**（c）只读成员校验与内部提取根。** `file_known_to_task`（:163-191）以 `mode=ro` URI 精确查 `files.path`：

```python
# task_store.py:169-189（节选）
candidate = Path(str(files_db))
if not candidate.is_file():
    raise TaskStoreError(
        TASK_STORE_UNAVAILABLE, "task files database is unavailable"
    )
uri = f"file:{quote(str(candidate.resolve()), safe='/')}?mode=ro"
try:
    conn = sqlite3.connect(uri, uri=True, timeout=10)
except sqlite3.Error as exc:
    raise TaskStoreError(
        TASK_STORE_UNAVAILABLE, "task files database is unavailable"
    ) from exc
try:
    cur = conn.execute(
        "SELECT 1 FROM files WHERE path = ? LIMIT 1", (file_path,)
    )
    return cur.fetchone() is not None
except sqlite3.Error as exc:
    raise TaskStoreError(
        TASK_STORE_UNAVAILABLE, "task files database is unavailable"
    ) from exc
finally:
    conn.close()
```

三层都是 `TASK_STORE_UNAVAILABLE`（503 语义）：文件不在、连不上、查询失败；只有"库可读且无此行"才返回 False（404 语义）——分析员永远不该因为库损坏而看到"文件不存在"。查询本身是精确 `path = ?` 等值匹配，与 LLMService.persist_to_files_db 的 WHERE 条件同构（身份口径一致）。`internal_extract_root`（:158-160）返回 `<tempdir>/forensics_llm_extract`，镜像 C++ `LLMAnalysisService::resolveFileForAnalysis` 的暂存目录，是两进程共享的"已提取文件"读锚点（office 路由用它豁免"必须在 files 表里"的检查）。

## 6. 工作流程走读：一次 markitdown 转换的入口校验

`POST /api/markitdown/convert-one`（routes/markitdown.py:399+）→ `task_store.get_task_record` + `workspace_from_record`（workspace_root 传入时也做精确校验）→ `has_symlink_component` 对 input_root/input_file/output_root 三查（:404-408）→ `resolved_within(workspace, ...)` 逐个收窄 → 提取器转换 → 输出镜像写在 output_root 之下。任何一步的 TaskStoreError 都被翻译成 400/404，而**不会有任何路径被"修正"后继续执行**。

## 7. 与其他模块的协作

| 模块 | 协作方式 |
|---|---|
| CppBackendService | get_task 唯一信任源（与 investigation/paths、ingestion worker 同源） |
| routes/markitdown、office、dll、multi_analysis、case_analysis_endpoints、llm_endpoints | 六个入口的强制门卫 |
| LLMService.persist_to_files_db | 下游共享同一 fail-closed 哲学：绝不回退写别的库 |
| investigation/paths.py | 纪律出处（trusted-parents-must-agree 同款实现） |

## 8. 注意事项与已知问题

- `workspace_from_record` 只看三个 output_* 键；任务只有非常规库名时（例如只有 `_raw.db` 缺失另两个）仍可工作，但**全部缺失**即失败——这是故意的。
- `validate_legacy_db_path` 用 `resolve(strict=False)`：若客户端路径与信任路径仅符号链接差异，resolve 后可能意外相等——转换类路由因此叠加了 `has_symlink_component` 检查，新增路由时要记得同样叠加，别只依赖精确校验。
- 本模块不做缓存：每次请求都打一次 C++ get_task。高频端点若成瓶颈，缓存必须以"任务记录不可变"为前提论证，不能默认。
- `input_output_overlap` 错误码已定义但当前模块内没有使用点（防重叠的检查在 markitdown 路由层做）。
- 并发语义：get_task 每次实查意味着任务被删除后，**在途请求**的下一跳校验会立刻 task_not_found（不会用到陈旧缓存）；同一请求内"先校验后写入"之间任务被删的窗口由下游（LLM 持久化 fail-closed、D4b 边界）各自兜住。

## 9. 如何验证（python_service/tests/unit/）

- `test_d2b_task_store.py`（精确校验/包含性/符号链接/错误码）、`test_d2b_db_ownership.py`（端到端归属：错误目标绝不写入）、`test_d2b_office_routes.py`、`test_d2b_standalone_contracts.py`、`test_markitdown_routes.py`（转换入口全链路门卫）。
- 手工验证：对同一任务 POST 一个 `files_db_path` 差一个字符的请求应得 400 `path_mismatch`；`GET` 一个不存在任务的任何受保护资源应得 404 而非 500。

## 10. 二轮深化 A：六路由 × 函数 × 错误码映射矩阵

| 路由（入口） | 调用的 task_store 函数 | 消费的 task 键 | TaskStoreError → HTTP |
|---|---|---|---|
| markitdown /convert | get_task_record + workspace_from_record + file_known_to_task/resolved_within | output_files_db、output_events_db、output_raw_db | not_found→404、unavailable→400/503、outside→400 |
| markitdown /convert-one、/batch-convert | workspace 解析 + has_symlink_component×3 + resolved_within | 同上 | 同上 + 符号链接→400 |
| office /parse | workspace_from_record + internal_extract_root + file_known_to_task | 三库键 | not part of task→404 |
| dll /analyze/dll | resolve_task_files_db + validate_legacy_db_path | output_files_db[_path] | mismatch→400、not_found→404 |
| multi_analysis（每任务循环） | resolve_task_files_db + validate_legacy_db_path | 同上 | not_found→404、其余→400 |
| case_analysis _case（reanalyze） | resolve_task_files_db + validate_legacy_db_path | 同上 | 同上 |
| llm_endpoints /analyze | resolve_task_files_db + validate_legacy_db_path | 同上 | 同上 |

`extraction_directory` 键不在 task_store 消费（它由 llm_endpoints/_analysis.py:189 与 file_filter 直接读 task 记录用于镜像内路径解析——task_store 的职责边界只到"库与工作区"）。

## 11. 二轮深化 B：与 investigation/paths.py 的同构对照

| 维度 | task_store.py | investigation/paths.py |
|---|---|---|
| 信任源 | cpp_backend.get_task（经 `_get_service_manager()` 延迟导入防环，:49-53） | 调用方传入的 task dict |
| 父目录一致键 | 三键（files/events/raw，:87-101） | 两键（files/events，paths.py:23-26） |
| 产出 | 工作区根（三库共同父目录） | `<父>/investigation.db` |
| 异常类型 | TaskStoreError(code) | EvidenceStoreError |
| 语义 | 404/400/503 分流 | 503（fail-closed 域错误） |

两处 `len(set(parents)) != 1` 判定逐字符同构——模块头注释（task_store.py:10-24）自认复用后者纪律。差异点在键集：investigation 侧不需要 raw.db（调查域不读 raw），因此**只挂 raw.db 的任务**能过 investigation 检查却过不了 markitdown 工作区检查——排障时按域选对模块。

## 12. 二轮深化 C：路径攻击向量 × 防御机制对照表

| 攻击向量 | 示例 | 防御机制 | 位置 |
|---|---|---|---|
| 兄弟前缀冒充 | `/t/a` 冒充 `/t/abc` 的成员 | resolve + `relative_to`（组件感知） | resolved_within :122-137 |
| `..` 穿越 | `workspace/../../etc/passwd` | 同上（resolve 抹平再判包含） | 同上 |
| 符号链接重定向 | 根内 symlink 指向根外 | resolve **前**逐组件 is_symlink | has_symlink_component :140-155 |
| 客户端猜路径 | files_db_path 填别的库 | 精确相等（无 basename/后缀/大小写兜底） | validate_legacy_db_path :104-119 |
| 记录内字段不一致 | 三库父目录不同 | set(parents) 唯一性 | workspace_from_record :87-101 |
| 库损坏冒充"无文件" | files.db 打不开 | 三层 unavailable（不返回 False） | file_known_to_task :163-191 |
| 空任务 ID | `""`/空白 | 入口即 task_not_found | get_task_record :55-59 |

已知残余（第 8 节已记录的补充视角）：validate_legacy_db_path 的 `resolve(strict=False)` 可能把"仅符号链接差异"的两条路径折叠成相等——防御靠路由层叠加 has_symlink_component，新增入口忘叠即留洞。

## 13. 二轮深化 D：新走读——`_get_service_manager()` 的防环延迟导入（:49-53）

```python
# task_store.py:49-53
def _get_service_manager():
    from . import get_service_manager
    return get_service_manager()
```

逐块解释：task_store 被 services/__init__ 的消费者（六个路由）在**模块导入期**引用，而 `services/__init__.py` 又 re-export get_service_manager——若 task_store 顶部直接 `from . import get_service_manager` 会形成"包初始化中导入包成员再反向导入包"的循环。函数体内的延迟导入把时序推迟到**首次调用**（此时包已初始化完毕）。代价是每次 get_task_record 都做一次函数级 import（Python 的 import 缓存使其为字典查找级开销，可忽略）；收益是 task_store 可以被任何层安全导入。同样的模式在 markitdown/office/dll 等路由的 handler 内 `from ..services import get_service_manager` 里反复出现——这是本仓库处理 services 包循环的标准手法（对比 ServiceManager 用"函数体内导入服务模块"解决同类问题，main.py:52-57）。

## 14. 二轮深化 E：get_task 的前置防御链（上游契约）

task_store 的信任完全建立在 `cpp_backend.get_task` 之上，其自身的防御（CppBackendClient.md 第 4 节）构成门卫的前置层：`task_id ∈ {".", ".."}` 直接拒收（cpp_backend.py:182-184）→ `quote(task_id, safe="")` 防 path 注入（:184）→ 响应 `id` 回显一致才返回（:197，防错配响应）。因此 task_store 收到的 task dict 已经过三层过滤；`image_name ← image_path` 别名补齐（:199-200）发生在同一方法内——下游读 `image_name` 的代码实际拿的可能是镜像路径，两个键的语义差异要在展示层自行处理。

**最后更新**: 2026-08-24（二轮深化：补全端点清单与模型契约）
