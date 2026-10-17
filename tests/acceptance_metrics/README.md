# TraceLens 第三方验收测试套件（tests/acceptance_metrics）

面向第三方验收方的黑盒测试套件：只通过已部署服务的 HTTP 端点与任务库判定
验收指标，不 import 产品代码。每个用例首行 docstring 标注对应的验收指标与
判定口径。

## 运行前提

1. TraceLens 已部署且 C++ 后端 / Python 服务在线（默认 `:8666` / `:8090`）。
2. 夹具已生成：`python3 tests/acceptance_metrics/prepare_fixtures.py`
   （仅用 mkfs.ext4 + debugfs，无需 root；输出在 `fixtures/`）。
3. 运行环境：`python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v`
   （依赖 requests + pytest，venv 内已具备）。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TRACELENS_CPP_BASE` | `http://127.0.0.1:8666` | C++ 后端地址 |
| `TRACELENS_PY_BASE` | `http://127.0.0.1:8090` | Python 服务地址 |
| `TRACELENS_ACCEPT_USER/_PASSWORD` | 无 | 服务开启 field-auth 时必填 |
| `TRACELENS_ACCEPT_FIXTURES` | `tests/acceptance_metrics/fixtures` | 夹具目录 |
| `TRACELENS_DATA_DIR` | `<repo>/data`（自动兜底 `build/data`） | 任务库/审计库根目录 |
| `TRACELENS_ACCEPT_TASK_TIMEOUT` | 3600 | 单任务完成超时（秒） |
| `TRACELENS_E01_IMAGE` | 无 | 真实 E01 镜像路径（开源工具无法凭空生成 E01） |
| `TRACELENS_ACCEPT_MIN_MB_S` | 10 | 吞吐阈值（合同值 10MB/s） |
| `TRACELENS_ACCEPT_REPORT_TIMEOUT` | 1800 | 推演报告生成超时（秒） |
| `TRACELENS_ACCEPT_ASSUME_LLM` | 无 | 置 1 时跳过 LLM 探测直接运行 LLM 用例 |

## 指标 ↔ 用例 ↔ 判定标准

| 验收指标 | 用例 | 判定标准 | 夹具 |
| --- | --- | --- | --- |
| 1(1) 磁盘镜像 RAW | `test_m1_1a_raw_image_ingest` | 任务 COMPLETED 且 raw 库提取全部植入文件 | `raw_basic.img` |
| 1(1) 磁盘镜像 DD | `test_m1_1b_dd_image_ingest` | 同上（.dd 逐字节副本） | `dd_basic.dd` |
| 1(1) 磁盘镜像 E01 | `test_m1_1c_e01_image_ingest` | 任务 COMPLETED 且提取 >0 文件 | `TRACELENS_E01_IMAGE` |
| 1(1) Android 移动设备 | `test_m1_1d_android_source` | 任务 COMPLETED 且 android.db 建表 | `android_test_gen.img`（prepare_fixtures 调 scripts/create_android_image.sh，需 sqlite3 CLI） |
| 1(1) 服务器日志 | `test_m1_1e_server_logs` + `_events` | oss.db（SERVER_CLOUD 场景的解析工件库）解析出日志/账户工件；events 库 >0 | `logs_server.img` |
| 1(2) 过滤吞吐 ≥10MB/s | `test_m1_2a_throughput_ge_10mb_s` | 镜像字节 / (审计 CREATED→RESULT_SET 窗口) ≥10 | `raw_basic.img` |
| 1(2) 低价值剔除率 ≥70% | `test_m1_2b_low_value_reject_ge_70pct` | 1 - scene_priority>0 文件数/全量 ≥70% | 同上 |
| 1(2) 待分析压缩至 12-15% | `test_m1_2c_pending_compress_12_to_15pct` | scene_priority>0 字节 / 全量字节 ∈ [12%,15%] | 同上 |
| 1(2) 统计口径一致性 | `test_m1_2d_overview_endpoint_consistency` | overview 端点与任务库数值一致 | 同上 |
| 2(1) 文本提取 | `test_m2_1a_text_extraction_markitdown` | MarkItDown 产物含关键内容 | `_md_in/_text_sample.html` |
| 2(1) 图像文字提取 | `test_m2_1b_image_text_extraction` | 视觉模型读出图上编号 `ACCT-2026-777` | `sample.png`（PIL 绘制） |
| 2(1) 视频信息提取 | `test_m2_1c_video_text_extraction` | 分段抽帧视觉分析产出非空描述 | `sample.mp4`（ffmpeg 生成） |
| 2(1) 事件转化 | `test_m2_1d_event_conversion` | events 库 >0 且时间线端点返回结构化事件 | `raw_basic.img` |
| 2(2) 重复证据去重 | `test_m2_2_duplicate_evidence_dedup` | duplicates 端点聚出植入重复对（md5 分组≥2） | 同上 |
| 3(1) 多模态同一事件聚合 | `test_m3_1_multimodal_event_aggregation` | 同一事件同时挂着文本文件与图像文件（内部沟通记录.txt 与 转账凭证.png 同分钟） | `raw_llm.img`（需 LLM：播种源=已分析簇） |
| 3(2) ≥100 事件节点 | `test_m3_2_timeline_supports_100_nodes` | events 库与时间线端点均 ≥100 节点 | `timeline_120.img`（120 个逐小时文件） |
| 4(1) 报告结构完整 | `test_m4_1a_report_structure` | sections[0]=案件背景章、含行为/证据/推断叙事、引用无悬空 | `raw_llm.img`（llm_analyze） |
| 4(1) 角色基本一致 | `test_m4_1b_role_consistency` | 报告具名角色 ⊆ {张伟, 李娜, 王五}（夹具植入集） | `raw_llm.img` |
| 4(2) 证据溯源定位 | `test_m4_2_evidence_traceback` | 每条 citation 经 workbench evidence/detail 定位成功 | `raw_llm.img` |

