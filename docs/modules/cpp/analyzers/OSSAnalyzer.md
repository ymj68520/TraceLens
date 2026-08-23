# OSSAnalyzer（src/analyzers/OSSAnalyzer/）

> **一句话**：阿里云 OSS（对象存储）取证分析器——通过 AK/SK 直连 API 列举 Bucket 与对象，或离线分析已导出的本地目录/Inventory 清单/访问日志，把对象元数据与操作历史写入 oss.db 的三张表。
>
> **状态提示（先读这个）**：模块代码完整、有测试、已编译进二进制，但**当前无法从任何入口触达**——配套的 `/api/forensics/oss/*` HTTP 路由没有注册到服务器，且路由内部的分析任务还是占位实现。详见第 2 节。

## 1. 为什么有这个模块

云时代之后，"证据在现场"的假设不再成立。一个涉案系统的数据可能早已从本地磁盘搬到对象存储：备份数据包、导出的业务数据、甚至攻击者外传的赃物都可能躺在 OSS Bucket 里。对这类证据，取证问题有三个：**Bucket 里有什么**（对象清单与元数据）、**谁动过它**（访问日志里的 IP/操作/时间）、**什么值得下载**（按类型、大小、时间筛选）。这个模块就是围绕这三问设计的。

它支持四种取证姿势，覆盖"现场有网/无网"两种情形：API 直连（实连 OSS 拉元数据）、本地目录分析（分析已导出的 OSS 目录，离线）、Inventory 清单（OSS 定期生成的 CSV 对象清单，离线）、访问日志（OSS 开启日志功能后落盘的访问记录，离线）。API 模式只取**元数据**不下载对象本体——取证上先"编目"再决定下载什么，比盲目全量拉取务实得多。

架构分三层：`OSSClient`（`Client/OSSClient.cpp`，封装 `libs/aliyun-oss-cpp-sdk` 的 `AlibabaCloud::OSS::OssClient`，见第 12 行 include）负责连接与列举；`OSSAnalyzer`（`OSSAnalyzer.h:44`）做编排，按模式分派；`OSSAnalysisDatabase` 落 oss_objects/oss_access_logs/oss_buckets 三张表（建表语句在 `src/core/DatabaseManager/SQL/oss_sql.h`，初始化见 `Database/OSSAnalysisDatabase.cpp:32-34`，并在 bucket/key/时间戳/存储类型上建了索引方便查询）。模块自带 `README.md` 和 `OSSExportTypes.h`（导出类型定义），是文档相对齐全的模块。

## 2. 核心数据结构与接口

**连接配置**（`Common/OSSDataTypes.h:102-124`）：

```cpp
struct OSSConnectionConfig {
    std::string accessKeyId;        ///< Access Key ID
    std::string accessKeySecret;    ///< Access Key Secret
    std::string securityToken;      ///< STS安全令牌（可选）
    std::string endpoint;           ///< OSS Endpoint
    std::string bucket;             ///< 默认Bucket名称
    std::string region;             ///< 地域

    int connectTimeoutMs = 10000;   ///< 连接超时（毫秒）
    int requestTimeoutMs = 30000;   ///< 请求超时（毫秒）
    int maxConnections = 16;        ///< 最大连接数

    bool useProxy = false;          ///< 是否使用代理
    std::string proxyHost;          ///< 代理主机
    int proxyPort = 0;              ///< 代理端口

    bool enableCrc = true;          ///< 启用CRC校验
    bool enableMD5 = false;         ///< 启用MD5校验
};
```

取证视角的字段解读：`accessKeyId/Secret` 是长期凭证（高危，建议测试环境用完即废），`securityToken` 支持 STS 临时令牌（有期限，泄露面小，调查方调证常用）；超时与连接数直接传给 SDK 的 ClientConfiguration；代理字段是给"只能经代理出网"的取证工作站准备的。

**核心接口清单**（`OSSAnalyzer.h:46-187`）：

