# AndroidLLMAnalysisService（src/network/HTTPServer/AndroidLLMAnalysisService{,_ArtifactAnalyzers,_Database}.cpp）

> **一句话**：Linux/Windows 同族的 Android 工件级 LLM 批量分析器——遍历 `_android.db` 的 14 类工件表（短信、微信/WhatsApp/Telegram 消息、联系人、通话记录、MIUI 备份清单、已装应用、微信/QQ 结构化记录、系统日志、设备标识、WiFi），逐条生成 summary/description/keywords 写回 llm_* 列，由 AndroidAnalyzer 在场景分析末尾调用。

骨架与 [LinuxLLMAnalysisService](./LinuxLLMAnalysisService.md) 完全同构（头注释自述 "Mirrors LinuxLLMAnalysisService / WindowsLLMAnalysisService"，AndroidLLMAnalysisService.h:25-28）。本文只讲 Android 特有之处，四件套/记录即 JSON/增量 PENDING 等通用机制不再重复。

## 1. 为什么有这个模块

Android 取证的证据主体是**应用级结构化数据**：一条微信消息、一条通话记录、一个 WiFi 指纹——AndroidAnalyzer 已把它们解析进 `_android.db` 各专属表，但"原始行 → 调查员可读解读"仍缺。本模块补齐这一步：每行工件过一次文本 LLM，产出三段式注解，供 `/android` 结果页与后续智能分析直接消费。

## 2. 在系统中的位置

```
TaskManager::start_analysis PLATFORM_ANALYSIS 阶段
  ├─ TSK 管线 scenario=ANDROID (TaskManagerAnalysis.cpp:460-464)
  │     └─ AndroidAnalyzer::analyzeAndroidData()
  └─ 逻辑提取管线 dir/zip/miui-backup (TaskManagerAnalysis.cpp:624-643)
        └─ 同一个 analyzeAndroidData()
              └─ 末尾 Phase 3: analyzeWithLLM()          (AndroidAnalyzerCore.cpp:253-254)
                    └─ AndroidLLMAnalysisService::analyzeAndroidArtifacts(_android.db)
                                                                (AndroidAnalyzerCore.cpp:322)
```

**查证结论（活跃性）**：两条 Android 路径（物理镜像与逻辑提取）都汇入 `analyzeAndroidData()`，LLM 注解随之**必然被调用**——不存在"未接线"问题；TaskManager 不直接调用它，与 Linux/Windows 同样的间接调用结构。

## 3. 核心概念与设计

### 3.1 表驱动四件套（Android 版）

前两件映射（_Database.cpp）：

```cpp
// src/network/HTTPServer/AndroidLLMAnalysisService_Database.cpp:102-120
std::string AndroidLLMAnalysisService::getTableNameForType(ArtifactType type) {
    switch (type) {
        case ArtifactType::SMS: return "sms_messages";
        case ArtifactType::WECHAT_MESSAGE: return "wechat_messages";
        case ArtifactType::WHATSAPP: return "whatsapp_messages";
        case ArtifactType::TELEGRAM: return "telegram_messages";
        case ArtifactType::CONTACT: return "contacts";
        case ArtifactType::CALL_LOG: return "call_logs";
        case ArtifactType::MIUI_MANIFEST: return "miui_backup_manifest";
        case ArtifactType::INSTALLED_APP: return "installed_apps";
        case ArtifactType::WECHAT_SQLITE_RECORD: return "wechat_sqlite_records";
        case ArtifactType::WECHAT_KV_RECORD: return "wechat_kv_records";
        case ArtifactType::QQNT_SQLITE_RECORD: return "qqnt_sqlite_records";
        case ArtifactType::SYSTEM_LOG: return "system_logs";
        case ArtifactType::DEVICE_IDENTIFIER: return "device_identifiers";
        case ArtifactType::WIFI_NETWORK: return "wifi_networks";
        default: return "";
    }
}
```

第三件 PENDING SELECT 常量（`getSelectSQLForType`，:122-141 返回 `android_analysis_sql_llm::SELECT_*_PENDING_ANALYSIS`），以短信为例：

