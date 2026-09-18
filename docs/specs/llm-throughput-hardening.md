# SPEC: LLM 流水线吞吐与正确性加固（LLM Throughput Hardening）

- 状态：已评审锁定，待实施（2026-09-16 与用户逐项定稿 A–F 六项）
- 来源：2026-09-16 对《分析缓慢四层叠加》报告的只读核查（分支
  `debug/llm-slowness-verification`）+ 活体实测归因；单点调研结论见本文各节"依据"
- 分支：`debug/llm-slowness-verification`（本 SPEC 随分支提交）
- 关联：`kg-ingestion-hardening.md` 的"已知余留"（给 graphiti 抽取单独配小模型）由本 SPEC
  B 项根治；A 项门控与该 SPEC 的单飞锁（B1）同点共存

## 0. 背景与实测归因

| # | 实测事实 | 数字 |
|---|---|---|
| 1 | 流水线 8 个 TaskPhase 中仅 2 个耗 LM Studio | `LLM_ANALYSIS`（文件+簇，Python）、`PLATFORM_ANALYSIS`（工件逐行，C++） |
| 2 | 单 episode 摄取成本 | `add_episode` 272.9s（4–7 次串行 LLM 调用）；FULL 模式 79 episodes ≈ 6h |
| 3 | 争抢收益差 | 无争抢文本 9s/件（中位）；争抢时 8–26min/件（E01 实测 9.9h/13.6h，ubuntu 全链 2.66h） |
| 4 | 摄取积压 | 4 个 8 月僵尸 running + 当日 4 个 running；worker 单槽（`_worker.py:197`） |
| 5 | 推理膨胀 | nemotron 对 "hi"+max_tokens=16 → content 0 字符、reasoning 71 字符；Graphiti 空响应重试翻倍调用（`llm_patch.py:96`）；`/no_think` 无效 |
| 6 | 图片路径质量缺陷 | jpg/png 走 markitdown 必失败（extractor_mapping fallback 无图片项）→ C++ Raw Read 二进制当文本（≤`LLM_MAX_CONTENT_LENGTH`=10000）喂 LLM → "???????" 误导描述；图片耗时大头实为 #3 争抢 |
| 7 | 真源表缺失 | 流水线文件分析由 C++ 直写 `files.llm_*`+`file_descriptions`（`LLMAnalysisService.cpp:360` 手工副本），无 `file_analyses` append-only 真源行；`model_used="default"`（写了 router 键名） |
| 8 | 视觉通路可用性 | C++ `LLMClient` 已支持 image_url 格式；`VisionAnalyzer::analyzeWithPrompt` 为现成轮子；LM Studio 实测 206KB 截图 **7.7s** 返回正确描述（detail=low，297 prompt tokens） |

## 1. 决策

### A. Graphiti 前台门控 + 僵尸治理

- **A1 门控**：新增前台忙判定——存在任务 `status=RUNNING` 且
  `progress.current_phase ∈ {LLM_ANALYSIS, PLATFORM_ANALYSIS}`（经
  `cpp_backend.list_tasks()` 轮询 C++ `GET /api/tasks/list`，间隔
  `GRAPHITI_GATE_POLL_SECONDS`=30）。摄取 worker 在**每个 episode 之间**检查；忙则 job 进入
  `waiting_idle` 子状态（progress 保留，UI 可见），空闲续跑。FINALIZING 不在集合内，任务尾部
  自触发不受自阻塞。
- **A2 插入点**：与 kg SPEC 单飞锁相同的 choke points——`graphiti_parts/_ingest.py` 三处
  batch 循环 episode 间、`file_analyzer.ingest_to_knowledge_graph` 直调处。kg_sync 自运行
  job 走同一批函数，天然覆盖。episode 内部（add_episode 黑盒）不中断，飞行中一个豁免。
- **A3 逃生口**：`POST /api/graphiti/ingest` body 增 `force`（bool，默认 false）；force=true
  绕过门控。
- **A4 轮询失败语义**：首查失败按"忙"；连续 ≥3 次失败按"空闲"（降级 WARN 日志）——C++ 不可
  用时 GPU 必然空闲。
