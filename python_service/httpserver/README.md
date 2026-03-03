# Python HTTP Server - Python HTTP 服务

## 1. 模块概述 (Overview)

**Python HTTP Server** 是基于FastAPI框架构建的现代化REST API服务,为取证分析平台提供Python生态系统的深度集成能力。该服务专注于知识图谱集成、LLM智能增强分析和高效数据导出,与C++ HTTP服务协同工作,形成完整的双服务架构。

该模块为客户解决"需要AI驱动的智能取证分析"的核心需求。通过集成Graphiti知识图谱和大语言模型能力,Python服务能够从海量取证数据中自动识别关键线索、发现隐藏关联、生成可读性报告,大幅提升取证分析效率。

**核心业务价值:**
- **知识图谱驱动**:自动识别实体关系,发现数据间的隐藏关联
- **LLM智能增强**:AI自动分析文件内容,生成摘要和关键词
- **高效数据导出**:支持TOON格式,30-60% token节省用于LLM分析
- **Python生态集成**:无缝集成丰富的Python数据科学库
- **异步高性能**:FastAPI异步架构,支持高并发访问

---

## 2. 核心功能列表 (Key Features)

### 2.1 Graphiti知识图谱API (`/api/graphiti/*`)

- **数据摄入**
  - 将取证数据库文件摄入知识图谱
  - 实体提取:文件、用户、时间、位置等
  - 关系抽取:文件关联、用户行为、时序关系
  - 支持增量更新和全量重建

- **图谱搜索**
  - 自然语言查询:"查找所有包含'合同'的PDF文件"
  - 实体类型过滤:按文件类型、用户、时间筛选
  - 关系路径分析:查找两个实体间的关联路径
  - 相关性排序:按匹配度返回最相关结果

- **图谱管理**
  - 实体列表查询:分页浏览所有实体
  - 关系列表查询:查看所有关系类型
  - 图谱状态监控:实体数量、关系数量、存储大小
  - 图谱清理和归档

### 2.2 LLM分析服务 (`/api/llm/*`)

- **内容分析**
  - 文本分析:分析任意文本内容,生成摘要和关键词
  - 文件上传分析:支持直接上传文件进行分析
  - 批量分析:异步批量处理大量文件
  - 任务管理:创建、查询、取消批量分析任务

- **模型管理**
  - 多模型支持:OpenAI、Anthropic、本地模型(LM Studio)
  - 模型列表:查询可用的LLM模型
  - 模型状态:检查模型健康状态和响应时间
  - 动态切换:无需重启服务即可切换模型

- **分析结果**
  - 自动摘要:生成文件内容的简短摘要
  - 关键词提取:识别5-10个重要关键词
  - 内容分类:自动判断文件类型和用途
  - 情感分析:识别文本情感倾向(适用于邮件、聊天记录)

### 2.3 数据库访问API (`/api/db/*`)

- **任务查询**
  - 任务列表:查询所有取证分析任务
  - 任务详情:获取特定任务的完整信息
  - 文件查询:获取任务关联的所有文件
  - 事件查询:获取任务的时间线事件

- **数据导出**
  - **TOON格式**:高效LLM提示格式,30-60% token节省
    - Schema声明:自动生成TOON.schema头部
    - 管道分隔:使用`|`分隔字段
    - 字段选择:支持导出指定字段
    - LLM集成:可直接输入大语言模型
  - **JSON格式**:标准JSON,用于API集成
  - **CSV格式**:用于Excel分析和报表

- **自定义查询**
  - 原生SQL查询执行
  - 查询结果缓存
  - 分页支持

### 2.4 系统监控API (`/health`, `/api/system/*`)

- **健康检查**
  - `/health`:基本健康状态
  - `/health/live`:Kubernetes存活探针
  - `/health/ready`:Kubernetes就绪探针
  - 数据库连接检查
  - 依赖服务状态

- **系统信息**
  - 服务版本和配置
  - Python版本和依赖库
  - 系统资源使用情况
  - API文档自动生成

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:AI辅助的智能取证分析

**背景**:调查人员需要从10万个文件中快速定位关键证据,传统人工筛选效率低下。