```cpp
// src/core/DatabaseManager/SQL/android_analysis_sql_llm.h:20-22
inline constexpr const char* SELECT_SMS_PENDING_ANALYSIS =
    "SELECT id, address, person, date, date_sent, type, body, service_center "
    "FROM sms_messages WHERE llm_analyzed_at IS NULL ORDER BY date DESC LIMIT ?;";
```

与其他平台同款约定：首列 id 作回写键、`llm_analyzed_at IS NULL` 排除已分析行（重跑增量续作）、ORDER BY 时间倒序 + LIMIT。第四件是每类型一个 prompt 函数（_ArtifactAnalyzers.cpp）；不少类型**共用泛型助手**，如 `analyzeGenericMessageArtifact(artifact, "WhatsApp")`、`analyzeSqliteRecordArtifact(artifact, "WeChat"/"QQ")`——即时通讯类工件的 prompt 结构高度相似，Android 版把"平台名"参数化了（区别于 Linux/Windows 每类型独立函数）。`storeArtifactAnalysis`（Database.cpp:17-56）统一 `UPDATE <表> SET llm_summary/…/llm_model_used WHERE id=?`，keywords 逗号拼接（:24-29）。

### 3.2 与 Linux/Windows 的关键差异：可用性门控

Linux/Windows 版头文件标注 "MANDATORY analysis step"，**只要场景跑了注解就跑**，LLM 不可用时逐条失败调用（拖慢平台阶段）。Android 版**没有**这条 MANDATORY 注释，并在调用方加了两道自动跳过：

```cpp
// src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp:260-290（节选）
void AndroidAnalyzer::analyzeWithLLM() {
    // Skip condition 1: user explicitly requested --no-ai.
    if (skipAI_) {
        std::cout << "AI analysis skipped (--no-ai)." << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_LLM_SKIPPED", "AI analysis skipped via --no-ai flag");
        return;
    }

    // Skip condition 2: no LLM endpoint configured → auto-skip. The local LLM
    // servers (LM Studio / Ollama / vLLM) the C++ LLMClient targets do not
    // require an API key (no Authorization header is sent), so the gate is the
    // base URL rather than the key. This keeps Android consistent with the
    // Linux/Windows analyzers' gate after their key-based check was relaxed.
    // ...
        if (configManager.getTextBaseUrl().empty() && configManager.getLLMBaseUrl().empty()) {
            std::cout << "AI analysis skipped (no LLM_BASE_URL configured). "
                      << "Structured analysis results in android tables are unaffected." << std::endl;
            AuditLog::instance().log("SYSTEM", "ANDROID_LLM_SKIPPED",
                "No LLM_BASE_URL configured, skipping LLM analysis");
            return;
        }
```

两道门：① `skipAI_`（用户 `--no-ai`）→ 跳过并写 `ANDROID_LLM_SKIPPED` 审计；② **未配置 LLM 端点**（text 与 llm 的 base URL 都为空）→ 自动跳过——注释明说本地 LLM（LM Studio/Ollama/vLLM）无需 API key，所以门控看 URL 而非 key。

效果：Android 在无 LLM 环境下不烧失败调用，与 Linux 的行为**不一致**（Linux 会逐条超时失败后静默返回 0）。这是同族三兄弟里唯一的可用性门控差异，排障时别拿 Linux 的表现套 Android。

任务级 `llm_analyze` 开关同样**不门控**本服务：TMA 注释直言 Android 分析器已在 analyzeAndroidData 内部做过工件级 LLM，`llm_analyze` 只补一条进度说明（TaskManagerAnalysis.cpp:162-172）。

### 3.3 选项分组

`AnalysisOptions`（h:56-63）5 个 include 开关默认全开、每类上限 1000：includeMessages（SMS+微信+WhatsApp+Telegram 四表）、includeContacts（联系人+通话）、includeMiui（备份清单+已装应用）、includeWechatEvidence（微信 sqlite/kv + QQNT 三表）、includeSystem（日志+设备标识+WiFi）。调用方硬编码全开（AndroidAnalyzerCore.cpp:312-317）——分组目前是"可关"而非"被配置"。

