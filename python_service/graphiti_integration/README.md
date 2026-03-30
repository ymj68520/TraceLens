# Graphiti Integration - 产品说明书

## 1. 模块概述 (Overview)

Graphiti Integration 是知识图谱集成模块,基于 Graphiti 框架构建,将取证数据转换为结构化的知识图谱。该模块自动提取实体(文件、人物、组织、时间等)和关系(创建、修改、访问、通信等),为取证分析提供智能的关联查询和推理能力。

**核心价值**:
- 自动构建知识图谱,揭示数据之间的隐藏关联
- 支持自然语言查询,降低使用门槛
- 提供实体和关系的可视化展示
- 增强 LLM 分析的上下文理解能力

该模块解决了"如何从海量数据中发现隐藏关联"的问题,为智能取证分析提供强大的工具。

## 2. 核心功能列表 (Key Features)

### 2.1 知识图谱构建
- **实体提取**: 自动识别文件、人物、组织、时间等实体
- **关系抽取**: 提取实体之间的关系(创建、修改、访问等)
- **事件建模**: 将文件系统事件建模为图谱中的边
- **时序建模**: 保留时间信息,支持时序查询

### 2.2 图谱查询
- **实体查询**: 查询特定实体的详细信息
- **关系查询**: 查询实体之间的关系
- **路径查询**: 查找实体之间的路径
- **子图查询**: 提取相关的子图

### 2.3 LLM 增强
- **向量化嵌入**: 为实体和关系生成向量嵌入
- **语义搜索**: 基于语义的相似度搜索
- **上下文理解**: 为 LLM 提供丰富的上下文
- **问答系统**: 支持自然语言问答

### 2.4 数据集成
- **数据库读取**: 从 SQLite 数据库读取数据
- **TOON 转换**: 将数据转换为 TOON 格式
- **批量摄入**: 支持批量数据摄入
- **增量更新**: 支持增量更新图谱

## 3. 业务流程/使用场景 (Use Cases)

### 场景一: 关联分析

**背景**: 需要找出文件之间的关联关系。

**使用流程**:
1. **数据摄入**: 将取证数据库摄入知识图谱
2. **实体识别**: 自动识别文件、用户、时间等实体
3. **关系提取**: 提取实体之间的关系
4. **关联查询**: 查询特定文件的所有关联
5. **可视化展示**: 展示关联图谱

**业务价值**: 发现数据之间的隐藏关联,提供全面的分析视角。

### 场景二: 智能问答

**背景**: 需要通过自然语言查询取证数据。

**使用流程**:
1. **构建图谱**: 将数据摄入知识图谱
2. **自然语言查询**: 用户用自然语言提问
3. **语义理解**: LLM 理解查询意图
4. **图谱查询**: 在图谱中查询相关信息
5. **答案生成**: 生成自然语言答案

**业务价值**: 降低使用门槛,让非专业人员也能查询数据。

## 4. 部署与配置要求 (Deployment & Configuration)

### 4.1 环境要求

**Python 版本**: Python 3.10+

**依赖库**:
```bash
pip install graphiti-core
pip install openai  # 或其他 LLM SDK
pip install numpy
```

**LLM 服务**:
- OpenAI API 或兼容服务
- 或本地 LLM(如 LM Studio)

### 4.2 配置文件

```python
# config.py
from graphiti_core import Graphiti
from graphiti_core.llm_client import OpenAIGenericClient
from graphiti_core.embedder import OpenAIEmbedder

# LLM 客户端配置
llm_client = OpenAIGenericClient(
    api_key="your-api-key",
    model="gpt-4",
    base_url="http://localhost:1234"
)

# 嵌入模型配置
embedder = OpenAIEmbedder(
    api_key="your-api-key",
    embedding_model="text-embedding-ada-002"
)

# Graphiti 客户端
graphiti_client = Graphiti(
    "sqlite:///graphiti.db",
    llm_client=llm_client,
    embedder=embedder
)
```

### 4.3 环境变量配置

在项目根目录的 `.env` 文件中配置:

```bash
# Neo4j 连接配置
NEO4J_URI=neo4j://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# LLM 配置 (用于实体提取)
LLM_TEXT_BASE_URL=http://192.168.31.199:1234
LLM_TEXT_MODEL=openai/gpt-oss-20b
LLM_API_KEY=local

# Graphiti 批处理配置
GRAPHITI_BATCH_SIZE=10              # 每批处理 10 条记录 (降低以避免 token 溢出)
GRAPHITI_MAX_RETRIES=3              # 失败重试次数
GRAPHITI_GROUP_ID=forensics_files   # 数据组 ID

# Token 管理配置 (防止 8096 上下文溢出)
GRAPHITI_MAX_EPISODE_TOKENS=3000    # 单条 episode 最大 token 数
GRAPHITI_INCLUDE_FULL_DESC=false    # 是否包含完整描述 (true/false)

# 数据过滤配置
GRAPHITI_USE_LOCAL_LLM=true         # 使用本地 LLM
```