**业务流程**:
1. **知识图谱摄入**
   ```bash
   POST /api/graphiti/ingest
   {
     "task_id": "task_123",
     "include_llm_descriptions": true,
     "batch_size": 100
   }
   ```
   系统自动分析文件元数据和LLM描述,构建知识图谱

2. **智能搜索**
   ```bash
   POST /api/graphiti/search
   {
     "query": "包含'机密'且与'合同'相关的PDF文件",
     "limit": 50
   }
   ```
   图谱引擎自动识别关联文件,返回最相关结果

3. **关联分析**
   调查人员发现可疑文件后,通过图谱查询:
   - "谁访问过这个文件?" → 识别相关用户
   - "这个文件与哪些文件相关?" → 发现关联文件
   - "事件前后还有哪些活动?" → 完整行为链

4. **AI辅助阅读**
   对找到的关键文档,调用LLM分析:
   ```bash
   POST /api/llm/analyze/file
   上传document.pdf
   ```
   返回摘要:"这是一份保密协议,涉及甲方ABC公司与XYZ项目..."

**价值体现**:从10万文件中快速定位3个关键证据,耗时从数天缩短到数小时。

### 场景二:TOON格式导出用于LLM深度分析

**背景**:需要将取证数据输入大语言模型进行深度案情分析。

**业务流程**:
1. **导出TOON格式**
   ```bash
   GET /api/db/tasks/123/export/toon?include=llm_summary,llm_keywords
   ```

2. **TOON格式示例**
   ```
   TOON.schema: name | size | mtime | llm_summary | llm_keywords
   /home/user/suspect.pdf | 2048576 | 1705420123 | 保密协议文档 | 保密,协议,ABC公司,项目X
   /home/user/budget.xlsx | 1024000 | 1705419800 | 财务预算表 | 预算,财务,2024,Q1
   ```

3. **输入LLM分析**
   将TOON格式数据直接粘贴给LLM:
   ```
   用户: 以下是我取证分析的数据,请帮我识别可疑行为:

   [TOON数据]

   LLM: 根据提供的数据,我发现以下可疑点:
   1. suspect.pdf是保密协议,但被删除了两次
   2. budget.xlsx在离职前3天被修改
   3. ...
   ```

**价值体现**:TOON格式相比JSON节省60% token,同样成本可分析3倍数据。

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**Python版本**: Python 3.10+ (推荐3.11+)

**必需的Python包**:
```bash
# Web框架
pip install fastapi==0.104.1 uvicorn[standard]==0.24.0

# 数据验证
pip install pydantic==2.5.0 pydantic-settings==2.1.0

# HTTP客户端
pip install httpx==0.25.2 python-multipart==0.0.6

# 知识图谱
pip install graphiti-core==0.1.0

# 环境配置
pip install python-dotenv==1.0.0
```

**可选依赖**:
```bash
# LLM集成
pip install openai==1.6.1 anthropic==0.18.0

# 数据处理
pip install pandas==2.1.0 numpy==1.26.0

# 开发工具
pip install black ruff mypy
```

### 配置文件

在项目根目录创建`.env`文件:

```env
# 服务配置
PYTHON_HTTP_HOST=0.0.0.0
PYTHON_HTTP_PORT=8090
LOG_LEVEL=INFO

# C++后端
CPP_BACKEND_URL=http://localhost:8080
CPP_BACKEND_TIMEOUT=30

# Graphiti知识图谱
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
GRAPHITI_GROUP_ID=forensics_project
GRAPHITI_ENABLED=true

# LLM配置
LLM_BASE_URL=http://localhost:1234
LLM_API_KEY=your-api-key
LLM_MODEL=qwen2.5:7b
LLM_MAX_TOKENS=4096
LLM_TIMEOUT=60

# 数据库导出
TOON_DEFAULT_FIELDS=name,path,size,mtime,llm_summary
TOON_DELIMITER=" | "
```

### 启动服务

**开发模式**:
```bash
# 从项目根目录
python -m python_service.httpserver.main

# 或使用uvicorn直接启动
uvicorn python_service.httpserver.main:app --reload --host 0.0.0.0 --port 8090
```