## 4. 核心接口清单

| 方法（真实签名） | 语义 | 调用方 | 失败行为 |
|---|---|---|---|
| `bool initialize()` | 惰性建文本模型 ModelRouter（:19-42） | 所有方法首行 | 异常返回 false → ANDROID_LLM_INIT_FAILED 审计 |
| `int analyzeAndroidArtifacts(androidDbPath, options, cb)` | 按 5 组开关调度 14 类型 | AndroidAnalyzerCore.cpp:322（唯一） | LLM 挂了逐条失败、返回 0，任务不受影响 |
| `int analyzeArtifactType(androidDbPath, type, maxArtifacts, cb)` | 单类型全流程（:109-207），LIMIT 内联替换（Database.cpp:66-70） | 上者 | 单条异常仅 stderr 并继续（:200-202） |
| `storeArtifactAnalysis / getArtifactsFromDatabase / 两映射`（private，_Database.cpp） | 与 Linux/Windows 同构 | 内部 | 同族一致 |

## 5. 工作流程走读

`analyzeAndroidArtifacts`（AndroidLLMAnalysisService.cpp:44-107）：惰性 initialize（ConfigManager 取文本模型建 ModelRouter，:19-42）→ 按开关逐类调 `analyzeArtifactType`。后者的类型路由（节选）：

```cpp
// src/network/HTTPServer/AndroidLLMAnalysisService.cpp:144-191（节选）
try {
    AnalysisResult result;
    switch (artifactType) {
        case ArtifactType::SMS:
            result = analyzeSmsArtifact(artifact);
            break;
        case ArtifactType::WHATSAPP:
            result = analyzeGenericMessageArtifact(artifact, "WhatsApp");
            break;
        case ArtifactType::TELEGRAM:
            result = analyzeGenericMessageArtifact(artifact, "Telegram");
            break;
        // ...
        case ArtifactType::WECHAT_SQLITE_RECORD:
            result = analyzeSqliteRecordArtifact(artifact, "WeChat");
            break;
        case ArtifactType::QQNT_SQLITE_RECORD:
            result = analyzeSqliteRecordArtifact(artifact, "QQ");
            break;
        // ...
        default:
            continue;
    }

    if (result.success) {
        if (storeArtifactAnalysis(db, tableName, artifact.id,
                                 result.summary, result.description,
                                 result.keywords, result.modelUsed)) {
            analyzed++;
        }
    }
} catch (const std::exception& e) {
    std::cerr << "Failed to analyze artifact " << artifact.id << ": " << e.what() << std::endl;
}
```

可见"泛型助手"在 switch 层的用法：同族消息类只换平台名字符串。调用端（AndroidAnalyzerCore.cpp:310-325）硬编码全开选项、传 stdout 进度回调，返回值写进 `ANDROID_LLM_ANALYSIS_COMPLETE` 审计。

失败模式：与 Linux 相同——LLM 挂了每条 chat 失败、函数返回 0，任务不受影响，表保持 PENDING 等下次增量（且 Android 有 §3.2 的端点预检，通常根本不会进入这条慢路）。

## 6. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| AndroidAnalyzer | 唯一调用方（analyzeWithLLM，AndroidAnalyzerCore.cpp:260-332），负责门控与审计 |
| AndroidAnalysisSQL（android_analysis_sql_llm） | PENDING SELECT 定义处；建表侧是 AndroidAnalyzer 的各解析阶段 |
| Linux/Windows 同族 | 同骨架；Android 多一层端点可用性门控 |
| ModelRouter / ConfigManager | 文本模型路由（同 Linux） |
| 前端 /android 相关视图 | 经路由读 llm_* 列渲染注解 |

## 7. 注意事项与已知问题

- **无 MANDATORY 标注 + 有端点门控**（§3.2）：同族行为差异，两份文档读者容易互相误导；跨平台排障先确认目标平台走哪条门控路径。
- **keywords 逗号拼接**：keywords 本身含逗号时无法还原数组（与 Linux/Windows 同款老问题）。
- **逐条同步调用、无批量**：千条级消息 × 每类 1000 上限，本地小模型也需可观时长；进度只有 stdout 回调（HTTP 进度条不感知细粒度，void 回调无取消通道）。
- **JSON 输出解析无重试**：模型不守格式该条作废，保持未分析状态。
- **include 分组无人消费**：调用方永远全开（§3.3），想按任务关掉某类（如跳过 wifi）需要先给 AnalysisOptions 接一条配置通路。

