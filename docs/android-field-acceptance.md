# Android 现场交付闭环：第六阶段验收记录

后续 6A 现场认证/出站控制的代码、隔离验收和**生产待切换**状态单独记录于 [`android-field-security-6a.md`](android-field-security-6a.md)。本页保留第六阶段当时的历史基线，不把未重启的生产实例写成已受 6A 保护。

后续 6B 的合成单条 Android 工件→冻结快照→研判/复核→R2 引用与回跳实现见 [`android-investigation-6b.md`](android-investigation-6b.md)。下表 C/D 是第六阶段**当时**的基线，不是 6B 当前代码能力；6B 未迁移生产库、未解除 6A 安全阻塞，也未验证真实样本。

6C 发布准备、隔离误连防护、实时作业盘点、备份恢复预演及本机/LAN 两种部署状态见 [`android-release-6c.md`](android-release-6c.md)。生产仍运行旧全网监听实例，发布提交与实际本机/LAN 切换尚未完成；`IMPACT_UNCONFIRMED`、预检 `UNKNOWN`、`LOCAL_MODEL_VALIDATION_REQUIRED` 和 `REAL_SAMPLE_REQUIRED` 不随合成测试 PASS 消除。

### 6B 当前增量（合成/隔离，不覆盖下面历史基线）

| 链路 | 当前代码验证 | 仍有限制 |
| --- | --- | --- |
| Android 详情→选中单条→冻结结果集/快照 | 四类工件复用同一 key/Resolver，SMS 的真实 HTTP 捕获与来源回跳通过，SQLite Backup 快照可离线校验。 | 是 `android.db` 派生解析行，非原始手机库行；无原库 PK/WAL 定位。 |
| 快照→分析→人工复核→Report Evidence→R2 | 合成 SMS 经过现有执行器、测试模型桩、6A JWT/角色校验、现有审核/显式绑定与 R2 发布；citation 回到同一结果版本，旧报告输入仍可读。 | 未运行获准真实本地模型；不能把 mock 结论当现场分析。 |
| 前端与交付 | 无头 Chrome 点击单条→捕获→冻结面板，再点合成报告 `c001` 并跟随渲染出的链接回到同版；R2 引用键与来源面板有组件测试。离线包附选中结果数据库、复核；显式 `--report-root` 时附 R2 citation 映射。 | 浏览器中的 R2 数据是 mock，未独立走模型复核/发布；这些由隔离 HTTP 测试覆盖。生产仍 `BLOCKED`，真实样本 `REAL_SAMPLE_REQUIRED`。 |

记录日期：2026-09-26。范围为 `feature/android-forensics-report-structure`，执行前 HEAD `c7f1fc3c0281527fb635773515521ed23960aecc`。执行前工作区已有大量未提交改动（包括第三至第五阶段未跟踪文件），本轮未清理、迁移、重跑或删除已有 Task/检材。现场状态只是一时快照：当时健康接口报告 43 个 Task、0 个运行中，三个服务版本均为 1.0.0；不能把这些数值写成固定运行前提。隔离回归使用 `tempfile` 数据目录、随机本地端口和合成镜像；未重启现有服务。

## 真实链路判定

