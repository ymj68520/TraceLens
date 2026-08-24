# 运维手册：LLM 端点操作

> 适用场景：维护为 TraceLens 供给智能层的 OpenAI 兼容端点（LM Studio / vLLM / 云端代理）。端口默认以 `.env` 的 `LLM_BASE_URL`（本仓库示例 `http://192.168.31.170:1234`）为准。

## 速查卡

```bash
# 1. 端点活着吗？双模型都在吗？
curl -s $LLM_BASE_URL/v1/models | python3 -m json.tool | grep '"id"'
# 期望同时看到：聊天模型（如 openai/gpt-oss-20b 或 qwen 系）与
#              text-embedding-nomic-embed-text-v1.5（图谱嵌入必需）

# 2. 一次最小聊天冒烟
curl -s $LLM_BASE_URL/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"<LLM_TEXT_MODEL>","messages":[{"role":"user","content":"ping"}],"max_tokens":8}'

# 3. 服务侧视角的健康
curl -s http://localhost:8090/api/llm/status     # Python 侧汇总
curl -s http://localhost:8666/api/forensics/dlls/health  # 顺带看 DLL 分析服务
```

## 1. 双模型同载是图谱的硬前提

Graphiti 全功能要求端点**同时**加载：
- **聊天/抽取模型**：负责实体抽取与摘要（`.env.example` 推荐 `openai/gpt-oss-20b`；qwen 系也可，但思考型模型见 §4）。
- **嵌入模型**：`text-embedding-nomic-embed-text-v1.5`（dim 768）——GraphitiIngestor 的 OpenAIEmbedder 用它建向量；缺了它图谱摄取会在初始化/检索时失败。

只载聊天模型：分析任务的 LLM 描述能跑，图谱质量骤降或不可用。检查命令即速查卡第 1 条：两个 ID 都必须在 `/v1/models` 里。

## 2. 模型名一致性（历史高频坑）

`LLM_TEXT_MODEL` 必须与 `/v1/models` 返回的 `id` **逐字一致**（含 `openai/` 之类前缀）。全链实测时修过的 P0 之一就是"模型名不匹配导致整链 404"。换模型后：
```bash
grep -E 'LLM_(TEXT|VISION)_MODEL' .env
curl -s $LLM_BASE_URL/v1/models | grep -F "$(grep LLM_TEXT_MODEL .env | cut -d= -f2)" || echo "名字对不上"
```

## 3. 限额联动矩阵（谁限制谁）

| 旋钮 | 默认 | 实际约束推导 |
|------|------|-------------|
| `LLM_MAX_FILES` | 500 | 每任务进文件级 LLM 的上限（smart 粗选前先截断） |
| `LLM_MAX_CONTENT_LENGTH` | 10000（example） | **实际生效约 6144**：FileAnalyzer 预算取三重最小值，`(LLM_CONTEXT_LENGTH−RESERVED−MAX_TOKENS)×CHARS_PER_TOKEN` 在代码默认（4096/512/2048/4.0）下 = 6144 字符——想让 10000 生效需同时调大 LLM_CONTEXT_LENGTH |
| `LLM_MAX_EVENT_CLUSTERS` | 0（不限） | 簇分析条数上限；0 表示全量 |
| `GRAPHITI_BATCH_SIZE` | 三处不一致（50/10/25） | httpserver 路径以 50 为准；调大前确认端点上下文窗口（当初从 50 降到 25 就是为防 8K 溢出） |
| `GRAPHITI_MAX_EPISODE_TOKENS` | 3000 | 单 episode 截断；与端点窗口直接挂钩 |

换更大窗口模型后，优先重算这一列而不是盲目调大。

## 4. 常见故障画像 → 责任层

| 症状 | 大概率责任层 | 处理 |
|------|-------------|------|
| 请求超时（120s） | 端点过载/排队 | 看 LM Studio 队列；调 LLM_TIMEOUT_SECONDS 或降并发（THREAD_POOL_SIZE 同时压任务与 LLM 两道闸） |
| 429/5xx 间歇 | 端点限流 | LLMClient 会重试（4 次尝试，含 4xx——本地端点的宽容取舍）；持续则降批量 |
| 描述全是空/截断 | 内容预算 | §3 的 6144 推导；SMART 粗选淘汰（查 files.llm_analyzed_at 覆盖率） |
| 图谱实体缺哈希/IP/路径 | 抽取指令层 | 确认 GraphitiIngestor 的 FORENSIC_EXTRACTION_INSTRUCTIONS 未被改动；episode 是 text 渲染 |
| `<think>` 残留进结果 | llm_patch 层 | 确认 graphiti_integration.llm_patch 在任何 graphiti_core 导入前 import（部署级时序坑） |
| 嵌入维度不匹配 | 嵌入配置 | EMBEDDING_MODEL/dim 与 Neo4j 里既有索引一致；换嵌入模型=图谱要重建 |
| 请求"并发"变串行 | LLMClient 互斥 | 单槽端点这是保护；多槽端点重审该锁（Concurrency §2.5） |

## 5. 换模型 / 换端点迁移检查单

1. `/v1/models` 双模型在列（§1）；
2. `.env` 的 LLM_TEXT_MODEL/LLM_VISION_MODEL 逐字对齐（§2）；
3. 上下文窗口变了 → 重算限额矩阵（§3）：LLM_CONTEXT_LENGTH、GRAPHITI_BATCH_SIZE、GRAPHITI_MAX_EPISODE_TOKENS；
4. 思考型模型（qwen3/deepseek-r1）→ 确认 llm_patch 生效（§4）；
5. 嵌入模型动了 → 图谱重建预案（wipe_neo4j.py + 重摄取）；
6. 跑冒烟：速查卡三条 + 一个小任务（smart 模式）+ `GET /api/graphiti/status`；
7. 观察一个完整任务的 files.llm_analyzed_at 覆盖率与图谱 job 无 episode 级报错。

## 6. 与代码的对应

| 机制 | 位置 |
|------|------|
| 重试/超时/互斥 | [LLMClient](../modules/cpp/integration/LLMClient.md)（互斥、4 次尝试、parseResponse 双兼容清洗） |
| 内容预算与截断 | [FileAnalyzer](../modules/cpp/integration/FileAnalyzer.md)（三重最小值 + 头 70% 尾 30%） |
| 抽取指令/渲染/嵌入组装 | [GraphitiIngestor](../modules/python/graphiti_integration/GraphitiIngestor.md) |
| 端点降级语义 | Python `/health/ready` 把 LLM 列为可选依赖（[Health](../modules/python/httpserver/routes/Health.md)） |

---

**最后更新**: 2026-08-24（新建：LLM 端点运维手册）
