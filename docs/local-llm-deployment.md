# TraceLens 本地大模型部署方案（离线保密环境）

- 制定日期：2026-10-19（**v2 修订**：主选模型由 Qwen3.8-Flash-Next 改为 Nemotron-3-Nano-Omni-30B-A3B，原因见 §0；**v3 修订**：embedding 由 8B/4096 维改为 0.6B/1024 维，实测依据见 §3.6）
- 适用分支：`feature/model-routing`（模型路由改造之后）
- 适用场景：取证镜像数据保密，**部署机不允许联网、不允许调用外部大模型 API**（chat.cordapp.org / api.hcnsec.cn 等云端端点全部停用）
- 硬件前提：
  - **4090 主机**：RTX 4090（24GB 显存）+ 128GB 系统内存
  - **Spark**：NVIDIA DGX Spark（GB10，128GB 统一内存，带宽约 273GB/s）

## 0. v2 修订记录（为什么换模型）

v1 选 Qwen3.8-Flash-Next（125B 总参 / 6B 激活）+ `--cpu-moe` 混合推理。该方案的解码速度由**系统内存带宽**决定（专家层驻留 DDR5，~60GB/s 实际带宽），单流仅 20–35 tok/s，735 文件的批量任务预估 6–12 小时——**速度不达标**。

v2 改用 **Nemotron-3-Nano-Omni-30B-A3B-Reasoning**（NVIDIA 2025-12 发布，30B 总参 / **3B 激活** MoE，混合 Mamba-Transformer 架构）：权重整体驻留 4090 显存（约 21GB 含视觉投影器），解码走**显存带宽（~1TB/s）**，预期单流 100–200 tok/s，**较 v1 提速约 5–8 倍**；Omni 变体保留原生多模态，满足"必须可分析图片"的硬性要求。项目 specs 里图片分析的历史角色（LM Studio 的 `nemotron-omni`）正是这一系模型，行为画像延续。

v1 的 Qwen3.8 方案压缩保留在附录 A，作为 Nemotron 路线不稳时的回退。

## 1. 方案总览

| 设备 | 运行内容 | 模型 | 承担功能 |
|---|---|---|---|
| 4090 主机 | llama.cpp `llama-server`（全模型驻留 GPU，**无 cpu-moe**） | **NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning**（unsloth GGUF，UD-Q3_K_XL） | 文本批量摘要 + **图片/截图多模态分析** + Graphiti 图谱抽取（三合一） |
| Spark | llama.cpp `llama-server --embedding`（`-np 4`） | **Qwen3-Embedding-0.6B**（官方 GGUF，F16，1024 维） | 向量检索（Graphiti / 语义检索） |

核心思路：30B 总参但仅 3B 激活，Q3 量化后 19.5GB，加 1.6GB 视觉投影器共约 21.1GB——**连同 mmproj 一起完整放进 24GB 显存**，没有 PCIe 每层往返，速度只受算力与显存带宽限制。Spark 用 0.6B embedding（F16 仅 1.2GB，4 路并发，实测聚合 ~67 条/秒，单发 10–66ms），速度与显存余量双优。

## 2. 选型依据（2026-10-19 调研核实）

**为什么选 Nemotron-3-Nano-Omni-30B-A3B-Reasoning：**

- **混合 Mamba-Transformer MoE**：仅少数层是全注意力（带 KV cache），其余为线性注意力状态（显存占用恒定）——32K 上下文的 KV 开销远小于同规模 dense 模型，24GB 卡上可以放开用上下文
- **Omni 变体才有视觉**（图像/视频/语音/文本）；纯文本版 `Nemotron-3-Nano-30B-A3B` 不能看图，不满足硬性要求，不要下错仓库
- **Reasoning 变体 = instruct 后训练**（本方案硬性前提），默认 thinking 模式可关
- **llama.cpp 支持已逐项核实**（master 源码 + GGUF 二进制头）：文本架构 `nemotron_h_moe` 在 `llama-arch.cpp`；视觉投影器 `mmproj-F16.gguf` 头部声明 `nemotron_v2_vl`，mtmd 视觉路径含 `NEMOTRON_V2_VL`/`NEMOTRON_OMNI`——文本与视觉链路都有官方支持，但架构较新，**必须用当日 master 源码编译**
- 仓库：`unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF`（hf-mirror 可达，含全套 UD 量化 + mmproj）