- **A5 僵尸清理**：job 启动时记录 `runner_epoch`（服务 boot uuid）；worker 启动 sweep：
  `status==RUNNING && runner_epoch≠current` → 置 `stale`（终态，error="service restarted
  mid-run"）。
- **A6 作业超时**：自 `started_at` 起超 `GRAPHITI_JOB_TIMEOUT_HOURS`=12 → 在 episode 边界取消，
  status=FAILED(error=timeout)。
- **A7 二期（不在本 SPEC 范围，防遗忘）**：断点续摄——利用文件-episode 状态机跳过已有
  episode 的文件续跑。v1 只标 stale + 手动重触发。
- 落点：`ingestion_job_parts/_worker.py`、`graphiti_parts/_ingest.py`、job 存储结构、
  （可选）`foreground_gate.py` 独立模块；约 100–200 行 + 单测。

### B. Graphiti 抽取模型分离（空值回退）

- **B1 配置**：`.env` 新增 `GRAPHITI_LLM_MODEL`，**空值 → 回退 `LLM_TEXT_MODEL`**（行为与现状
  逐字节一致）。
- **B2 落点**：`graphiti_integration/config.py:93`
  `llm_model=os.getenv("GRAPHITI_LLM_MODEL") or os.getenv("LLM_TEXT_MODEL", …)`；
  `graphiti_ingestor.py` 的 `LLMConfig.model` 与 `small_model` 同值跟随；
  `OpenAIRerankerClient` 使用同一 config 确认跟随。
- **B3 选型**：`microsoft/phi-4`（14B 非推理版；2026-09-16 已下载并在 LM Studio
  `/v1/models` 注册为 `microsoft/phi-4`；目录核实 qwen2.5 instruct 已下架、Qwen3 系均为
  思考型、phi-4 与 phi-4-reasoning 明确分开）。`GRAPHITI_LLM_MODEL=microsoft/phi-4`。
- **B4 作用域**：任务尾部 FULL 摄取与流水线内簇 episode 摄取（single-own episode）共用
  `graphiti_integration` 实例，一并生效。`llm_patch.py` 保留作安全网（对非推理模型无副作用）。
- **B5 验证（A/B）**：同一已分析任务重摄，对比——单 episode 耗时（基线 272.9s）、
  "thinking/noise" 日志条数（基线 2/晚，目标 0）、Neo4j 实体/关系质量抽查（14B 非推理模型
  抽取质量为本项唯一质量风险，必须实测把关）。
- **B6 边界**：分析模型（nemotron）不动；图片分析仍走 nemotron-omni（唯一 VLM，见 D）。

### C. 工件分析批量 prompt（C3）

- **C1 协议**：每批 N 条（默认 10）。user 消息列出
  `[{"id":…,"type":…,"data":{…}}, …]`，要求输出 JSON 数组
  `[{"id":…,"summary":…,"description":…,"keywords":[…]}]`；system 沿用现有单条角色与四段要求。
- **C2 校验**：响应 id 集合与请求精确匹配 + 必填字段 + 沿用现有 description 截断。
- **C3 失败阶梯**：整批解析失败 → 带纠错指令原批重试 1 次 → 批拆半递归（N/2）→ 最低到 1
  （= 现状单条代码路径，兜底不劣于现状）。个别条目缺失/非法 → 仅对该条目走单条调用。
  原则：静默跳过证据不可接受。
- **C4 共享实现**：提取 `BatchArtifactAnalyzer` helper，Linux/Windows/Android 三个
  `LLMAnalysisService` 统一调用，禁止三处各写各的。DB 写回保持逐条（耐久性语义不变）。
- **C5 进度**：批内**逐条**发 `progressCallback(tableName, k, total)`——看门狗活性依赖进度
  心跳，一条 HTTP 跨分钟时必须靠批内回调保活。
- **C6 超时预算**：批量响应（10 条 × ~200tok + reasoning）÷ 33tok/s ≈ 60–120s+，C++ LLMClient
  读超时按批大小线性放大（或批量请求统一 ≥180s）。