| 方法 | 语义 | 调用方 | 失败行为 |
|------|------|--------|---------|
| `OSSAnalyzer(config, dbManager)` + `bool initialize()` | 建客户端与 oss.db | 预期：OSS 路由的 job 执行体（现状占位，见第 2 节现状链条） | false + lastError |
| `void analyzeOSSData()` | 按配置自动分派四种模式 | 同上 | 每模式独立 try |
| `bool analyzeFromAPI(bucket="", prefix="")` | API 直连：Bucket 信息 + 流式列举对象 | 同上 | 客户端未初始化/bucket 为空即 false |
| `bool analyzeFromLocalDirectory(localDir, bucket="local")` | 递归遍历导出目录 | 同上 | 目录不存在 false |
| `bool analyzeFromInventory(csvPath)` | 解析 OSS Inventory CSV | 同上 | 同上 |
| `bool analyzeAccessLogs(logPath)` | 解析访问日志（单文件或目录） | 同上 | 同上 |
| `bool fetchAndAnalyzeAccessLogs(bucket, start=0, end=0)` | 从 OSS 拉取并分析日志 | 同上 | 未初始化 false |
| `getAllObjects/getObjectsByBucket/getObjectsByExtension/getAccessLogs/getAnalysisSummary` | 查询接口 | 查询路由（同为未注册状态） | — |

## 3. 在流水线中的位置（以及为什么现在到不了）

按设计意图，它是 HTTP 服务的一个独立功能（不进 TaskManager 的任务流水线）：前端发起 `POST /api/forensics/oss/analyze`，`OSSAnalysisRoutes` 生成 `oss-xxxxxxxx` 形式的 job_id，后台线程跑分析，前端轮询 `/analyze/status`。查询侧还有 `/api/forensics/oss/objects|logs|summary|stats/*|buckets` 等路由（`routes/OSSQueryRoutes.cpp`、`OSSStatsRoutes.cpp`），另有 `/ai/filter`、`/ai/analyze` 两个 AI 路由设计为转发 Python 服务。

但验证源码得到的现状链条是：

1. **路由未注册**：`HTTPServer` 构造函数只实例化 Task/Forensics/System/Search/CaseCRUD/Filter 六组路由（`HTTPserver.cpp:63-75`，`HTTPserver.h:20-25` 的 include 清单同样没有 OSS）。注册逻辑存在于 `OSSRoutes.cpp`/`OSSRoutes_new.cpp`，但没有任何人调用它们——前端 OSS 页面请求会落到 SPA 兜底路由，拿到的是 404。
2. **路由内部也未完工**：即便注册了，`run_analysis_job` 目前是"睡 100ms 然后标记完成"的占位（`OSSAnalysisRoutes.cpp:222-230` 的注释原话 "Placeholder implementation"）；AI 三条路由直接返回 503"Python service not yet integrated"；下载对象返回 501 Not Implemented。
3. **因此 OSSAnalyzer 类没有任何生产调用方**——它只在单元测试（`tests/UnitTest/test_oss_analyzer_gtest.cpp`）里被构造过。

换言之：**分析器本身（OSSClient/OSSAnalyzer/oss.db）是成品，外层的接线（路由注册 + job 执行体）是半成品**。另外注意：HTTP 任务里 SERVER_CLOUD 场景产出的 `<镜像>_oss.db` 与本模块无关（那是 LinuxFilesAnalyzer 借用了 oss.db 这个文件名，见 `TaskManagerAnalysis.cpp:508-510`）；本模块的 oss.db 是独立的库，schema 来自 `oss_sql.h`。

预期使用方式（API 就绪）：构造 `OSSConnectionConfig` → `OSSAnalyzer(config, nullptr)` → `initialize()` + `setOutputDbPath()` → `analyzeOSSData()`（API 模式）或 `analyzeFromLocalDirectory/analyzeFromInventory/analyzeAccessLogs`（离线模式）。

## 4. 证据来源与覆盖范围

四种模式各自看到不同的证据面：

| 模式 | 证据来源 | 产出 |
|------|---------|------|
| API 直连（`analyzeFromAPI`） | 实时连接 OSS：`getBucketInfo` + `listAllObjects` 分页列举（支持 prefix 过滤） | oss_buckets（Bucket 元数据与统计）、oss_objects（每个对象的 key/大小/ETag/存储类型/最后修改时间） |
| 本地目录（`analyzeFromLocalDirectory`） | 递归遍历导出目录，相对路径即对象 key（反斜杠归一为 `/`） | oss_objects（文件级元数据，虚拟 bucket 名默认 "local"） |
| Inventory 清单（`analyzeFromInventory`） | OSS Inventory 定期生成的 CSV | oss_objects（清单行→对象记录） |
| 访问日志（`analyzeAccessLogs`） | OSS 日志文件（单文件或目录批量） | oss_access_logs（remote_ip/时间/方法/object_key/状态码/字节数/referer/UA） |

认证侧支持 AK/SK 长期凭证与 STS 临时令牌（`securityToken` 字段），连接超时/最大连接数可配——这些在 `OSSClient::initialize` 里传给 SDK。

### 4.1 产出表结构说明（oss.db 三张表 + 两个视图）

