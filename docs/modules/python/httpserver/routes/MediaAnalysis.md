# MediaAnalysis 路由（python_service/httpserver/routes/audio_analysis.py + video_analysis.py，前缀 /api/audio-analysis、/api/video-analysis）

> **一句话**：音视频内容的两条 C++ 面向 HTTP 门——音频走 SenseVoice 本地 STT+要点合成（全文落 `audio_transcripts` 表），视频走分段抽帧的多图视觉调用（串行段级描述+综合），两者共用 markitdown 的任务归属门与"超时长文件降级为 metadata-only + 待回填"语义；交互式 Python 流程不经过这里，直接调同实现的服务层。

## 1. 这组路由承担什么职责（为什么存在）

两个文件是同一条设计准则的两个实例（audio_analysis.py:1-6 / video_analysis.py:1-7 的 docstring 几乎逐句对应）：C++ 任务流水线的文件描述阶段此前把音视频**原始字节**喂给文本模型（音频）或完全不管内容（视频），现在改为调用这两个端点——"Used by the C++ backend via HTTP (task-pipeline file description — replacing the previous raw-read/metadata paths), while interactive/case Python flows call the analyzer directly"（audio_analysis.py:2-5）。也就是说：服务层（services/llm/audio_analyzer.py、video_analyzer.py）是唯一实现，这两个路由只是**实现面向 C++ 的门**。

每端点只有一个：`POST /api/audio-analysis/transcribe`（main.py:354 挂载）与 `POST /api/video-analysis/describe`（main.py:353）。

## 2. 典型调用方（前端哪个页面/组件）

- **C++ 流水线**是主要调用方（逐文件分析阶段按扩展名分派）。
- 前端不直接调这两个端点——`/files` 页的音视频描述经批量 LLM/流水线结果读回（`/api/llm/*` 与 files.db）；`extraction_method` 字段（vision/metadata_only 等）在文件详情里可见，是这条链路的间接痕迹。
- 交互式 Python 流程（案件工作流）直接调 `services.llm.audio_analyzer.analyze_audio_file` / `video_analyzer.analyze_video_file`（audio_analysis.py:5-6）。

## 3. 核心数据结构

**请求模型**（两文件同构，audio_analysis.py:31-43 / video_analysis.py:31-43）：

| 字段 | 含义 |
|---|---|
| `task_id` | 可选，任务归属锚（决定文件必须在该任务工作区内） |
| `workspace_root` | 可选，**已废弃**的独立工作区锚（兼容 CLI 调用方） |
| `file_path` | 必填，绝对路径 |
| `prompt` | 可选，研判提示词（织入综合阶段） |

**响应模型**：AudioTranscribeResponse（audio_analysis.py:46-54）与 VideoDescribeResponse（video_analysis.py:46-55）都是 `success/description/summary/keywords/model/extraction_method/processing_time_ms`，视频多一个 `tokens_used`。`extraction_method` 携带降级形态（如 metadata_only / pending_backfill 相关标注），调用方据此区分"分析了"与"只读了元数据"。

**扩展词表**：`AUDIO_EXTENSIONS`（services/llm/audio_analyzer.py）与 `VIDEO_EXTENSIONS`（video_analyzer.py）是各自路由的 400 判定源（audio_analysis.py:84-88、video_analysis.py:87-91）。

## 4. 端点语义分组（散文）

- `POST /api/audio-analysis/transcribe`（audio_analysis.py:54-128）：SenseVoice-small（CPU）+ silero VAD 分块转写，再合成取证描述；**全文转写落任务 files.db 的 `audio_transcripts` 表**（:66-69 docstring——描述只带按时长分带的要点摘录，全文在库里）；超过 `LLM_AUDIO_MAX_DURATION_SEC`（默认 60 分钟）的音频**不转写**，落一行 `pending_backfill` 状态的转写记录（coverage 0 + 说明）并返回 metadata-only 描述（:67-70、audio_analyzer.py:6-7/:294）。`trigger_source="pipeline"`（:110）——落库时标记触发来源。
- `POST /api/video-analysis/describe`（video_analysis.py:57-119）：时长 ≤ `LLM_VIDEO_MAX_DURATION_SEC`（默认 30 分钟，video_analyzer.py:11）时按 `LLM_VIDEO_FPS` 抽帧、每 `LLM_VIDEO_SEGMENT_SECONDS` 窗口一次多图视觉调用（**严格串行**，video_analyzer.py:8/:250-302），最后综合成整体描述；超长视频同样降级 metadata-only 并标记待回填；**音轨不分析**（:71 docstring："The audio track is not analyzed"——视频中的语音内容不在本端点职责内）。