- **C7 配置灰度**：`LLM_ARTIFACT_BATCH_SIZE=1`（默认=现状关闭）→ 试点 10（ubuntu 镜像）→
  E01。`LLM_ARTIFACT_BATCH_RETRIES=1`。
- **C8 换模暂缓（用户决策）**：工件路径是否脱离 nemotron 等 phi-4 在 Graphiti 的 B5 实测
  结果再定；届时倾向将空值回退模式推广到 C++（`LLM_ARTIFACT_MODEL`，经 ModelRouter 配置）。

### D. 图片走视觉路径（D-vision）

- **D1 路由**：C++ `FileAnalyzer::analyzeFile` 对图片扩展（现有 IMAGE 集合）不再 Raw Read →
  调 `VisionAnalyzer::analyzeWithPrompt(path, prompt)`；prompt 与流水线四段输出
  （SUMMARY/DESCRIPTION/KEYWORDS）对齐并注入取证要点。
- **D2 降级链**：vision 请求失败/HTTP 400（损坏）或文件 > `LLM_IMAGE_MAX_BYTES`（默认 8MB）
  → 复用现有 Binary 分支机制（metadata-only 文本走一次普通调用）。VisionAnalyzer 无压缩
  能力，v1 大图直接降级，不引入 C++ 缩放。
- **D3 配置**：`LLM_IMAGE_DETAIL=low`（实测低 token 高质量：297 prompt tokens）；`LLM_IMAGE_MAX_BYTES=8388608`。
- **D4 模型**：固定 nemotron-omni（服务器唯一 VLM；phi-4 纯文本）。与 B/C 模型决策正交。
- **D5 二期可选**：EXIF 伴随上下文（拍摄时间/GPS/设备，像素里没有的取证信息）；OCR；vision
  结果同样经 E 的端点落真源（`extraction_method="vision"`）。
- **D6 收益**：单图 7.7s（无争抢实测）替代现状二进制垃圾分析（误导描述 + 争抢时 10–20min）。

### E. file_analyses 真源表补齐

- **E1 新端点**：`POST /api/file-analysis/record`（挂 `routes/file_analysis.py` 既有 router）。
  body：`{files_db_path, file_path, description, summary, keywords, model_used,
  extraction_method, task_id}` → 调已测试的 `persist_to_files_db`（三写原子，
  `trigger_source="pipeline"`）→ `{persisted: bool}`。服务为 C++ 内网直连，与
  `/api/graphiti/*` 同类，无需 cs 认证。
- **E2 C++ 接入**：`LLMPythonProxy` 新增 `recordFileAnalysisResult(...)`；
  `LLMAnalysisService` 写库点改为 POST；**Python 不可用时保留现有直写完整逻辑为降级**
  （WARN 日志），耐久性语义不回退。
- **E3 删重**：直写路径降级保留，但正常路径不再双写；`file_descriptions` 重复维护段随
  三写收敛。
- **E4 model_used 修复**：写 `ConfigManager::getTextModel()`（真实模型名）而非
  `router_->getLastUsedModel()`（键名 "default"）。
- **E5 不动**：事件簇 append-only 记录（事件簇 SPEC）不受影响；`file_analyses` schema 不改。

### F. 可观测性

- **F1 日志轮转**：Python 服务日志改 `RotatingFileHandler`（backupCount ≥ 5），C++ 侧启动
  轮转保留 3–5 份——废止"清空重写"（2026-09-16 调查中当晚原始证据即因此丢失）。
- **F2 耗时日志**：Python 侧 LLM 调用包装处单行 `LLM call dur=Xs model=M in=/out=`；C++
  `LLMClient::chat` 返回前同规格一行。episode 级耗时已有（`Completed add_episode in Xms`），
  不重复加。

## 2. 禁改红线

- add_episode 组内串行与 kg SPEC 单飞锁语义不动；A 的门控与锁共存，不改锁行为。
- 文件分析/事件簇两 SPEC 的 append-only 约定不动；E 只是收敛 C++ 副本进 Python 三写，不改
  任何 schema。
- job 体系公开 API（queue_ingestion / GET /jobs…）签名不变，只增量加字段（force、
  runner_epoch、waiting_idle 相位）。