## 8. 如何验证与扩展

- **验证**：跑 android 场景任务后查 `_android.db`：`SELECT address, llm_summary FROM sms_messages WHERE llm_analyzed_at > 0 LIMIT 10`；再触发一次同库任务确认 PENDING 查询增量生效；把 LLM_BASE_URL 清空重跑，审计日志应出现 `ANDROID_LLM_SKIPPED`（门控生效）而非逐条失败。
- **扩展新工件类型**：① AndroidAnalyzer 建表填充；② android_analysis_sql_llm 加 `SELECT_X_PENDING_ANALYSIS`；③ Database.cpp 两个映射函数加 case；④ _ArtifactAnalyzers.cpp 加 prompt 函数（或复用泛型助手）并在 analyzeArtifactType 的 switch（AndroidLLMAnalysisService.cpp:146-191）注册；⑤ 要进默认执行集，还需在 analyzeAndroidArtifacts 的开关组（:63-104）加调用。

## 9. 14 表的 SELECT 列契约全表（二轮补全）

android_analysis_sql_llm.h:20-77 逐表列出进 prompt 的 JSON 字段与截断排序：

| 类型 | 表 | 进 prompt 的列 | ORDER BY（截断偏向） | 行号 |
|---|---|---|---|---|
| SMS | sms_messages | address, person, date, date_sent, type, body, service_center | date DESC | :20-22 |
| WECHAT_MESSAGE | wechat_messages | sender, receiver, content, timestamp, media_type, msg_type, is_send, chatroom_name, sender_nickname, talker | timestamp DESC | :24-27 |
| WHATSAPP | whatsapp_messages | sender, receiver, content, timestamp, media_type | timestamp DESC | :29-31 |
| TELEGRAM | telegram_messages | sender, receiver, content, timestamp, media_type | timestamp DESC | :33-35 |
| CONTACT | contacts | display_name, phone_number, email, account_type, account_name | display_name ASC | :37-39 |
| CALL_LOG | call_logs | number, date, duration, type, name, geocoded_location | date DESC | :41-43 |
| MIUI_MANIFEST | miui_backup_manifest | device, miui_version, backup_date, total_size, package_count, source_folder | backup_date DESC | :45-47 |
| INSTALLED_APP | installed_apps | package_name, display_name, version_code, version_name, data_size, sd_size, bak_type, manifest_summary | **data_size DESC（占空间大的优先）** | :49-51 |
| WECHAT_SQLITE_RECORD | wechat_sqlite_records | source_path, table_name, record_key, record_json, artifact_kind, is_sensitive | **is_sensitive DESC, id（敏感优先）** | :53-55 |
| WECHAT_KV_RECORD | wechat_kv_records | source_path, namespace, key, value_type, value_text, is_sensitive, parse_status | is_sensitive DESC, id | :57-61 |
| QQNT_SQLITE_RECORD | qqnt_sqlite_records | source_path, table_name, record_key, record_json, artifact_kind, is_sensitive | is_sensitive DESC, id | :62-64 |
| SYSTEM_LOG | system_logs | timestamp, log_level, tag, process, pid, message, log_file, log_source | timestamp DESC | :66-68 |
| DEVICE_IDENTIFIER | device_identifiers | identifier_type, value, package_name, source_path | id ASC | :70-72 |
| WIFI_NETWORK | wifi_networks | ssid, **pre_shared_key**, key_mgmt, last_connected | last_connected DESC | :74-76 |

三个取证语义值得点出：微信/QQ 结构化记录**敏感行优先**（is_sensitive DESC，注释明言"Prioritize sensitive tokens/identifiers (uin/imei/mac/device)"）——1000 条上限内先保住敏感证据；已装应用**按数据量降序**（大应用先分析）；WiFi 表把 **pre_shared_key（明文 WiFi 密码）直接放进 prompt**——这是全场证据密度最高的列之一，也是隐私敏感面（prompt 会离开本机去 LLM 端点）。

