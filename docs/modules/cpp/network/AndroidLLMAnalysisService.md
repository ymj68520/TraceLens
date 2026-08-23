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

- `getTableNameForType`（AndroidLLMAnalysisService_Database.cpp:102-120）：14 类型 ↔ `sms_messages / wechat_messages / whatsapp_messages / telegram_messages / contacts / call_logs / miui_backup_manifest / installed_apps / wechat_sqlite_records / wechat_kv_records / qqnt_sqlite_records / system_logs / device_identifiers / wifi_networks`；
- `getSelectSQLForType`（:122-141）：每类型一条 `android_analysis_sql_llm::SELECT_*_PENDING_ANALYSIS` 常量——WHERE 排除已分析行，重跑增量续作；
- 每类型一个 prompt 函数（_ArtifactAnalyzers.cpp；不少类型共用泛型助手，如 `analyzeGenericMessageArtifact(artifact, "WhatsApp")`、`analyzeSqliteRecordArtifact(artifact, "WeChat"/"QQ")`，AndroidLLMAnalysisService.cpp:153-178）；
- `storeArtifactAnalysis`（Database.cpp:17-56）：统一 `UPDATE <表> SET llm_summary/…/llm_model_used WHERE id=?`，keywords 逗号拼接（:24-29）。

### 3.2 与 Linux/Windows 的关键差异：可用性门控

Linux/Windows 版头文件标注 "MANDATORY analysis step"，**只要场景跑了注解就跑**，LLM 不可用时逐条失败调用（拖慢平台阶段）。Android 版**没有**这条 MANDATORY 注释，并在调用方加了两道自动跳过（AndroidAnalyzerCore.cpp:260-287）：

1. `skipAI_`（用户 `--no-ai`）→ 跳过并写 `ANDROID_LLM_SKIPPED` 审计；
2. **未配置 LLM 端点**（text 与 llm 的 base URL 都为空）→ 自动跳过，注释明说这是"keeps Android consistent … after their key-based check was relaxed"（:268-281）——本地 LLM（LM Studio/Ollama/vLLM）无需 API key，所以门控看 URL 而非 key。

效果：Android 在无 LLM 环境下不烧失败调用，与 Linux 的行为**不一致**（Linux 会逐条超时失败后静默返回 0）。这是同族三兄弟里唯一的可用性门控差异，排障时别拿 Linux 的表现套 Android。

任务级 `llm_analyze` 开关同样**不门控**本服务：TMA 注释直言 Android 分析器已在 analyzeAndroidData 内部做过工件级 LLM，`llm_analyze` 只补一条进度说明（TaskManagerAnalysis.cpp:162-172）。

### 3.3 选项分组

`AnalysisOptions`（h:56-63）5 个 include 开关默认全开、每类上限 1000：includeMessages（SMS+微信+WhatsApp+Telegram 四表）、includeContacts（联系人+通话）、includeMiui（备份清单+已装应用）、includeWechatEvidence（微信 sqlite/kv + QQNT 三表）、includeSystem（日志+设备标识+WiFi）。调用方硬编码全开（AndroidAnalyzerCore.cpp:312-317）——分组目前是"可关"而非"被配置"。

## 4. 工作流程走读

`analyzeAndroidArtifacts`（AndroidLLMAnalysisService.cpp:44-107）：惰性 initialize（ConfigManager 取文本模型建 ModelRouter，:19-42）→ 按开关逐类调 `analyzeArtifactType`。后者（:109-207）每类型**自开连接**：取未分析行（LIMIT 内联替换，Database.cpp:66-70）→ 逐条进度回调 → switch 路由到 prompt 函数 → `router_->chat` → 解析 JSON → 成功才 UPDATE；单条异常仅 stderr 并继续（:200-202）。返回累计分析数，调用方写 `ANDROID_LLM_ANALYSIS_COMPLETE` 审计（AndroidAnalyzerCore.cpp:323-325）。

失败模式：与 Linux 相同——LLM 挂了每条 chat 失败、函数返回 0，任务不受影响，表保持 PENDING 等下次增量（且 Android 有 §3.2 的端点预检，通常根本不会进入这条慢路）。

## 5. 与其他模块的协作

| 协作方 | 关系 |
|---|---|
| AndroidAnalyzer | 唯一调用方（analyzeWithLLM，AndroidAnalyzerCore.cpp:260-332），负责门控与审计 |
| AndroidAnalysisSQL（android_analysis_sql_llm） | PENDING SELECT 定义处；建表侧是 AndroidAnalyzer 的各解析阶段 |
| Linux/Windows 同族 | 同骨架；Android 多一层端点可用性门控 |
| ModelRouter / ConfigManager | 文本模型路由（同 Linux） |
| 前端 /android 相关视图 | 经路由读 llm_* 列渲染注解 |

## 6. 注意事项与已知问题

- **无 MANDATORY 标注 + 有端点门控**（§3.2）：同族行为差异，两份文档读者容易互相误导；跨平台排障先确认目标平台走哪条门控路径。
- **keywords 逗号拼接**：keywords 本身含逗号时无法还原数组（与 Linux/Windows 同款老问题）。
- **逐条同步调用、无批量**：千条级消息 × 每类 1000 上限，本地小模型也需可观时长；进度只有 stdout 回调（HTTP 进度条不感知细粒度）。
- **JSON 输出解析无重试**：模型不守格式该条作废，保持未分析状态。
- **include 分组无人消费**：调用方永远全开（§3.3），想按任务关掉某类（如跳过 wifi）需要先给 AnalysisOptions 接一条配置通路。

## 7. 如何验证与扩展

- **验证**：跑 android 场景任务后查 `_android.db`：`SELECT address, llm_summary FROM sms_messages WHERE llm_analyzed_at > 0 LIMIT 10`；再触发一次同库任务确认 PENDING 查询增量生效；把 LLM_BASE_URL 清空重跑，审计日志应出现 `ANDROID_LLM_SKIPPED`（门控生效）而非逐条失败。
- **扩展新工件类型**：① AndroidAnalyzer 建表填充；② android_analysis_sql_llm 加 `SELECT_X_PENDING_ANALYSIS`；③ Database.cpp 两个映射函数加 case；④ _ArtifactAnalyzers.cpp 加 prompt 函数并在 analyzeArtifactType 的 switch（AndroidLLMAnalysisService.cpp:146-191）注册；⑤ 要进默认执行集，还需在 analyzeAndroidArtifacts 的开关组（:63-104）加调用。

**最后更新**: 2026-08-23（新建，解释式）