**量化档选择（hf-mirror 实测体积）：**

| 档位 | 模型体积 | +mmproj 1.6GB 后 | 结论 |
|---|---|---|---|
| **UD-Q3_K_XL / UD-Q3_K_M / UD-IQ4_XS / UD-IQ4_NL** | 19.5GB | **~21.1GB** | **推荐**：留 ~2.9GB 给 KV 与运行缓冲 |
| UD-IQ3_XXS / UD-IQ3_S / UD-Q2_K_XL | 18.5–19.5GB | ~20–21GB | 备选（更低精度） |
| UD-Q4_K_S | 23.0GB | 24.6GB | ✗ 超 24GB 显存 |
| UD-Q4_K_XL / UD-Q4_K_M | 23.9GB | 25.5GB | ✗ 超 24GB 显存 |
| UD-Q5_K_* 及以上 | ≥24.8GB | — | ✗ |

主推 **UD-Q3_K_XL**（Q3_K 系对 MoE 专家权重质量较稳）。若质量实测不足，用 `--n-cpu-moe N` 把 N 层专家放内存换取 Q4_K_S 的进档空间（牺牲部分速度），不要直接上 Q4_K_XL。

**为什么不再选其他候选：**

| 候选 | 排除原因 |
|---|---|
| Qwen3.8-Flash-Next（v1 主选） | cpu-moe 带宽受限 20–35 tok/s，批量任务 6–12h → 附录 A 回退项 |
| Nemotron-3-Nano-30B-A3B（非 Omni） | 无视觉能力 |
| nvidia 官方 BF16 / FP8 / NVFP4 | 30–60GB 均超 24GB；NVFP4 为 Blackwell 专有格式，4090（Ada）不支持 |

### 2.1 知识图谱（Graphiti）链路的模型构成

| 组件 | 代码位置 | 本地方案 |
|---|---|---|
| 抽取 LLM | `GRAPHITI_LLM_MODEL` / `GRAPHITI_LLM_BASE_URL` | 4090 的 Nemotron-3-Nano-Omni |
| Embedding | `EMBEDDING_MODEL` / `EMBEDDING_DIM` | Spark 的 Qwen3-Embedding-0.6B（1024 维，实体消歧对齐） |
| Reranker | `OpenAIRerankerClient`（`graphiti_ingestor.py`，复用抽取 LLM） | 自动跟随 4090，无需单独部署 |

两点工程事实（与 v1 相同）：

- **离线安全**：项目未使用 Graphiti 默认的 HuggingFace cross-encoder，重排由本地 LLM 兼任，无隐藏下载。
- **⚠ pin 陷阱**：`graphiti_integration/config.py` 中 `GRAPHITI_LLM_MODEL` **留空会回落到写死的 `microsoft/phi-4`**——llama-server 上不存在该模型，图谱入库会全部失败。`.env` 必须始终显式设置 `GRAPHITI_LLM_MODEL`。

## 3. 部署步骤

### 3.1 4090 主机：编译 llama.cpp

> 架构较新（nemotron_h_moe / nemotron_v2_vl），**必须最新 master**，不要用发行版旧二进制。

```bash
sudo apt install -y build-essential cmake git libcurl4-openssl-dev
git clone https://github.com/ggml-org/llama.cpp && cd llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j$(nproc)
# 产物：build/bin/llama-server
```

（GitHub 不可达时走代理镜像：`git clone https://ghfast.top/https://github.com/ggml-org/llama.cpp`）

### 3.2 4090 主机：下载模型（走 hf-mirror）