- Python `_run_batch_analysis` 串行循环不动（流水线文件分析走 C++，不经过它）。
- 所有新旋钮默认=可回现状：`GRAPHITI_LLM_MODEL` 空=现状；`LLM_ARTIFACT_BATCH_SIZE=1`=现状；
  `GRAPHITI_FOREGROUND_GATE=false`=现状（默认 true 是本 SPEC 唯一刻意的行为变化）。
- 看门狗进度活性不得降级：C 批内逐条回调、D 每图回调、A 挂起仅作用于后台 job（不在任务
  看门狗管辖内，任务进度回调不受影响）。
- 分析模型 nemotron 不动（B 只换 Graphiti 抽取；C8 换模另行决策）。

## 3. 阶段与验收

- **Phase 1（P0）A + F**：门控 + 僵尸 sweep + 超时 + 轮转 + 耗时日志。验收：单测（忙判定
  状态机、force 绕过、轮询失败降级、runner_epoch sweep、超时取消）全绿；活体——起一个带
  LLM 的任务，观察摄取 job 进入 waiting_idle、任务结束后自动恢复。
- **Phase 2（P0）B**：配置 + 客户端跟随 + A/B 验证。验收：B5 三指标（episode 耗时、
  thinking/noise=0、KG 抽查）；空值回退回归（不设 env 行为不变）单测。
- **Phase 3（P1）D**：C++ vision 分支 + 降级链。验收：**C++ 构建绿**（历史教训：C++ 改动
  必须构建验证）；ubuntu 镜像 3 张图实测 vision 生效、构造损坏图与大图验证降级。
- **Phase 4（P1）E**：端点 + 代理 + 替换 + model_used 修复。验收：端点契约单测；流水线跑后
  目标库存在 `file_analyses` 行且 `trigger_source='pipeline'`、`model` 为真实模型名；
  停 Python 服务验证降级直写不阻塞流水线。
- **Phase 5（P2）C**：helper + 协议 + 三处接入 + 灰度。验收：失败阶梯单测（重试/拆半/单条
  兜底）、批内逐条进度单测；BATCH=10 于 ubuntu 实测调用数 ÷N 与质量抽查 → E01。

## 4. 新增配置总表

| 配置 | 默认 | 归属 | 说明 |
|---|---|---|---|
| `GRAPHITI_LLM_MODEL` | 空（回退 `LLM_TEXT_MODEL`） | B | Graphiti 抽取模型，填 `microsoft/phi-4` |
| `GRAPHITI_FOREGROUND_GATE` | `true` | A | 前台门控总开关 |
| `GRAPHITI_GATE_POLL_SECONDS` | `30` | A | /api/tasks/list 轮询间隔 |
| `GRAPHITI_JOB_TIMEOUT_HOURS` | `12` | A | 作业超时（episode 边界取消） |
| `LLM_ARTIFACT_BATCH_SIZE` | `1`（=关闭） | C | 每批工件数 |
| `LLM_ARTIFACT_BATCH_RETRIES` | `1` | C | 整批解析失败重试次数 |
| `LLM_IMAGE_MAX_BYTES` | `8388608` | D | 超限降级 metadata-only |
| `LLM_IMAGE_DETAIL` | `low` | D | vision detail 等级 |

## 5. 验证基线（实施后对比）

| 指标 | 基线 | 目标 |
|---|---|---|
| E01 全链耗时 | 9.9h / 13.6h | 3–4h（C 灰度后） |
| ubuntu 全链耗时 | 2.66h | ~1h |
| 单 episode 摄取 | 272.9s | ≤150s（phi-4）且 thinking/noise=0 |
| 前台单件延迟 | 争抢时 8–26min/件 | 恒定 ≈9s（中位） |
| 图片单件 | 10–20min（争抢）+垃圾描述 | ~10–30s 且描述真实可用 |
| 僵尸作业 | 8 个（4 stale 态+4 当日） | 0（sweep 后）；前台忙时零竞争 |

## 6. 实施记录

- **Phase 2B（B）**：`graphiti_integration/config.py` 空值回退 + `.env` `GRAPHITI_LLM_MODEL=microsoft/phi-4`；
  测试 `tests/unit/test_graphiti_model_config.py`（5 用例）。