schema 全部在 `src/core/DatabaseManager/SQL/oss_sql.h`：

| 表 | 关键列（真实名） | 取证含义 |
|----|------------------|---------|
| `oss_objects`（:16-40） | `bucket/key/size/etag/last_modified/storage_class/content_type/owner/user_metadata/version_id/is_deleted/md5_hash/analyzed_at` + 6 个 `llm_*` 列 | 对象编目：`UNIQUE(bucket,key,version_id)` 支撑增量重扫；ETag/MD5 双哈希列供完整性比对；`is_deleted` 标记"清单里消失的对象"（版本化 Bucket 可追删改史）；`llm_is_relevant` 是为 AI 筛选预留的判定列 |
| `oss_access_logs`（:49-69） | `request_id/timestamp/operation/bucket/object_key/remote_ip/user_agent/accesser_id/http_status/bytes_sent/object_size/time_taken_ms/referer/host/signature_version/ssl_enabled` | 操作史：`accesser_id`（OSS 的主账号/子账号标识）能区分"谁"在动；四个索引（timestamp/operation/object_key/remote_ip）支撑时间窗、按 IP、按对象的典型查询 |
| `oss_buckets`（:78-96） | `name/region/endpoint/acl/owner/versioning_enabled/logging_enabled/logging_bucket/logging_prefix/object_count/total_size/analyzed_at` | Bucket 档案：`logging_enabled + logging_bucket/prefix` 告诉你访问日志落在哪（取证调证的第一步常是确认日志是否开启） |
| 视图 `oss_objects_summary` / `oss_access_timeline`（:245-265） | 按 bucket 聚合对象数/总量/新旧；按日期+操作聚合计数与流量 | 现成的统计视图，查询路由直接 SELECT |

## 5. 解析机制走读

**链路一：API 模式的对象编目（`analyzeFromAPI`，`Core/OSSAnalyzerCore.cpp:66-122`）。** 先取 Bucket 信息落 oss_buckets，然后开一个事务，`client_->listAllObjects` 流式回调逐对象插入，最后用实际对象数回写 Bucket 统计。分页列举的底层（`Client/OSSClient.cpp:285-341`）：

```cpp
// OSSClient.cpp:300-334（节选）
    while (isTruncated) {
        ListObjectsRequest request(bucketName);
        if (!prefix.empty()) request.setPrefix(prefix);
        if (!marker.empty()) request.setMarker(marker);
        request.setMaxKeys(1000);

        auto outcome = impl_->client->ListObjects(request);
        if (!outcome.isSuccess()) {
            setError("Failed to list objects: " + outcome.error().Message());
            break;
        }

        for (const auto& obj : outcome.result().ObjectSummarys()) {
            OSSObjectInfo info;
            info.bucket = bucketName;
            info.key = obj.Key();
            info.size = obj.Size();
            info.etag = obj.ETag();
            info.lastModified = parseOssDateTime(obj.LastModified());
            info.storageClass = obj.StorageClass();
            info.owner = obj.Owner().Id();
            callback(info);
            totalCount++;
        }

        isTruncated = outcome.result().IsTruncated();
        marker = outcome.result().NextMarker();
        if (progressCallback) {
            progressCallback(totalCount, -1); // Total unknown
        }
    }
```

做什么：marker 式分页循环——每页最多 1000 个对象，`IsTruncated` 为真就用 `NextMarker` 翻页，直到拉完。为什么流式回调而不是先攒全再返回：百万级对象的 Bucket 攒全量列表会吃几个 GB 内存，回调让上层（`analyzeFromAPI`）边收边插库、每 100 个报一次进度、回调里给每条记录盖上 `analyzedAt` 时间戳。错误路径：某页失败 `setError` 后 break——已收的部分仍保留（外层事务此时还未 commit，`analyzeFromAPI` 的 `commitTransaction` 在回调全部结束后才执行，半途网络断掉不会留半本账）。

**链路二：访问日志的行解析（`parseAccessLogLine`，`Core/OSSAnalyzerCore.cpp:374-410`）。**

```cpp
// OSSAnalyzerCore.cpp:378-401（节选）
    // OSS日志格式: IP - - [timestamp] "METHOD /path HTTP/version" status bytes "referer" "user-agent"
    std::regex logPattern(R"regex((\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"([^"]+)"\s+(\d+)\s+(\d+)\s+"([^"]*)"\s+"([^"]*)")regex");
    std::smatch match;

    if (std::regex_search(line, match, logPattern) && match.size() >= 8) {
        entry.remoteIP = match[1];
        // 时间戳解析简化
        entry.timestamp = 0; // 实际应解析 match[2]

        // 解析请求行
        std::string request = match[3];
        std::istringstream reqStream(request);
        std::string method, path;
        reqStream >> method >> path;
        entry.operation = method;
        entry.objectKey = path;
```