```bash
pip install -U huggingface_hub
export HF_ENDPOINT=https://hf-mirror.com
hf download unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF \
    --include "NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q3_K_XL.gguf" \
    --include "mmproj-F16.gguf" \
    --local-dir ~/models/nemotron-omni-30b
```

- 注意：该仓库所有量化档都是**仓库根目录下的单文件**（没有 `UD-Q3_K_XL/` 子目录），`--include` 按文件名通配
- 主模型单文件约 19.5GB（无分片）；`mmproj-F16.gguf` 1.59GB 必下，否则没有视觉能力
- 完全离线场景可先在可达机器下载后经移动硬盘携带

### 3.3 4090 主机：启动对话/多模态服务（:8000）

```bash
~/llama.cpp/build/bin/llama-server \
    -m ~/models/nemotron-omni-30b/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q3_K_XL.gguf \
    --mmproj ~/models/nemotron-omni-30b/mmproj-F16.gguf \
    -ngl 99 \
    -c 32768 --flash-attn \
    --cache-type-k q8_0 --cache-type-v q8_0 \
    -np 4 --cont-batching \
    --jinja \
    --alias nemotron-3-nano-omni-30b \
    --host 0.0.0.0 --port 8000
```

参数说明：

- `-ngl 99`：全部层驻留 GPU——**本方案与 v1 的本质区别**，不再有 `--cpu-moe`
- `-np 4 --cont-batching`：4 并发槽连续批处理；混合 Mamba 架构的序列状态很小，显存富余可试 `-np 6~8`
- thinking：Reasoning 版默认输出思考内容。先按默认跑；若 Graphiti 抽取 JSON 质量差，对比开关两种模式（`--reasoning-budget 0` 若模板支持则可关）。项目 `llm_patch.py` 兜底剥离 `<think>` 残留
- `-c 32768`：起步上下文；KV 只占少数注意力层，显存富余可加大

### 3.4 Spark：启动 embedding 服务（:8001）

> ✅ **2026-10-19 已在 Spark 上完成（v3：0.6B 档）**：llama.cpp 编译（CUDA sm_121a）、模型下载、`llama-embedding.service` 常驻并开机自启、`EMBEDDING_DIM=1024` 实测定稿。服务器状态与 4090 网线直连步骤见 [spark-4090-direct-network.md](spark-4090-direct-network.md)。

```bash
export HF_ENDPOINT=https://hf-mirror.com
hf download Qwen/Qwen3-Embedding-0.6B-GGUF \
    --include "Qwen3-Embedding-0.6B-f16.gguf" --local-dir ~/models/qwen3-embedding-06b

llama-server -m ~/models/qwen3-embedding-06b/Qwen3-Embedding-0.6B-f16.gguf \
    --embedding --pooling last \
    -b 8192 -ub 8192 -c 32768 -np 4 --cont-batching \
    --alias qwen3-embedding-0.6b \
    --host 0.0.0.0 --port 8001
```

- 注意文件名是**小写 `f16`**（大写 `F16` 匹配不到，会静默下载 0 个文件）
- `--pooling last` 是 Qwen3-Embedding 在 llama.cpp 的必需参数；`-c 32768` 拆给 4 个 slot（每槽 8192），保证 2000 字长文本不被截断
- **为什么从 8B 降到 0.6B**（2026-10-19 Spark 实测）：8B 单发 76–494ms、批量 32 条/秒；0.6B 单发 10–66ms、批量 114 条/秒、4 路并发聚合 ~67 条/秒即打满（8/16 路无增益）；实体区分度对拍 0.6B 反而略优（0.158 vs 0.122），C-MTEB 榜单差距（64 vs 70）对消歧场景可接受。8B 模型文件仍保留在 `~/models/qwen3-embedding/` 备查

### 3.5 修改 TraceLens `.env`