LLM 依赖用例标注 `@pytest.mark.llm`；`/api/llm/models` 无可用模型时自动
跳过（不误报失败）。只跑非 LLM 用例：
`python_service/.venv/bin/python -m pytest tests/acceptance_metrics -v -m "not llm"`。

## 已知缺口

1. **吞吐已在夹具口径达标**（2026-10-17，当前二进制）：`raw_basic.img`
   （100MB）过滤窗口冷启动 8.2s = 12.2MB/s、热缓存 7.9s = 12.7MB/s，审计口径
   仍是 CREATED→首次 RESULT_SET。提速来自三处：元数据与事件插入改为批量提交、
   raw 库建表用 `synchronous=NORMAL`、内容哈希只覆盖过滤保留的小文件。
   2026-10-15 的真实 E01（121,770 文件，4.32MB/s）是这些改动之前的测量，
   不再代表本分支，但十万级文件的速率尚未复测。剔除率与压缩比不变
   （71.4% / 12.9%）。
2. **去重只覆盖过滤保留的小文件**：TSK 遍历时对不超过 32MB、且落在保留目录
   （`/home`、`/root`、`/Users`、`/var/log`、`/var/lib`、`/etc` 等）的普通文件
   流式计算内容 MD5，读不完整则留空。低价值文件不计算哈希——给它们算哈希
   等于把过滤掉的数据又全读一遍。`test_m2_2` 断言 dup_a.csv / dup_b.csv 聚成一组。
3. **任务态 LLM 分析可能被未知二进制卡死**：夹具含随机二进制（.bin/.tmp 垃圾）
   时，`llm_analyze` 任务在"重要文件分析"阶段单文件 >20min-1h 无进展
   （2026-10-14 实测，最终手工取消；markitdown 对这些文件是干净 skip，卡点在
   C++ 把未知二进制原文喂给文本模型后的空响应重试）。因此推演/聚合用例使用
   纯文本证据镜像 raw_llm.img。产品侧建议：任务态分析启用 skipBinaryFiles 或
   为未知扩展名设置跳过/超时。另注意：任务态分析（smart 模式）实际分析了
   scene_priority=0 的文件，与研判准入口径（scene_priority>0）不一致，
   量大镜像时将显著拉长任务时长。
4. **E01 用例需真实镜像**：开源工具无法生成 E01；验收时设 `TRACELENS_E01_IMAGE`
   指向真实镜像（全量分析约数小时，注意任务超时配置）。
5. **Android 夹具：`prepare_fixtures.py --only android` 需要宿主有 `sqlite3`
   CLI；无则用例跳过并在现场补夹具。

6. **叙事生成为 LLM 概率性输出**：`citation_invalid`（某节引用了节范围外的
   证据键）等校验失败属间歇性，重跑该用例即可（每次 POST /generate 都是新一次
   生成）；结构/溯源用例在多次运行中均稳定通过。

## 验收报告口径

测试输出（`-v -s`）内联打印关键度量（吞吐、剔除率、压缩比、节点数、报告
章节数/引用数），可直接转录进验收记录。夹具组成由 `fixtures/manifest.json`
固化，保证第三方复现时输入一致。