**重要说明**:
- `GRAPHITI_BATCH_SIZE`: 默认值从 50 降低到 10,以避免单批 token 累积超过 8096
- `GRAPHITI_MAX_EPISODE_TOKENS`: 单条 episode 的安全 token 限制
- `GRAPHITI_INCLUDE_FULL_DESC`: 设为 `true` 可包含完整的 LLM 描述 (可能较大)

### 4.3 使用示例

```python
from graphiti_integration import GraphitiIngestor, GraphitiConfig

# 创建配置
config = GraphitiConfig(
    llm_api_key="your-api-key",
    llm_base_url="http://localhost:1234",
    llm_model="qwen2.5:7b"
)

# 创建摄入器
ingestor = GraphitiIngestor(config)

# 初始化
await ingestor.initialize()

# 摄入数据
episodes = [
    EpisodeData(
        name="文件创建事件",
        content="用户 admin 在 2024-01-01 创建了文件 document.pdf"
    )
]

result = await ingestor.ingest_episodes(episodes)
print(f"成功摄入 {result.successful} 个事件")
```

## 5. 接口与集成说明 (API & Integration)

### 5.1 核心接口

**GraphitiIngestor**:
```python
async def initialize() -> None
async def ingest_episodes(episodes: List[EpisodeData]) -> IngestionResult
async def search(query: str, limit: int = 10) -> List[SearchResult]
```

**DatabaseReader**:
```python
def read_database(db_path: str) -> pd.DataFrame
def extract_episodes(df: pd.DataFrame) -> List[EpisodeData]
```

**TOONTransformer**:
```python
def to_markdown(df: pd.DataFrame) -> str
def to_episodes(toon_data: str) -> List[EpisodeData]
```

### 5.2 REST API

通过 Python HTTP 服务暴露的 API:
- `POST /api/graphiti/ingest` - 摄入数据到知识图谱
- `POST /api/graphiti/search` - 在图谱中搜索
- `GET /api/graphiti/entities` - 列出实体
- `GET /api/graphiti/relationships` - 列出关系
- `GET /api/graphiti/status` - 服务状态

### 5.3 集成示例

```python
# 从数据库读取并摄入
from graphiti_integration.database_reader import DatabaseReader
from graphiti_integration.toon_transformer import TOONTransformer

# 读取数据库
reader = DatabaseReader("evidence_files.db")
df = reader.read_table("files")

# 转换为 TOON
transformer = TOONTransformer()
toon_data = transformer.to_markdown(df)

# 转换为 Episode
episodes = transformer.to_episodes(toon_data)

# 摄入到 Graphiti
result = await ingestor.ingest_episodes(episodes)
```

## 6. 常见问题 (FAQ)

### Q1: Graphiti 与传统数据库有什么区别?

**A**: 主要区别:
- **传统数据库**: 结构化查询,需要预定义模式
- **知识图谱**: 灵活的图结构,支持关联查询和推理

Graphiti 更适合处理复杂的关系和关联分析。

### Q2: 图谱性能如何?

**A**:
- 小规模(<10000 节点): 实时查询
- 中等规模(10000-100000 节点): 亚秒级查询
- 大规模(>100000 节点): 需要优化索引

建议: 定期清理旧数据,保持图谱大小可控。

### Q3: 支持哪些 LLM?

**A**: 支持任何 OpenAI 兼容的 API:
- OpenAI (GPT-3.5、GPT-4)
- Azure OpenAI
- LM Studio (本地)
- Ollama (本地)

### Q4: 如何可视化知识图谱?

**A**: 有多种方式:
1. 使用 Graphiti 内置的可视化工具
2. 导出为 GraphML 格式,使用 Gephi 可视化
3. 使用 Python 的 networkx 和 matplotlib
4. 使用 Web 前端框架(如 D3.js)构建自定义可视化

### Q5: 数据更新如何处理?

**A**: Graphiti 支持增量更新:
1. 仅摄入新增或变更的数据
2. 自动去重,避免重复摄入
3. 支持删除旧的实体和关系

建议: 定期更新图谱,保持数据最新。