做什么：OSS 访问日志是类 Apache Combined 格式（空格分隔、请求行与引号字段包裹），一个正则一次捕获八个字段：IP、时间、请求行、状态、字节数、referer、UA。请求行再拆出方法（GET/PUT/DELETE→operation）与对象路径（→objectKey）。`requestId` 用整行的 `std::hash` 合成（`"log_" + hash`），保证无真实请求 ID 时行与行可区分。诚实标注：时间戳字段当前**没有真正解析**（`entry.timestamp = 0; // 实际应解析 match[2]`，第 388 行），做时间线排序前需要先补上这段——这是激活路径上的第一优先 TODO。

**链路三：离线目录模式（`parseLocalDirectory`，`Core/OSSAnalyzerCore.cpp:142-179`）。** 事务内递归遍历，把每个文件的 `fs` 元数据（大小、修改时间）包装成 `OSSObjectInfo`，相对路径拼上 prefix 作为对象 key——这使"从 OSS 同步下来的目录"和"API 拉到的清单"在 oss_objects 里结构一致，后续查询/统计/AI 过滤不用区分来源。反斜杠归一为 `/`（第 154-155 行）是 Windows 兼容处理；遍历结束同样回写一条虚拟 Bucket 统计记录（objectCount/totalSize）。

## 6. 与 LLM 的协作（设计中的 Python 协作）

设计上 OSS 的 AI 能力放在 Python 服务侧：`/api/forensics/oss/ai/filter`（AI 筛选相关文件）与 `/ai/analyze`，注释指向 `python_service/httpserver/routes/oss_analysis.py`。C++ 侧目前只返回 503 占位（`OSSAnalysisRoutes.cpp:233-290`），真正的协作尚未发生。可参照的现成模式是 OfficeAnalyzer 经 `PYTHON_SERVICE_URL` 调 Python `/api/office/parse` 的跨服务调用。数据库侧其实已备好接口：`oss_sql.h:171-201` 的 `UPDATE_OSS_OBJECT_LLM_ANALYSIS`（回写 5+1 个 llm 列）与 `SELECT_OSS_OBJECTS_FOR_FILTERING`（取未分析行）——SQL 都写好了，只差调用方。

## 7. 与其他模块的协作 / 注意事项

- **依赖**：阿里云 OSS C++ SDK（`libs/aliyun-oss-cpp-sdk`，编译进项目）、libcurl/openssl（SDK 传递依赖）。离线模式完全不需要 SDK 可达的网络。
- **激活路径（若要投入使用）**：最小改动是在 `HTTPserver` 构造里实例化 `OSSRoutes`（一行），并把 `run_analysis_job` 的占位换成构造 `OSSAnalyzer` 跑 `analyzeOSSData()`；凭证从请求或 .env 读（参考其他模块读 `ConfigManager` 的方式）。别忘 `parseAccessLogLine` 的时间戳解析。
- **命名混淆**：本项目里 "oss.db" 有两个含义——任务流水线的 SERVER_CLOUD 结果库（Linux 工件）与本模块的 OSS 对象库。查询代码时要看清上下文。
- **AI 路由的 Python 侧**：`python_service` 是否已有对应路由实现，决定了 AI 功能的距离；C++ 注释里引用的 Tasks 8-11 是实现计划编号，不是已完成功能。

## 8. 如何验证与扩展

- 测试：`tests/UnitTest/test_oss_analyzer_gtest.cpp` 覆盖枚举值、连接配置默认值、oss.db 初始化、对象与访问日志的插入/查询（含按 bucket 过滤）。API 模式无法离线测，验证需真实 AK/SK + 测试 Bucket。
- 加新证据模式：在 `OSSAnalyzer` 加 `analyzeFromXxx`（参照 `analyzeFromInventory` 的 CSV 读取），产出统一塞进 `OSSObjectInfo`/`OSSAccessLogEntry` 即可复用全部查询与导出。
- 补时间线能力：完成 `parseAccessLogLine` 的 timestamp 解析后，`oss_access_logs` 的四个索引（timestamp/operation/object_key/remote_ip）就能支撑"按时间窗找操作"的典型取证查询；`oss_access_timeline` 视图也会随之有意义。

**最后更新**: 2026-08-23（技术深化：叙事结构保留，补核心代码与逐段解释）