**生产模式**:
```bash
# 使用Gunicorn + Uvicorn workers
gunicorn python_service.httpserver.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8090 \
  --timeout 3600 \
  --access-logfile /var/log/forensic/python/access.log \
  --error-logfile /var/log/forensic/python/error.log
```

**使用启动脚本**:
```bash
# 同时启动C++和Python服务
./scripts/start_services.sh
```

服务启动后:
- Swagger UI: http://localhost:8090/docs
- ReDoc: http://localhost:8090/redoc
- OpenAPI JSON: http://localhost:8090/openapi.json

---

## 5. 接口与集成说明 (API & Integration)

### Graphiti知识图谱API

```bash
# 摄入数据到知识图谱
curl -X POST http://localhost:8090/api/graphiti/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_123",
    "include_llm_descriptions": true,
    "batch_size": 50
  }'

# 响应
{
  "success": true,
  "job_id": "ingest_job_456",
  "message": "Ingestion started in background",
  "timestamp": "2024-01-19T10:30:00Z"
}

# 搜索知识图谱
curl -X POST http://localhost:8090/api/graphiti/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "机密文件 AND 合同",
    "limit": 20,
    "include_relationships": true
  }'

# 查询图谱状态
curl http://localhost:8090/api/graphiti/status
```

### LLM分析API

```bash
# 分析文本内容
curl -X POST http://localhost:8090/api/llm/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "content": "这是一份合同...",
    "max_tokens": 1000
  }'

# 批量分析文件
curl -X POST http://localhost:8090/api/llm/batch-analyze \
  -H "Content-Type: application/json" \
  -d '{
    "task_id": "task_123",
    "file_filter": {"category": "documents"},
    "max_parallel": 5
  }'

# 查询批量任务状态
curl http://localhost:8090/api/llm/batch-analyze/job_789
```

### 数据库导出API

```bash
# 导出为TOON格式
curl http://localhost:8090/api/db/tasks/123/export/toon \
  -G \
  --data-urlencode "include=llm_summary,llm_keywords" \
  --data-urlencode "filter=category='documents'"

# 导出为JSON格式
curl http://localhost:8090/api/db/tasks/123/export/json \
  -G \
  --data-urlencode "table=files" \
  --data-urlencode "limit=1000"

# 自定义SQL查询
curl -X POST http://localhost:8090/api/db/query \
  -H "Content-Type: application/json" \
  -d '{
    "sql": "SELECT * FROM files WHERE size > 10485760 ORDER BY size DESC LIMIT 10"
  }'
```

### Python客户端示例

```python
import httpx

class ForensicPythonClient:
    def __init__(self, base_url="http://localhost:8090"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=60.0)

    async def ingest_to_graphiti(self, task_id: str):
        """摄入数据到知识图谱"""
        response = await self.client.post(
            f"{self.base_url}/api/graphiti/ingest",
            json={
                "task_id": task_id,
                "include_llm_descriptions": True,
                "batch_size": 50
            }
        )
        return response.json()

    async def search_graphiti(self, query: str, limit: int = 20):
        """搜索知识图谱"""
        response = await self.client.post(
            f"{self.base_url}/api/graphiti/search",
            json={
                "query": query,
                "limit": limit,
                "include_relationships": True
            }
        )
        return response.json()

    async def batch_analyze_files(
        self,
        task_id: str,
        file_filter: dict = None
    ):
        """批量LLM分析文件"""
        response = await self.client.post(
            f"{self.base_url}/api/llm/batch-analyze",
            json={
                "task_id": task_id,
                "file_filter": file_filter or {},
                "max_parallel": 5
            }
        )
        return response.json()

    async def export_toon(self, task_id: str, **params):
        """导出为TOON格式"""
        response = await self.client.get(
            f"{self.base_url}/api/db/tasks/{task_id}/export/toon",
            params=params
        )
        return response.text

# 使用示例
async def main():
    client = ForensicPythonClient()

    # 摄入到知识图谱
    job = await client.ingest_to_graphiti("task_123")
    print(f"Ingestion job: {job['job_id']}")

    # 等待摄入完成...
    await asyncio.sleep(60)

    # 搜索图谱
    results = await client.search_graphiti("机密 AND 合同")
    for result in results['results']:
        print(f"Found: {result['name']} - {result['score']}")

    # 导出TOON格式
    toon_data = await client.export_toon("task_123")
    print(f"TOON export:\n{toon_data[:500]}...")

asyncio.run(main())
```