| 段 | 本轮状态 | 依据与不能声称的内容 |
| --- | --- | --- |
| A `android.db → Android 页面列表/详情/筛选` | **已实现且合成验证；现场入口受限** | 新增四类原生工件的只读 Reader/API/UI，任务记录确定库路径，白名单查询、分页、详情；检索词置于 POST 请求体而非 URL，Wi-Fi 密钥在网页返回中遮盖。合成短信正文/重复行、联系人、应用、Wi-Fi 与前端组件测试通过。新内容 API 默认 503，需可信入口注入 `TRACELENS_FIELD_API_TOKEN`；不能由网页保存令牌。旧 MIUI 页面仍独立。当前部署仍不满足敏感数据准入。 |
| B `android.db → 来源文件核对` | **文件候选来源可查；逐条来源缺少适配** | `android_source_coverage` 能提供候选 Android 路径；归档/镜像 provenance 可提供原始成员/分区/文件哈希。现有 `sms_messages`、`contacts`、`installed_packages`、`wifi_networks` 表没有每行的原始数据库路径与主键；新详情明确标 `candidate_file_not_row`、`verified_row_source=false`，多候选时不指定文件。读取 DB bundle/WAL 不等于已定位 WAL frame。不能声称精确返回原库那一行。 |
| C `Android 工件 → Investigation/二次分析/人工复核` | **缺少适配** | `EvidenceResolver` 只接受 `file:`、`cluster:v1:`；`investigation.db` 的 evidence_type CHECK 也仅允许 file/cluster，snapshot、prompt、grounding、报告生成都按这两类处理。Android Task 挂接 task_id、读到 `android.db`、或存在文件级 provenance 均不等于进入调查域。本轮没有伪造 files/events 或新增半套 evidence key；逐条短信→快照→分析→复核链**未验收**。如要接通，需另做版本化 artifact key 与旧报告兼容迁移的完整验收。无本地模型也不能把 mock 当真实 AI。 |
| D `已选择证据 → 现有报告/结果导出` | **现有文件/事件链已实现但本轮未验证 Android 引用；Android 记录级引用缺少适配** | `intelligence_report.py` 可按 Android 表读取通讯录、短信、应用等确定性章节，但不是 Investigation 中已选择的一条短信的冻结引用。新增离线结果包可交付 `android.db` 四类表与 coverage，不等于现有最终报告可引用单条 Android 工件。 |
| E HTML `records.db → 查询/来源回跳/结果导出` | **已实现且合成验证** | 保留 `source_type=external_html_report` 和独立 `records.db`；既有记录查询/分类/统计/转义原页定位不变。新增离线包通过 SQLite Backup API 交付 records 快照、JSONL、coverage、manifest、warnings、SHA-256；合成缺附件导入维持 PARTIAL，不因打包改为 COMPLETE。现有本地项目方报告（前阶段测试）22 页/7,404 条/缺附件 1 条、PARTIAL，本轮没有重新导入或复制敏感报告。 |

### 证据语义与覆盖口径

- AndroidAnalyzer 工件：`android.db`，本轮只读查询。第三方报告：`records.db`，`source_type=external_html_report`，是派生记录。两者不能互称。
- `android_source_coverage` 一行对应一个预设候选来源/解析阶段，不是所有 Android 文件的总量。`FOUND` 与 `PARSED` 是过程状态，不能相加当成独立证据数；`NOT_FOUND` 仅表示候选路径未命中，不证明设备没有该类数据。UI 不给 `PARSED/(PARSED+NOT_FOUND)` “完整率”。
- 旧解析器不存 SMS/联系人原库 PK、账号/Android user 的逐条关联。不能编造行号、磁盘偏移或 WAL frame。单一候选路径只展示为候选文件；有多个候选时不做唯一关联。
- 加密状态需区分文件系统支持、fscrypt 标记、fstab 声明、内容实际可读、缺密钥与未知。`tests/integration/test_android_filesystem_image_e2e.py` 的 locked 样本仅为 `SYNTHETIC_ENCRYPTION_METADATA_ONLY`，只验证拒绝与覆盖状态，不证明手机 FBE 兼容。super-only 规范化不等于用户数据分析。Task `completed` 是程序状态，不是目标工件验收通过。

## 合成输入与可复验结果

独立预期由测试代码中的固定文字/字段定义，而非从解析输出反推：短信 `(10086, fixture-message-1, 1700000000000, type 1)`、`(10010, fixture-message-2, 1700000001000, type 2)`；联系人 `Fixture Contact/12345`；应用 `com.fixture.app/version 1`；Wi-Fi `FixtureWifi`。内容比较使用多重集合，保留合法重复记录。