## 10. prompt 函数清单（12 个 + 1 个共享助手）

| 函数（h:149-162 声明） | 覆盖类型 | 备注 |
|---|---|---|
| analyzeSmsArtifact | SMS | 独立 |
| analyzeWechatMessageArtifact | WECHAT_MESSAGE | 独立（列最多，10 列） |
| analyzeGenericMessageArtifact(artifact, label) | WHATSAPP("WhatsApp") / TELEGRAM("Telegram") | 平台名参数化 |
| analyzeContactArtifact | CONTACT | |
| analyzeCallLogArtifact | CALL_LOG | |
| analyzeMiuiManifestArtifact | MIUI_MANIFEST | |
| analyzeInstalledAppArtifact | INSTALLED_APP | |
| analyzeSqliteRecordArtifact(artifact, label) | WECHAT_SQLITE_RECORD("WeChat") / QQNT_SQLITE_RECORD("QQ") | 平台名参数化 |
| analyzeWechatKvArtifact | WECHAT_KV_RECORD | |
| analyzeSystemLogArtifact | SYSTEM_LOG | |
| analyzeDeviceIdentifierArtifact | DEVICE_IDENTIFIER | |
| analyzeWifiNetworkArtifact | WIFI_NETWORK | |
| analyzeWithPrompt（共享助手，:169-171） | 全部 | 角色描述 + 工件 JSON + guidance 三参数——Android 版独有的收敛层，Linux/Windows 没有这层抽象 |

14 类型 → 12 函数（两组参数化各省 1 个）。switch 的 default `continue` 同族（ALL 与未注册类型静默跳过）。

## 11. 配置影响表（全集，含门控细节）

| 配置 | 默认 | 消费链 | 说明 |
|---|---|---|---|
| `LLM_BASE_URL` | `http://192.168.31.170:1234` | AndroidAnalyzerCore.cpp:278 端点门控 | **默认非空**——门控"URL 都为空才跳过"在默认配置下恒不触发；要跳过得显式设空 |
| `LLM_TEXT_BASE_URL` | 回退 LLM_BASE_URL | 同上第二条件 | 同上 |
| `LLM_TEXT_*` 五项 | 见 Environment.md | initialize() → ModelRouter | 每条工件模型调用 |
| `LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES` | 120 / 3 | LLMClient | 端点配置了但不可达时仍逐条超时（门控不检测连通性，只查配置非空） |
| `--no-ai`（CLI flag） | false | skipAI_ → analyzeWithLLM 第一道门 | HTTP 任务路径无此开关（skipAI_ 恒 false），只有 CLI 能触发 |
| （无 maxArtifacts env） | 1000 | AnalysisOptions（h:57） | 调用方硬编码全开 |
| `TRACELENS_MIUI_*` | 见源文件 | MIUI 解析侧（上游） | 影响 manifest 表的行数而非本模块行为 |

注意 §3.2 门控的完整条件是 `getTextBaseUrl().empty() && getLLMBaseUrl().empty()`——**两个都空才跳过**；只清空 LLM_TEXT_BASE_URL 时回退逻辑（ConfigManager.cpp:100）会让它拿到 LLM_BASE_URL 的值，门控仍不触发。

## 12. 关联矩阵（补全版）