---

## 6. 常见问题 (FAQ)

**Q1: Python服务和C++服务如何协同工作?**

A:两者分工明确,通过HTTP通信:
- **C++服务(8080端口)**:负责磁盘镜像分析、任务管理、数据库访问
- **Python服务(8090端口)**:负责知识图谱、LLM分析、数据导出

**工作流程**:
1. 客户端向C++服务创建分析任务
2. C++服务完成分析,生成数据库
3. Python服务从C++服务获取数据,进行知识图谱构建
4. 客户端从Python服务查询图谱或导出数据

**优势**:
- 各服务使用最适合的技术栈
- 独立部署和扩展
- 技术栈解耦,易于维护

---

**Q2:知识图谱能处理多少数据?性能如何?**

A:性能取决于数据量和Neo4j配置:

**数据规模参考**:
- 小型(<1万文件):实时响应,亚秒级查询
- 中型(1-10万文件):秒级响应,适合交互式分析
- 大型(>10万文件):需要优化索引,查询可能需要数秒

**优化建议**:
1. 为常用查询字段建立索引
2. 使用`filter_analyzed_only`仅摄入已分析LLM的文件
3. 定期清理旧数据,保持图谱大小
4. 使用Neo4j企业版处理超大规模数据

---

**Q3:LLM分析的准确率如何?支持哪些模型?**

A:准确率取决于LLM模型能力和数据质量:

**支持的模型**:
- **OpenAI**: GPT-4, GPT-3.5-turbo
- **Anthropic**: Claude 3 Opus, Claude 3 Sonnet
- **本地模型**:通过LM Studio运行的开源模型(Qwen, LLaMA等)
- **自定义**:任何兼容OpenAI API的模型

**准确率参考**:
- 文件摘要:85-95%准确率(取决于模型)
- 关键词提取:70-90%准确率
- 内容分类:80-95%准确率
- 建议:对关键结果进行人工复核

**优化建议**:
- 使用更强大的模型(如GPT-4)
- 提供更多上下文信息
- 调整提示词(Prompt)优化输出
- 使用Few-shot示例引导模型

---

**Q4:TOON格式相比JSON有什么优势?**

A:TOON格式专为LLM优化,主要优势:

**Token节省**:
- JSON: `{"name": "file.pdf", "size": 1024}` → 约50 tokens
- TOON: `file.pdf | 1024` → 约10 tokens
- **节省60-70% token**,同样成本可分析更多数据

**可读性**:
- 表格格式,LLM容易理解
- 自动类型推断,无需复杂schema
- 适合复制粘贴到聊天界面

**使用建议**:
- 小数据集(<1000条): JSON和TOON均可
- 中大数据集(>1000条): 优先使用TOON
- 需要字段嵌套: 使用JSON
- LLM分析: 优先使用TOON

---

**Q5:如何扩展新的API端点?**

A:FastAPI使得添加新端点非常简单:

**步骤**:
1. 在`python_service/httpserver/routes/`创建新路由文件
   ```python
   # routes/custom.py
   from fastapi import APIRouter, Query
   from pydantic import BaseModel

   router = APIRouter(prefix="/api/custom", tags=["custom"])

   class CustomRequest(BaseModel):
       param1: str
       param2: int = 100

   @router.post("/endpoint")
   async def custom_endpoint(request: CustomRequest):
       # 业务逻辑
       return {"result": "success"}
   ```

2. 在`main.py`的`_register_routes()`中注册
   ```python
   from .routes import custom
   app.include_router(custom.router)
   ```

3. 重启服务(或使用`--reload`自动重载)

4. 更新API文档

---