| 输入/路径 | 预期 → 实际 | 差异/证据 |
| --- | --- | --- |
| DIR、ZIP、TAR、7z、AB → AndroidAnalyzer | SMS 2、联系人 1、应用 1、Wi-Fi 1，字段多重集合一致 → **一致** | `tests/integration/test_android_container_cli_e2e.py`，本轮在隔离目录用 `build/forensic_analyzer` 执行。目录/容器内 WAL 的第二条短信进入结果。 |
| EXT4、F2FS 单分区；完整 RAW/E01 + EXT4/F2FS | 各 SMS 2/联系人 1/应用 1/Wi-Fi 1，字段多重集合一致 → **一致** | `tests/integration/test_android_filesystem_image_e2e.py`；6 条各有 6 条文件级 provenance。合成镜像 128–300 MiB，非 TB。 |
| sparse EXT4/F2FS userdata HTTP Task | raw 与 sparse 内容、counts、coverage、provenance 一致 → **一致** | `tests/integration/test_android_container_http_e2e.py` 隔离 Task；转换 0.185s/0.372s 仅是转换子步骤，不含全量哈希/预检/解析/导出。 |
| raw/sparse super、完整 RAW/E01 内 super | 三个合成逻辑分区 SHA-256 相同；预期用户工件为 0 → **一致** | 同一 HTTP 测试；`userdata=NOT_PRESENT_IN_SOURCE`，EROFS 系统分区 `UNSUPPORTED_FILESYSTEM`。来源改变返回 HTTP 409。 |
| 本轮独立结果包测试 | 合成 SQLite/WAL 中 3 条短信（含重复 2 条）、联系人/应用/Wi-Fi 各 1 → 快照与 JSONL **一致** | `python_service/tests/unit/test_android_field_delivery.py`；源连接保持开启且 WAL 未 checkpoint，离线校验可打开快照并校验文件 SHA-256，篡改后失败。另有 HTML 合成缺附件 PARTIAL 用例。 |

前端 `vitest` 的 Android 工件/覆盖组件共 6 项通过，Vite 生产构建成功。`scripts/browser_e2e.py` 在独立 `127.0.0.1` mock 服务与无头 Chrome 中通过 Android、Files、Investigation、Case Intelligence、Knowledge Graph 页面冒烟；Android 页面检测到原生工件卡片，所有路线均无错误边界。它不连接真实后端，不能代替真实样本端到端验收。

尚未覆盖：userdata 根/全文件树根及包装目录、Android user 0/其他 user、多账号、中文长路径、未知 schema/空目标表/缺列、提取成功但解析器不支持、取消/超时/磁盘不足等系统性差分与故障注入。不能据此声称这些构型已验收。上述六镜像合成脚本用 `/usr/bin/time -v` 复跑：环境 32 vCPU/15 GiB RAM，`/tmp` 所在盘测试前可用约 944 GiB；脚本含生成镜像与分析总墙钟 26.39 秒、user 7.13 秒、system 3.67 秒、最大 RSS 161,500 KiB，文件系统输出 898,008 个 512B 单位。该 RSS 是进程/子进程工具测量，不是整机峰值内存；文件系统输出量不是峰值临时磁盘占用。全量哈希、预检、规范化、遍历、解析、可选 AI、打包的分段 CPU/RAM/峰值磁盘仍未全部记录，TB 级未测，不能外推上述秒数。

## 离线结果包

仅在受控主机本地使用 `scripts/android_field_package.py`。Task 模式可通过 `--task-id` 从 **127.0.0.1** 上的现有 C++ 服务读取可信 Task 记录（拒绝非 loopback 和重定向），或在断网机器用本地 `--task-record`；报告模式传入已导入的 import ID。路径不来自浏览器/任意 HTTP 参数。输出必须是不存在的新目录，默认文件权限受 `umask 077` 限制。不要把含正文的结果包提交 Git/公开 CI。示例：

```bash
python_service/.venv/bin/python scripts/android_field_package.py --task-id <task_id> --output /受控目录/交付包-001
python_service/.venv/bin/python scripts/android_field_package.py --task-record /受控目录/task-record.json --output /受控目录/交付包-离线
python_service/.venv/bin/python scripts/android_field_package.py --import-id <32位import_id> --output /受控目录/报告包-001
python_service/.venv/bin/python scripts/android_field_package.py --verify /受控目录/交付包-001
```

包内 `android.db`/`records.db` 是 SQLite Backup API 的一致性快照，不直接复制仍写入的主库；`records.jsonl` 从该快照流式导出。包含 coverage、原预检/规范化 manifest（存在时）、warnings、README、`package_manifest.json` 的逐文件 SHA-256/大小、快照哈希、生成 UTC 时间、源码 commit。`toolchain_inventory.json` 记录 commit/dirty 标记、相关源码和当前安装二进制哈希、选定 Python 依赖版本及 `THIRD_PARTY_LICENSES.md` 的哈希；它**不是完整 SBOM**，正式再分发需经批准的全依赖许可清单。清单不自哈希；外部交接仍须对清单文件另行签名/哈希。没有原始镜像/敏感附件；缺附件仍是 PARTIAL。失败时留下 `INCOMPLETE` 标志而非有效包。源镜像哈希仅沿用已有预检 manifest，不把派生数据库哈希冒充原始检材哈希。