| 方向 | 对象 | 交互点 | 说明 |
|---|---|---|---|
| 被调 | AndroidAnalyzerCore.cpp:322 | 唯一调用点 | 两条上游（TSK/逻辑提取）汇合 |
| 门控 | AndroidAnalyzerCore.cpp:260-290 | skipAI_ + 端点双检 | ANDROID_LLM_SKIPPED 审计 |
| 依赖 | llm::ModelRouter | initialize() | 文本模型 |
| 读写 | `_android.db` 14 张表 | SELECT pending / UPDATE by id | 列契约见 §9 |
| SQL 来源 | android_analysis_sql_llm.h | :20-90 | **没有** Windows/Linux 那套 UPDATE_*_LLM_ANALYSIS 常量族——回写从一开始就是字符串拼接（_Database.cpp:17-56），只留 android_analysis_progress 进度表 SQL（:82-91，与 Windows 同样零调用方的死代码） |
| 同族 | Linux/Windows 版 | 同骨架 | Android 独有 analyzeWithPrompt 收敛层与端点门控 |
| 审计 | AuditLog | ANDROID_LLM_INIT_FAILED / ANDROID_LLM_ANALYSIS_COMPLETE / ANDROID_LLM_SKIPPED | 三类审计事件 |
| 读出方 | 前端 /android 视图 | llm_* 列 | 微信/QQ 记录的敏感优先截断影响展示顺序 |

## 13. analyzeWithPrompt 共享助手的契约（三参数收敛层）

Android 版独有的抽象（h:169-171 声明）：所有 12 个 prompt 函数最终经它走完"拼 prompt → router chat → 解析 JSON"三步。参数表：

| 参数 | 内容 | 示例（SMS） |
|---|---|---|
| roleDescription | 角色句（平台+工件类型） | "You are a digital forensics expert analyzing Android SMS messages." |
| artifactJson | 工件行的 JSON dump（§9 的列集） | `{"address":"10086","body":"...","date":...}` |
| guidance | 输出要求段 | summary/description/keywords 三项要求 + JSON 模板 |

返回 AnalysisResult 五字段（success/summary/description/keywords/modelUsed）。**收敛的代价**：guidance 是共享模板，所有类型的三段式输出结构一致——没有类型特化的问题导向（对比 Linux 版每类的独立 prompt 可以问不同问题）。**解析是裸 json::parse**——同平台族严格策略（模型输出带额外文本即整条作废）。

## 14. 5 组开关的调度展开表（analyzeAndroidArtifacts 执行序）

| 开关 | 展开的类型（调用序） | 类型数 |
|---|---|---|
| includeMessages | SMS → WECHAT_MESSAGE → WHATSAPP → TELEGRAM | 4 |
| includeContacts | CONTACT → CALL_LOG | 2 |
| includeMiui | MIUI_MANIFEST → INSTALLED_APP | 2 |
| includeWechatEvidence | WECHAT_SQLITE_RECORD → WECHAT_KV_RECORD → QQNT_SQLITE_RECORD | 3 |
| includeSystem | SYSTEM_LOG → DEVICE_IDENTIFIER → WIFI_NETWORK | 3 |

调用方硬编码全开（AndroidAnalyzerCore.cpp:312-317）——14 类全跑，理论上限 14×1000 次调用；但 §3.2 的端点门控先于本服务生效（URL 双空时根本不进来），实际风险面比 Linux/Windows 小。

## 15. 验证 runbook

```bash
# 1. android 场景任务后查注解（敏感优先截断的直观验证）
sqlite3 data/tasks/<id>/android.db \
  "SELECT is_sensitive, COUNT(*), SUM(llm_analyzed_at IS NOT NULL)
   FROM wechat_kv_records GROUP BY is_sensitive"
#    期望：is_sensitive=1 的覆盖率高（它们排在 LIMIT 前）
# 2. 门控验证
#    .env 清空 LLM_BASE_URL 与 LLM_TEXT_BASE_URL → 跑 android 任务
sqlite3 data/forensics_audit.db "SELECT action FROM audit_logs WHERE action='ANDROID_LLM_SKIPPED' ORDER BY timestamp DESC LIMIT 1"
# 3. 脱敏端点（前置依赖：RouteHelpers 的 android 三级回退）
curl -s ":8080/api/forensics/android/miui-wechat-records?task_id=<id>&kind=kv" | jq '.records[0].value_text' | head -c 100
curl -s ":8080/api/forensics/android/miui-wechat-records?task_id=<id>&kind=kv&reveal_sensitive=1" | jq '.records[0].value_text' | head -c 100
# 4. 覆盖率端点
curl -s ":8080/api/forensics/android/llm-summary?task_id=<id>" | jq .totals
```

**最后更新**: 2026-08-24（二轮深化：补全方法清单与契约细节）