```ini
# —— 指向本地 llama-server ——
LLM_TEXT_BASE_URL=http://<4090主机IP>:8000/v1
LLM_VISION_BASE_URL=http://<4090主机IP>:8000/v1
GRAPHITI_LLM_BASE_URL=http://<4090主机IP>:8000/v1
LLM_TEXT_MODEL=nemotron-3-nano-omni-30b
LLM_VISION_MODEL=nemotron-3-nano-omni-30b
GRAPHITI_LLM_MODEL=nemotron-3-nano-omni-30b   # 不可留空！留空回落 phi-4（本机不存在，图谱入库全挂）
LLM_API_KEY=local-no-key                      # llama-server 未启用 --api-key 时忽略此值
LLM_THINKING_MODE=                            # 留空，由服务端控制 thinking
GRAPHITI_STRUCTURED_OUTPUT_MODE=json_schema   # llama.cpp 走语法约束，比 json_object 更可靠

# —— 并发与超时 ——
LLM_CONTEXT_LENGTH=32768
LLM_MAX_CONCURRENCY=4             # 与 -np 一致；-np 提到 6~8 时同步
GRAPHITI_MAX_CONCURRENCY=4        # 与 Spark embedding 的 -np 4 对齐
LLM_TIMEOUT_SECONDS=600
LLM_MAX_FILES=1000                # 速度恢复后不再需要削减批量

# —— embedding 指向 Spark ——
EMBEDDING_BASE_URL=http://<Spark IP>:8001/v1
EMBEDDING_MODEL=qwen3-embedding-0.6b
EMBEDDING_DIM=1024                # v3 定稿：0.6B 原生 1024 维（llama.cpp 忽略 dimensions 参数，见 3.6）
```

> `LLM_ENDPOINT=/v1/chat/completions` 等其余配置不变。**`EMBEDDING_DIM` 必须在首次图谱入库前定稿**——维度写进 Neo4j 索引后中途更改需重建图谱数据。

### 3.6 Embedding 维度验证（✅ v3 定稿：0.6B / 1024 维）

2026-10-19 Spark 实测两条结论：① llama.cpp **忽略 `dimensions` 参数**（8B 上要 2048 给 4096；0.6B 上要 768 给 1024）——llama.cpp 路线下维度只能取模型原生值，768 维不可得；② 生产服务已切 **Qwen3-Embedding-0.6B**（F16，原生 1024 维，`-np 4`），`.env` 定稿 `EMBEDDING_DIM=1024`。质量对拍与基准数据见 §3.4。

## 4. 冒烟测试清单（部署完当天完成）

1. **视觉（本方案第一风险项，先测）**：用一张取证截图按 OpenAI `image_url` 格式发请求，确认返回内容描述正确（mmproj / `nemotron_v2_vl` 路径生效）；失败先重编译当日 master
2. **文本**：`curl http://<4090>:8000/v1/chat/completions` 发一条消息，记录实测 tok/s（预期 100–200；若 <60 检查是否真的全层驻留，`nvidia-smi` 看显存占用应 ~21GB+）
3. **结构化输出**：带 `response_format: json_schema` 请求，确认语法约束生效、输出可直接 `json.loads`
4. **thinking 行为**：确认默认输出中 `<think>` 段的表现，与 `llm_patch.py` 剥离逻辑对上；对比开关 thinking 对抽取质量的影响
5. **embedding**：3.6 的维度验证 + 两组相似文本余弦相似度抽查（相似 >0.7、无关 <0.4 量级）
6. **端到端**：跑一个小型测试任务（如 M57-Jean 的部分文件），核对 `files.db` 的 `llm_summary` 计数与图谱作业状态（`GET :8090/api/graphiti/jobs/<job_id>`）

## 5. 性能预期与批量策略

| 项目 | 云端基线（deepseek-flash，2026-10-17 实测） | v1 Qwen3.8 预期 | **v2 Nemotron 预期** |
|---|---|---|---|
| 单流解码 | 秒级响应 | 20–35 tok/s | **100–200 tok/s** |
| 735 文件 LLM 全流程 | 49 分钟 | 6–12 小时 | **约 1–3 小时** |
| 单图视觉分析 | 秒级 | 数秒–数十秒 | 秒级（prefill 全速在 4090 上） |
| 图谱入库 | 1822 实体/18 分钟 | 显著变慢 | 明显改善，`GRAPHITI_MAX_CONCURRENCY=2` 兜底 |