## 敏感检材准入：BLOCKED

`python_service/.venv/bin/python scripts/android_field_check.py` 只检查监听/匿名 HTTP 状态，不读取响应体或输出凭据。2026-09-26 实际结果：8666、8090、8091 均监听 `0.0.0.0`；8666 `/api/tasks` 与 8090 `/api/android-report/imports` 无认证返回 200；8091 `/api/tasks` 返回 401。`.env` 中 `LLM_BASE_URL`/文字/视觉配置指向 `api.deepseek.com`，embedding 指向局域网主机；离线模式未明确启用。C++ 与 Python 的 LLM/embedding/Graphiti/OSS 路径尚无经本轮验证的统一出站拦截。**当前运行实例不允许导入真实敏感检材。** 前端登录、CORS 或隐藏按钮不足以代替后端认证。

本轮新增的 Android 逐条内容 API 默认 503，只有至少 32 字符的 `TRACELENS_FIELD_API_TOKEN` 由受信 HTTPS 反代注入时开放；这**只保护新路由**，不修复旧 API。现场应先完成全部入口/后端端口的受控监听或认证、授权本地模型端点白名单、系统级出站封锁及只读渗透复核，再重新运行检查并人工审批。无模型时合成包/确定性查询/统计不需要外部 AI。不要在浏览器或普通日志中存令牌；检材文本是数据，不能执行其中指令。当前脚本的 `MANUAL_REVIEW_REQUIRED` 也不是自动安全通过。

## 真实样本独立验收入口

从 [`android-field-sample-manifest.example.json`](android-field-sample-manifest.example.json) 复制模板到**仓库外**受控目录，显式填写授权样本路径、样本 ID、分段清单/哈希、提取工具和版本、容器/文件系统、可读/加密事实、目标工件、预期字段和美亚对照范围。不得自动扫描机器未知检材。美亚结果只有同检材、同账号、同时间/删除/附件范围时才可比较；差异按缺件、加密、路径、schema、解析器、去重/过滤、时间、附件分别归因。当前**无项目方授权原始镜像样本：`REAL_SAMPLE_REQUIRED`**。已有 HTML 报告仅证明对应派生模板，不替代真实镜像验收。M01/MFC/EROFS/多段 EWF/新 LP 与厂商 F2FS 特性不在本阶段扩大支持。

本地入口示例：`python_service/.venv/bin/python scripts/android_field_sample_manifest.py --manifest /受控目录/sample.json --full-hash`。只检查显式列出的文件与哈希，不扫描其他路径、不上传、不自动创建 Task；不加 `--full-hash` 时不会读取大检材全文，结果为 `HASH_NOT_CHECKED`，绝不是已验收。

## 本轮剩余阻塞（按优先级）

1. **P0 安全准入**：现有 8666/8090 匿名可读且后端监听全网，存在可出站模型配置；未完成全链鉴权、隔离和出站封锁前不得处理敏感检材。
2. **P0 记录级调查链**：Android/HTML 记录没有版本化 Evidence key → snapshot → grounding → review → 最终报告引用 → 精确来源的完整协议。不能用 `file:` 伪装数据库记录。此阶段只补只读展示/交付，未达到请求的单条短信完整研判闭环。
3. **P1 逐条 provenance**：旧 parser 表缺原始 DB 表/PK、Android user/账号、来源文件逐行绑定；文件级 provenance 不能推出逐行定位。需合成 fixture 与真实结构证据后，再做可迁移的增量字段与旧任务回读。
4. **P1 现场差分/异常/性能**：真实样本、目录多账号变体、超时/取消/磁盘不足及 TB 级未验收。完整性能与资源测量待独立执行。
5. **P2 交接签名/许可证**：结果包哈希可复验，但没有独立数字签名；许可证清单和固定依赖参见既有 `THIRD_PARTY_LICENSES.md`/阶段文档，尚未形成每个运行二进制的签名清单。