- **Phase 1（A）**：新增 `graphiti_integration/episode_gate.py`（底层钩子注册表 +
  GateAborted）、`httpserver/services/ingestion_gate.py`（忙判定/ContextVar 作业上下文/超时/轮询
  失败降级/install+uninstall）；`batch_ingest` episode 间调用钩子（中止的 episode 计入
  failed 并留错误明细）；worker `_process_job`/kg_sync runner 设置作业上下文，超时收敛为
  FAILED；`IngestionJob` 增 `runner_epoch`/`force`；启动 stale sweep（Redis 模式有效）；
  `/ingest` 增 `force`；main.py lifespan 装载并在退出时卸载（防进程级单例泄漏进测试）。
  测试 `tests/unit/test_ingestion_gate.py`（14 用例）。
- **Phase 1（F）**：`run.sh` `rotate_log()` 三服务日志保留 5 份轮转；Python
  `file_analyzer` 文本/视觉两条路径单行耗时日志；C++ `LLMClient` 路径在
  `FileAnalyzer::finishTextAnalysis`/`analyzeImageFile` 输出 `[LLMClient] dur=…`。
- **Phase 4（E）**：Python `POST /api/file-analysis/record`（服务端按任务记录解析
  files_db，`asyncio.to_thread` 跑三写，`trigger_source="pipeline"`）；C++
  `LLMPythonProxy::recordFileAnalysisResult`；`LLMAnalysisService::storeDescription`
  代理优先、Python 不可用回退直写；`model_used` 全部改记真实模型名
  （`router_->getConfig().model`，修复 "default"）；`tests/CMakeLists.txt` 给
  test_scene_classifier_gtest 补链 LLMPythonProxy.cpp。测试
  `tests/unit/test_file_analysis_record.py`（4 用例）。
- **Phase 3（D）**：`FileAnalyzer` 图片扩展（jpg/jpeg/png/gif/bmp/webp/tiff/tif）改走
  `analyzeImageFile`：base64+`detail=LLM_IMAGE_DETAIL`（默认 low）直喂多模态模型；超
  `LLM_IMAGE_MAX_BYTES`（默认 8MB）/vision 失败 → metadata-only 文本分析降级；公共尾部抽取为
  `finishTextAnalysis`/`parseAnalysisResponse`。ConfigManager 新增
  `getLLMImageMaxBytes`/`getLLMImageDetail`/`getLLMArtifactBatchSize`/`getLLMArtifactBatchRetries`。
- **Phase 5（C）**：新增 header-only `src/network/HTTPServer/LLMBatchAnalysis.h`
  （打包 prompt/响应解析/失败阶梯：整批重试 1 次→拆半递归→单条留给调用方兜底）；
  Linux/Windows/Android 三个 `analyzeArtifactType` 重构为共享 lambda
  （analyzeSingle/reportProgress/storeOne）+ `LLM_ARTIFACT_BATCH_SIZE>1` 批量路径；
  默认 1 = 现状逐行调用。
- **构建**：全量 `cmake --build` 100% 通过（含 web_frontend）。
- **全量测试（2026-09-17）**：Python 全套 **1691 passed / 12 failed / 4 errors / 9
  skipped** ——12 failed + 4 errors 经 `git stash` 对照证实为**存量/并行改动**（干净树同批
  测试同样失败；e2e 的 502 为真实 C++ 服务被占用）。C++ ctest **54/62 通过**；8 个
  Timeout（120s 线）经串行复核为环境负载（完全未触碰的 EventTimelineTests 串行 131.5s
  16/16 通过；Android/Miui 测试二进制根本不链接本 SPEC 改动的文件；MiuiBackupHeaderTests
  处 D 状态 IO 挂起）。新增 23 个 Python 用例全绿。
- **注意**：实施期间发现并行会话在同一工作区活动（分支 `mvp/phase1-acceptance`，提交
  1072421 将本 SPEC 的进行中改动打包带走、a776272 自行 pin phi-4），工作区存在两拨未提交
  改动的叠加，提交切分需人工确认归属。