批量策略：速度恢复后 `LLM_MAX_FILES` 不必削减；"N/N 进度后仍有尾批在途"现象依旧存在，以 `files.db` 的 `llm_summary` 计数为真实完成数。tok/s 显著低于预期时，优先检查：① 显存是否溢出（`nvidia-smi`）；② 是否误加了 `--cpu-moe`；③ 内存/显存频率是否达标。

## 6. 调优与回退

| 情况 | 处置 |
|---|---|
| 质量不足（抽取 JSON 混乱、漏实体） | `--n-cpu-moe N` 少量专家层放内存，进档 UD-Q4_K_S；或放开 thinking 对比 |
| 速度不达标（<60 tok/s） | 确认无 `--cpu-moe`、显存未溢出、模型档位为 19.5GB 档 |
| vision 加载失败（mmproj 报不支持） | 拉当日 master 重编译；仍失败则文本用本模型、图片分析临时降级（或转附录 A） |
| llama.cpp 对 nemotron_h_moe 支持不稳定 | **回退附录 A**：Qwen3.8-Flash-Next `--cpu-moe` 方案（慢但自洽） |
| `response_format` 被 400 | llama-server 升级到最新版；仍失败则 `.env` 改回 `json_object`，`llm_patch.py` 自动降级为提示词注入重试 |
| Spark 未到位 | 4090 单机全包：embedding 换 `Qwen3-Embedding-4B-GGUF` 挤同一张卡（约 8GB；llama.cpp 固定原生 2560 维，`EMBEDDING_DIM=2560`；此时主模型上下文适当调小） |

## 7. 附录 A：v1 Qwen3.8-Flash-Next 方案（回退项，速度不达标）

4090 + `--cpu-moe` 混合推理跑 `unsloth/Qwen3.8-Flash-Next-GGUF`（125B-A6B，UD-Q3_K_XL 90GB 驻留 128GB 内存）：

```bash
llama-server -m .../UD-Q3_K_XL/*.gguf --mmproj .../mmproj-F16.gguf \
    --cpu-moe -ngl 99 -c 32768 --flash-attn \
    --cache-type-k q8_0 --cache-type-v q8_0 \
    -np 4 --cont-batching --reasoning-budget 0 --jinja \
    --alias qwen3.8-flash-next --host 0.0.0.0 --port 8000
```

单流 20–35 tok/s，735 文件约 6–12 小时；mmproj-F16 905MB；上下文原生 262K。llama.cpp 架构名 `qwen4exp`（master 已支持）。仅当 Nemotron 路线受阻时启用，`.env` 三个 MODEL 同步改回 `qwen3.8-flash-next`。

## 8. 附录 B：模型文件清单

| 文件 | 来源 | 体积（实测） | 用途 |
|---|---|---|---|
| `NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-UD-Q3_K_XL.gguf` | unsloth/NVIDIA-Nemotron-3-Nano-Omni-30B-A3B-Reasoning-GGUF | 19.54GB | 主模型（text+vision+graph） |
| `mmproj-F16.gguf` | 同上 | 1.59GB | 视觉投影器（必下） |
| `Qwen3-Embedding-0.6B-f16.gguf` | Qwen/Qwen3-Embedding-0.6B-GGUF（注意小写 f16） | 1.2GB | 向量检索（Spark，1024 维） |
| （备查）`Qwen3-Embedding-8B-f16.gguf` | Qwen/Qwen3-Embedding-8B-GGUF | 15.1GB | 仍保留在 Spark `~/models/qwen3-embedding/`，需要更高消歧质量时切回（`EMBEDDING_DIM=4096`，需重建图谱） |
| （备选）UD-Q4_K_S | 同主模型仓库 | 23.0GB | 质量进档（需 `--n-cpu-moe` 配合） |

所有下载走 `HF_ENDPOINT=https://hf-mirror.com`（国内直连可达，2026-10-19 实测）；完全离线可将上述文件经移动硬盘携带。