## 5. 数据流（读什么、写什么）

**归属门**（两文件第一道检查）：`_assert_file_readable_for_task(task_id, workspace_root, file_path)`（audio_analysis.py:76-79、video_analysis.py:79-82，从 markitdown.py 导入）——task_id 锚定时文件必须在该任务工作区内，防"传任意路径读任意文件"；归属校验通过后才看文件存在（404）与扩展名（400）。

**信任库解析**：task_id 给定时经 `task_store.resolve_task_files_db(task_id)` 解析**可信** files.db（audio_analysis.py:99-105——音频全文落库的目标库路径不是请求传的，是任务记录推的，与 record 端点同一信任取向）；LLM 服务经 `get_service_manager().llm_service` 注入服务层。

**写**：只有音频写库（audio_transcripts 表，含 complete/partial/pending_backfill 三态记录，audio_analyzer.py:238/:294）；视频无落库（描述经调用方——C++ 流水线——写 files.db 的常规分析列）。

**错误面**（openapi responses 声明一致）：400（非音频/视频扩展名、工作区外）、404（文件不存在）、500（分析失败，detail 固定 "audio analysis failed"/"video analysis failed"，:117/:107——异常文本只进日志）；归属门自己的拒绝语义由 markitdown 门决定。

## 6. 边界与已知状态（降级/限额）

- **时长限额是硬闸不是尽力而为**：超限音频/视频不做部分分析，直接 metadata-only + `pending_backfill` 记录——回填是**显式的后续动作**，不是隐式重试。
- **视频段级串行**：多图视觉调用不并发（video_analyzer.py:8 "segments are strictly serial"）——视觉端点的速率约束优先于单文件延迟。
- **workspace_root 已废弃但仍接受**：为 CLI 调用方保留的过渡兼容（请求模型注释 "Deprecated standalone workspace anchor for CLI callers"），新调用方一律用 task_id。
- 两个端点都**同步等待**完成（无 202/job 模式）——C++ 流水线以逐文件调用消费，单文件时长可控；这与 TaskAnalysisRuns 的后台作业模式是两种并发取向（流水线文件级并行 vs 端点内串行）。
- env 限额族：`LLM_AUDIO_MAX_DURATION_SEC`（60min）、`LLM_VIDEO_MAX_DURATION_SEC`（30min）、`LLM_VIDEO_FPS`、`LLM_VIDEO_SEGMENT_SECONDS`。

## 7. 如何验证

- 服务层：`python_service/tests/unit/` 下 audio/video analyzer 测试（分段计划、pending_backfill、扩展词表）。
- 端点冒烟：对任务工作区内一个 mp4 调 describe（vision 模型可用时得分段描述；不可用时得 metadata-only，extraction_method 体现降级）；对一个 >60min 的 wav 调 transcribe，核对 files.db `audio_transcripts` 出现 pending_backfill 行。
- 流水线回归：跑一个含音视频文件的任务，确认 C++ 侧描述来自本端点（files.db 分析行的 extraction_method 为 vision/音频对应值而非旧 raw-read 路径）。

相关阅读：[TaskAnalysisRuns.md](TaskAnalysisRuns.md)（文件分析记录链）、[LLM.md](LLM.md)（同前缀族的 LLM 服务面）、services 实现层 `services/llm/audio_analyzer.py` 与 `services/llm/video_analyzer.py`。

## 8. 二轮深化 A：一个实现、两个消费者的门模式

两个文件的 docstring 都写明"这是 C++ 之门的实现共享"：服务层函数（analyze_audio_file/analyze_video_file）带 `trigger_source` 参数，交互式 Python 流程直接调用（trigger_source=case/interactive），HTTP 端点固定传 `"pipeline"`（audio_analysis.py:110）。这个模式的价值在落库语义：audio_transcripts 的每行都能回答"这段转写是流水线批量产生的还是分析师手动触发的"——审计链不需要另建通道。而 `workspace_root` 的废弃兼容说明门的演化路径：先加 task_id 锚（可信来源），旧锚保留给 CLI 渐进迁移。对照 [TaskAnalysisRuns.md](TaskAnalysisRuns.md) 的 record 端点（C++ 回写分析结果），本项目 C++/Python 的分工一致性在这三处反复出现：**C++ 负责"何时对哪个文件做什么"，Python 独占"怎么做与写哪里"**。

**最后更新**: 2026-11-10（新建：音视频内容分析路由文档）
