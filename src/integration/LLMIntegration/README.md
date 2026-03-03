# LLMIntegration - 大语言模型集成引擎

## 1. 模块概述 (Overview)

**LLMIntegration** 是取证分析平台的大语言模型(LLM)集成核心,为整个系统提供AI驱动的智能分析能力。该模块通过OpenAI兼容API连接多种LLM服务(如LM Studio、OpenAI GPT、Anthropic Claude、本地模型等),实现文件内容智能分析、摘要生成、关键词提取、视觉理解等功能。通过多模型路由、MCP协议集成、批处理优化等高级特性,LLMIntegration为取证分析人员提供强大的AI辅助工具,大幅提升海量证据的分析效率和洞察深度。

该模块为客户解决"如何在海量取证数据中快速发现关键线索"的核心痛点。传统取证分析依赖人工逐个检查文件,耗时且容易遗漏重要信息。LLMIntegration利用大语言模型的强大理解能力,自动分析文件内容、生成摘要、提取关键词、识别敏感信息,使得调查人员能够从数万份文档中快速定位关键证据,将数天的分析工作缩短至数小时。

**核心业务价值:**
- **AI驱动分析**:利用大语言模型自动理解文件内容,生成摘要和关键词
- **多模型支持**:兼容OpenAI、LM Studio、本地模型等多种LLM服务
- **智能路由策略**:支持优先级、回退、负载均衡等多种路由策略
- **MCP协议集成**:通过Model Context Protocol暴露文件分析工具
- **批处理优化**:高效的批量文件分析,支持进度回调
- **上下文窗口管理**:智能处理大文件,支持分块分析

---

## 2. 核心功能列表 (Key Features)

### 2.1 LLMClient - OpenAI兼容API客户端

- **广泛的模型支持**
  - **OpenAI**:GPT-4、GPT-3.5-turbo、GPT-4-turbo
  - **Anthropic**:Claude 3 Opus、Claude 3 Sonnet(通过适配器)
  - **本地模型**:LM Studio、Ollama、llama.cpp等
  - **企业API**:Azure OpenAI、Google PaLM API
  - 任何兼容OpenAI API格式的服务

- **核心功能**
  - 连接测试:验证LLM服务可用性
  - 对话完成:支持多轮对话、系统提示词
  - 模型列表:查询服务端可用模型
  - 工具调用:支持Function Calling能力
  - 自动重试:网络错误时自动重试(可配置次数)
  - 超时控制:防止长时间等待

- **配置灵活性**
  - 自定义API端点
  - 可选API密钥(本地模型可省略)
  - 可调整的temperature参数(控制创造性)
  - 可配置的max_tokens(控制响应长度)
  - 上下文窗口管理

### 2.2 ModelRouter - 多模型智能路由

- **路由策略**

  **优先级路由(Priority)**:
  - 按模型优先级排序
  - 优先使用高优先级模型
  - 高优先级模型不可用时降级

  **回退路由(Fallback)**:
  - 按顺序尝试模型
  - 主模型失败时自动切换
  - 确保请求成功率

  **轮询路由(RoundRobin)**:
  - 平均分配请求到各模型
  - 分散负载,防止单点过载
  - 提高并发处理能力

  **负载均衡(LoadBalance)**:
  - 根据当前负载动态选择
  - 优先选择空闲模型
  - 优化响应时间

  **能力路由(Capability)**:
  - 按模型能力匹配任务
  - 文本生成、代码生成、视觉分析
  - 确保任务由最合适的模型处理

- **模型管理**
  - 动态添加/移除模型端点
  - 实时健康检查
  - 失败计数和自动标记
  - 优先级动态调整

- **容错机制**
  - 自动故障转移
  - 请求失败重试
  - 错误日志记录
  - 降级策略

### 2.3 FileAnalyzer - 文件智能分析器

- **核心分析能力**

  **摘要生成(Summarization)**:
  - 自动生成50-100字的简短摘要
  - 捕捉文件核心内容
  - 适用于快速浏览

  **详细描述(Description)**:
  - 生成200-500字的详细描述
  - 涵盖文件用途、重要性、敏感度
  - 提供更丰富的上下文信息

  **关键词提取(Keywords)**:
  - 提取5-10个关键词
  - 识别文件主题和类别
  - 支持搜索和分类

  **文件类型判断**:
  - 自动识别文件用途
  - 判断敏感度等级
  - 标注内容类别

- **大文件处理**
  - **分块分析**:
    - 自动将大文件分割为多个块
    - 每块独立分析后合并结果
    - 支持重叠分块保持上下文连续性

  - **智能边界**:
    - 优先在句子/段落边界分割
    - 避免截断关键信息
    - 保持语义完整性

  - **上下文窗口管理**:
    - 自动计算token数量
    - 限制单次请求大小
    - 留出响应空间

- **批量处理**
  - 并行分析多个文件
  - 进度回调支持
  - 错误处理和恢复
  - 结果聚合和统计

### 2.4 MCPIntegration - Model Context Protocol集成

- **MCP服务器**
  - 标准MCP协议实现
  - 默认端口8890
  - 支持blocking/non-blocking模式

- **内置工具**

  **read_file**:
  - 读取文件内容
  - 支持大小限制
  - 路径安全检查

  **analyze_file**:
  - 分析文件内容
  - 生成摘要和关键词
  - 返回JSON格式结果

  **list_files**:
  - 列出目录内容
  - 支持递归遍历
  - 文件类型过滤

  **generate_description**:
  - 生成文件描述
  - 支持单文件或多文件
  - 自然语言输出

- **安全机制**
  - 路径白名单限制
  - 防止目录遍历攻击
  - 文件大小限制
  - 可访问路径配置

- **自定义工具**
  - 支持注册自定义工具
  - JSON Schema参数定义
  - 灵活的处理器函数
  - 工具发现API

### 2.5 ConfigManager - 环境配置管理

- **配置加载**
  - 从.env文件加载配置
  - 支持多环境配置
  - 默认值机制
  - 配置验证

- **配置项**
  ```env
  # LLM服务配置
  LLM_BASE_URL=http://localhost:1234
  LLM_API_KEY=your-api-key
  LLM_MODEL=qwen2.5:7b
  LLM_MAX_TOKENS=4096
  LLM_TEMPERATURE=0.7
  LLM_TIMEOUT=60

  # 上下文窗口配置
  LLM_CONTEXT_LENGTH=4096
  LLM_RESERVED_TOKENS=512
  LLM_CHARS_PER_TOKEN=4.0

  # 分块分析配置
  LLM_ENABLE_CHUNKED=true
  LLM_CHUNK_SIZE=2000
  LLM_OVERLAP_SIZE=200
  LLM_MAX_CHUNKS=5

  # MCP服务配置
  MCP_PORT=8890
  MCP_ALLOWED_PATHS=/data/files,/tmp/extracted
  ```

---

## 3. 业务流程/使用场景 (Use Cases)

### 场景一:海量文档智能筛选与优先级排序

**背景**:某企业内部调查涉及离职员工电脑的50万个文件,调查团队需要在24小时内完成初步筛查,识别高度可疑文件。

**业务流程**:
1. **文件提取与准备**
   ```bash
   # 从磁盘镜像提取所有文件
   forensic_analyzer employee_disk.dd --extract-all --output-dir /tmp/extracted
   # 提取完成: 502,347 个文件
   ```

2. **配置LLM分析环境**
   ```cpp
   // 加载配置
   ConfigManager::instance().load(".env");

   // 创建模型路由器
   auto router = std::make_shared<ModelRouter>();

   // 配置主模型(GPT-4,高质量)
   LLMConfig gpt4Config;
   gpt4Config.baseUrl = "https://api.openai.com/v1";
   gpt4Config.apiKey = config.get("OPENAI_API_KEY");
   gpt4Config.model = "gpt-4-turbo";
   gpt4Config.priority = 10;
   gpt4Config.contextLength = 128000;

   // 配置备用模型(本地Qwen,低延迟)
   LLMConfig qwenConfig;
   qwenConfig.baseUrl = "http://localhost:1234";
   qwenConfig.model = "qwen2.5:7b";
   qwenConfig.priority = 5;

   router->addModel("gpt4", gpt4Config, ModelInfo{...});
   router->addModel("qwen", qwenConfig, ModelInfo{...});
   router->setStrategy(RoutingStrategy::Fallback);
   ```

3. **批量分析文档**
   ```cpp
   FileAnalyzer analyzer(router);
   analyzer.setProgressCallback([](size_t current, size_t total, const std::string& file) {
       double percent = 100.0 * current / total;
       std::cout << "[" << percent << "%] 分析: " << file << std::endl;
   });

   BatchAnalysisRequest request;
   request.filePaths = getDocumentFiles("/tmp/extracted");  // 仅分析文档
   request.generateSummary = true;
   request.generateDescription = true;
   request.extractKeywords = true;
   request.maxContentLength = 5000;  // 每个文件最多发送5000字符

   auto results = analyzer.analyzeBatch(request);
   ```

4. **筛选可疑文件**
   ```sql
   -- 查询包含敏感关键词的文件
   SELECT file_path, llm_summary, llm_keywords
   FROM files
   WHERE llm_keywords LIKE '%机密%'
      OR llm_keywords LIKE '%保密%'
      OR llm_keywords LIKE '%合同%'
      OR llm_keywords LIKE '%客户名单%';

   -- 查询高敏感度描述
   SELECT file_path, llm_description
   FROM files
   WHERE llm_description LIKE '%敏感%'
      OR llm_description LIKE '%机密%'
      OR llm_description LIKE '%未公开%';
   ```

5. **优先级排序**
   - 找到3,456个包含敏感关键词的文档
   - 其中234个被LLM标记为"高度敏感"
   - 按关键词匹配度和敏感度排序
   - 生成TOP 50可疑文件清单

**价值体现**:
- **效率提升**: 从需要5天人工筛查缩短至18小时完成
- **覆盖全面**: 100%覆盖所有文档,无遗漏
- **质量保证**: GPT-4的准确率达92%,远超人工一致性
- **成本可控**: 主分析使用本地模型,仅可疑文件使用GPT-4复核
- **证据完整**: 所有分析结果存储在数据库,形成完整证据链

---

### 场景二:网络入侵事件的恶意代码智能识别

**背景**:某Web服务器遭攻击,安全团队需要从1,200个Web文件中识别被植入的后门和恶意代码。

**业务流程**:
1. **批量分析Web文件**
   ```cpp
   FileAnalyzer analyzer(router);

   // 自定义提示词优化代码分析
   analyzer.setSummaryPrompt(
       "你是一个网络安全专家。请分析以下代码文件,识别:"
       "1. 是否包含可疑的eval、base64_decode、assert等危险函数"
       "2. 是否有混淆的代码段"
       "3. 是否包含未知的包含或引用"
       "如果是正常代码,请简要说明功能。如果是恶意代码,请详细说明威胁类型。"
   );

   // 分析PHP文件
   auto phpFiles = glob("/tmp/extracted", "**/*.php");
   BatchAnalysisRequest request;
   request.filePaths = phpFiles;
   request.generateSummary = true;
   request.extractKeywords = true;

   auto results = analyzer.analyzeBatch(request);
   ```

2. **识别可疑模式**
   ```cpp
   for (const auto& result : results) {
       if (result.summary.find("恶意") != std::string::npos ||
           result.summary.find("后门") != std::string::npos ||
           result.summary.find("可疑") != std::string::npos) {

           std::cout << "发现可疑文件: " << result.filePath << std::endl;
           std::cout << "威胁类型: " << result.summary << std::endl;

           // 记录到证据数据库
           saveToDatabase(result);
       }
   }
   ```

3. **深度分析可疑文件**
   ```cpp
   // 对发现的23个可疑文件进行详细分析
   for (const auto& suspiciousFile : suspiciousFiles) {
       std::string content = readFile(suspiciousFile);
       std::string prompt =
           "请详细分析以下PHP代码的安全风险:\n\n" + content +
           "\n\n请提供:1) 威胁等级(低/中/高/严重) 2) 攻击向量 3) 建议的处置措施";

       LLMResponse response = router->chat(prompt, systemPrompt);
       std::cout << "文件: " << suspiciousFile << std::endl;
       std::cout << "分析结果:\n" << response.content << std::endl;
   }
   ```

4. **生成安全报告**
   - 识别出7个Webshell后门
   - 发现15个包含混淆代码的可疑文件
   - 定位到3个被植入的恶意脚本
   - 生成完整的安全事件报告

**价值体现**:
- **精准识别**: LLM能够识别混淆后的恶意代码,传统特征码难以检测
- **上下文理解**: 理解代码逻辑而非仅匹配字符串
- **自适应能力**: 可应对未知的攻击手法
- **快速响应**: 数小时内完成分析,大幅缩短响应时间

---

### 场景三:通过MCP协议与外部LLM协作

**背景**:调查人员希望使用Claude、ChatGPT等商业LLM直接分析取证数据,但要确保数据安全。

**业务流程**:
1. **启动MCP服务器**
   ```cpp
   // 创建MCP集成
   MCPIntegration mcp(router, 8890);

   // 配置安全路径白名单
   mcp.setAllowedPaths({
       "/data/extracted_files",
       "/tmp/forensic_analysis"
   });

   // 启动服务器(非阻塞模式)
   mcp.start(false);
   std::cout << "MCP服务器已启动: http://localhost:8890" << std::endl;
   ```

2. **注册自定义工具**
   ```cpp
   // 注册案件特定工具
   mcp.registerTool(
       "search_evidence",
       "搜索与案件相关的证据文件",
       R"({
           "type": "object",
           "properties": {
               "keywords": {"type": "array", "items": {"type": "string"}},
               "file_type": {"type": "string"}
           }
       })",
       [](const std::string& argsJson) -> std::string {
           // 实现搜索逻辑
           return searchFiles(argsJson);
       }
   );
   ```

3. **Claude/ChatGPT连接MCP服务**

   在Claude Desktop或ChatGPT中配置MCP:
   ```json
   {
     "mcpServers": {
       "forensic-tools": {
         "command": "node",
         "args": ["path/to/mcp-client.js"],
         "env": {
           "MCP_SERVER_URL": "http://localhost:8890"
         }
       }
     }
   }
   ```

4. **LLM直接调用取证工具**

   与Claude对话:
   ```
   用户: 请帮我分析/home/user/Documents目录下的所有文档,找出与"保密协议"相关的文件。

   Claude: [调用list_files工具]
   Claude: [调用analyze_file工具分析每个文档]

   我找到了以下与保密协议相关的文件:

   1. /home/user/Documents/合同/ABC公司保密协议.pdf
      摘要: ABC公司与XYZ项目的保密协议文档...
      关键词: 保密、协议、ABC公司、商业机密

   2. /home/user/Documents/法律/保密条款修订版.docx
      摘要: 保密协议的修订版本...
      关键词: 法律、保密、修订

   建议重点审查这些文件...
   ```

**价值体现**:
- **数据安全**: 文件不离开本地网络,仅发送分析结果
- **灵活协作**: 调查人员可用自然语言与证据库交互
- **智能分析**: 结合LLM的推理能力进行复杂分析
- **标准化接口**: MCP协议支持多种LLM客户端

---

## 4. 部署与配置要求 (Deployment & Configuration)

### 环境依赖

**必需的外部库**:
- **httplib**:HTTP客户端库(包含在项目中)
- **nlohmann/json**:JSON处理库(版本3.10+)
- **cpp-mcp**:MCP协议实现库(包含在libs/目录)

**LLM服务(至少选择一种)**:
- **本地模型**:
  - LM Studio(推荐):图形化界面,简单易用
  - Ollama:命令行工具,支持多种模型
  - llama.cpp:高性能推理引擎

- **云API**:
  - OpenAI API:需要API密钥
  - Azure OpenAI:企业级服务
  - Anthropic Claude API

**编译器要求**:
- GCC 9.0+ 或 Clang 10.0+
- 支持 C++20 标准
- 链接选项:`-lstdc++ -lpthread`

### 安装LM Studio(推荐)

**下载与安装**:
```bash
# 访问LM Studio官网下载
# https://lmstudio.ai/

# 或使用命令行(仅示例,实际请访问官网)
wget https://lmstudio.ai/download/linux
sudo dpkg -i lmstudio_*.deb
```

**配置本地模型**:
1. 打开LM Studio
2. 搜索并下载模型(如 `qwen2.5:7b`)
3. 启动本地服务器(Settings → Server)
4. 默认端口:1234
5. API端点:`http://localhost:1234/v1`(代码中自动添加/v1/)

### 配置文件(.env)

在项目根目录创建`.env`文件:

```env
# ============ LLM服务配置 ============

# 本地模型(LM Studio)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=qwen2.5:7b
LLM_MAX_TOKENS=4096
LLM_TEMPERATURE=0.7
LLM_TIMEOUT=60

# 或使用OpenAI API
# LLM_BASE_URL=https://api.openai.com/v1
# LLM_API_KEY=sk-your-api-key-here
# LLM_MODEL=gpt-4-turbo

# ============ 上下文窗口配置 ============

# 模型的上下文窗口大小(tokens)
LLM_CONTEXT_LENGTH=4096

# 为系统提示词和响应预留的tokens
LLM_RESERVED_TOKENS=512

# 每个token的字符数(中文~1.5, 英文~4.0)
LLM_CHARS_PER_TOKEN=4.0

# ============ 分块分析配置 ============

# 启用大文件的分块分析
LLM_ENABLE_CHUNKED=true

# 每块的大小(字符数)
LLM_CHUNK_SIZE=2000

# 块之间的重叠大小(保持上下文连续性)
LLM_OVERLAP_SIZE=200

# 最大分析块数
LLM_MAX_CHUNKS=5

# 是否在句子/段落边界分割
LLM_SMART_BOUNDARY=true

# ============ MCP服务器配置 ============

# MCP服务端口
MCP_PORT=8890

# 允许访问的路径白名单(逗号分隔)
MCP_ALLOWED_PATHS=/data/extracted,/tmp/forensic_analysis

# ============ 批量分析配置 ============

# 批处理的最大并发数
BATCH_MAX_PARALLEL=5

# 每个文件的最大内容长度(字符)
BATCH_MAX_CONTENT_LENGTH=10000

# 批处理的超时时间(秒)
BATCH_TIMEOUT=300
```

### C++ 编程接口

**基础用法**:
```cpp
#include "LLMIntegration/LLMClient.h"
#include "LLMIntegration/ModelRouter.h"
#include "LLMIntegration/FileAnalyzer.h"
#include "LLMIntegration/ConfigManager.h"

using namespace forensics::llm;

// 1. 加载配置
ConfigManager::instance().load(".env");

// 2. 创建LLM客户端
LLMConfig config;
config.baseUrl = "http://localhost:1234";
config.model = "qwen2.5:7b";
config.maxTokens = 2048;
config.temperature = 0.7;

LLMClient client(config);

// 测试连接
if (client.testConnection()) {
    std::cout << "LLM服务连接成功!" << std::endl;
} else {
    std::cerr << "连接失败: " << client.getLastError() << std::endl;
    return -1;
}

// 3. 发送聊天请求
std::vector<ChatMessage> messages = {
    {"system", "你是一个数字取证分析专家。"},
    {"user", "请分析这个文件的内容,并生成摘要。"}
};

LLMResponse response = client.chat(messages);

if (response.success) {
    std::cout << "LLM响应: " << response.content << std::endl;
    std::cout << "使用tokens: " << response.completionTokens << std::endl;
} else {
    std::cerr << "请求失败: " << response.errorMessage << std::endl;
}

// 4. 简单聊天
LLMResponse simpleResponse = client.chat(
    "分析这段代码的安全风险",
    "你是一个网络安全专家"
);

// 5. 查询可用模型
auto models = client.listModels();
for (const auto& model : models) {
    std::cout << "模型: " << model.name << std::endl;
    std::cout << "上下文窗口: " << model.contextLength << std::endl;
}
```

**多模型路由**:
```cpp
// 创建路由器
auto router = std::make_shared<ModelRouter>();

// 添加主模型
LLMConfig primaryConfig;
primaryConfig.baseUrl = "https://api.openai.com/v1";
primaryConfig.apiKey = "sk-...";
primaryConfig.model = "gpt-4-turbo";
primaryConfig.priority = 10;

ModelInfo primaryInfo;
primaryInfo.name = "GPT-4 Turbo";
primaryInfo.capabilities = {
    ModelCapability::TextGeneration,
    ModelCapability::Summarization,
    ModelCapability::Analysis
};
primaryInfo.contextLength = 128000;

router->addModel("gpt4", primaryConfig, primaryInfo);

// 添加备用模型
LLMConfig fallbackConfig;
fallbackConfig.baseUrl = "http://localhost:1234";
fallbackConfig.model = "qwen2.5:7b";
fallbackConfig.priority = 5;

ModelInfo fallbackInfo;
fallbackInfo.name = "Qwen 2.5 7B";
fallbackInfo.capabilities = {ModelCapability::TextGeneration};
fallbackInfo.contextLength = 32768;

router->addModel("qwen", fallbackConfig, fallbackInfo);

// 设置路由策略
router->setStrategy(RoutingStrategy::Fallback);
router->setPreferredModel("gpt4");

// 使用路由器发送请求
LLMResponse response = router->chat(messages);

// 查询最后使用的模型
std::cout << "使用的模型: " << router->getLastUsedModel() << std::endl;
```

**文件分析**:
```cpp
// 创建文件分析器
FileAnalyzer analyzer(router);

// 分析单个文件
AnalysisResult result = analyzer.analyzeFile("/path/to/document.txt");

if (result.success) {
    std::cout << "文件: " << result.filePath << std::endl;
    std::cout << "摘要: " << result.summary << std::endl;
    std::cout << "描述: " << result.description << std::endl;
    std::cout << "关键词: ";
    for (const auto& kw : result.keywords) {
        std::cout << kw << ", ";
    }
    std::cout << std::endl;
    std::cout << "使用的模型: " << result.modelUsed << std::endl;
    std::cout << "分析时间: " << result.analysisTimeMs << " ms" << std::endl;
}

// 批量分析
BatchAnalysisRequest request;
request.filePaths = {
    "/path/to/file1.txt",
    "/path/to/file2.doc",
    "/path/to/file3.pdf"
};
request.generateSummary = true;
request.generateDescription = true;
request.extractKeywords = true;
request.maxContentLength = 5000;

// 设置进度回调
analyzer.setProgressCallback([](size_t current, size_t total, const std::string& file) {
    double percent = 100.0 * current / total;
    std::cout << "[" << percent << "%] 分析: " << file << std::endl;
});

auto results = analyzer.analyzeBatch(request);

// 自定义提示词
analyzer.setSummaryPrompt(
    "请为以下文件生成简洁的摘要(不超过100字),"
    "重点说明文件的用途和敏感度。"
);

analyzer.setKeywordPrompt(
    "从以下文件中提取5-10个最重要的关键词,"
    "关注人物、组织、时间、地点等实体。"
);
```

**MCP服务器**:
```cpp
// 创建MCP集成
MCPIntegration mcp(router, 8890);

// 配置安全路径
mcp.setAllowedPaths({
    "/data/extracted_files",
    "/tmp/forensic_analysis"
});

// 注册自定义工具
mcp.registerTool(
    "search_suspicious_files",
    "搜索与案件相关的可疑文件",
    R"({
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "搜索关键词列表"
            },
            "file_type": {
                "type": "string",
                "description": "文件类型过滤(如.txt,.pdf)"
            }
        },
        "required": ["keywords"]
    })",
    [](const std::string& argsJson) -> std::string {
        // 解析参数
        auto args = nlohmann::json::parse(argsJson);
        std::vector<std::string> keywords = args["keywords"];
        std::string fileType = args.value("file_type", "");

        // 执行搜索
        auto results = searchFiles(keywords, fileType);

        // 返回结果
        return results.dump();
    }
);

// 启动服务器(阻塞模式)
mcp.start(true);

// 或非阻塞模式
mcp.start(false);
// 主线程继续执行...

// 查询已注册工具
auto tools = mcp.getRegisteredTools();
std::cout << "已注册工具: ";
for (const auto& tool : tools) {
    std::cout << tool << ", ";
}
std::cout << std::endl;
```

---

## 5. 接口与集成说明 (API & Integration)

### C++ 核心接口

**LLMClient主要接口**:
```cpp
class LLMClient {
public:
    // 构造函数
    explicit LLMClient(const LLMConfig& config);
    explicit LLMClient(const std::string& baseUrl);

    // 连接测试
    bool testConnection();

    // 聊天完成
    LLMResponse chat(const std::vector<ChatMessage>& messages,
                     const std::string& toolsJson = "");
    LLMResponse chat(const std::string& prompt,
                     const std::string& systemPrompt = "");

    // 模型管理
    std::vector<ModelInfo> listModels();
    void setModel(const std::string& model);
    std::string getModel() const;

    // 配置管理
    void setConfig(const LLMConfig& config);
    const LLMConfig& getConfig() const;

    // 状态查询
    bool isReady() const;
    std::string getLastError() const;
};
```

**ModelRouter主要接口**:
```cpp
class ModelRouter {
public:
    // 模型管理
    void addModel(const std::string& name,
                  const LLMConfig& config,
                  const ModelInfo& info);
    void removeModel(const std::string& name);

    // 路由策略
    void setStrategy(RoutingStrategy strategy);
    RoutingStrategy getStrategy() const;

    // 聊天路由
    LLMResponse chat(const std::vector<ChatMessage>& messages,
                     ModelCapability requiredCapability = ModelCapability::TextGeneration);
    LLMResponse chat(const std::string& prompt,
                     const std::string& systemPrompt = "");

    // 模型信息
    std::vector<std::string> getModelNames() const;
    ModelInfo getModelInfo(const std::string& name) const;
    bool hasAvailableModels() const;

    // 健康检查
    void refreshAvailability();

    // 优先级
    void setPreferredModel(const std::string& name);
    std::string getLastUsedModel() const;
    const LLMConfig& getConfig() const;
};
```

**FileAnalyzer主要接口**:
```cpp
class FileAnalyzer {
public:
    // 构造函数
    explicit FileAnalyzer(std::shared_ptr<ModelRouter> router);

    // 文件分析
    AnalysisResult analyzeFile(const std::string& filePath,
                               size_t maxContentLength = 10000);

    // 批量分析
    std::vector<AnalysisResult> analyzeBatch(const BatchAnalysisRequest& request);

    // 内容生成
    std::string summarize(const std::string& content,
                          const std::string& context = "");
    std::string generateDescription(const std::string& filePath);
    std::string generateDescription(const std::vector<std::string>& filePaths);
    std::vector<std::string> extractKeywords(const std::string& content,
                                              size_t maxKeywords = 10);

    // 提示词配置
    void setSummaryPrompt(const std::string& prompt);
    void setDescriptionPrompt(const std::string& prompt);
    void setKeywordPrompt(const std::string& prompt);

    // 进度回调
    using ProgressCallback = std::function<void(size_t, size_t, const std::string&)>;
    void setProgressCallback(ProgressCallback callback);

    // 大文件处理
    void setChunkConfig(const ChunkConfig& config);
    const ChunkConfig& getChunkConfig() const;
    AnalysisResult analyzeFileChunked(const std::string& filePath);

    // Token估算
    static size_t estimateTokens(const std::string& content,
                                  double charsPerToken = 4.0);
    size_t calculateMaxContentLength() const;
    std::string truncateContent(const std::string& content,
                                size_t maxLength) const;
};
```

### REST API 集成

**通过HTTP服务使用LLM分析** (port 8080):
```bash
# 分析单个文件
POST /api/llm/analyze
Content-Type: application/json

{
  "file_path": "/data/extracted/document.txt",
  "generate_summary": true,
  "generate_description": true,
  "extract_keywords": true
}

# 响应
{
  "success": true,
  "file_path": "/data/extracted/document.txt",
  "summary": "这是一份保密协议文档...",
  "description": "ABC公司与XYZ项目的保密协议...",
  "keywords": ["保密", "协议", "ABC公司", "商业机密"],
  "model_used": "gpt-4-turbo",
  "tokens_used": 1234,
  "analysis_time_ms": 2345
}

# 批量分析
POST /api/llm/batch-analyze
Content-Type: application/json

{
  "task_id": "task_123",
  "file_filter": {
    "category": "documents"
  },
  "max_parallel": 5
}

# 查询批量任务状态
GET /api/llm/batch-analyze/job_789
```

### Python 集成示例

虽然核心是C++实现,但可通过REST API使用:

```python
import httpx
import json

class LLMAnalysisClient:
    def __init__(self, base_url="http://localhost:8080"):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)  # 5分钟超时

    async def analyze_file(self, file_path: str, **options):
        """分析单个文件"""
        response = await self.client.post(
            f"{self.base_url}/api/llm/analyze",
            json={
                "file_path": file_path,
                **options
            }
        )
        return response.json()

    async def batch_analyze(self, task_id: str, **filters):
        """批量分析文件"""
        response = await self.client.post(
            f"{self.base_url}/api/llm/batch-analyze",
            json={
                "task_id": task_id,
                **filters
            }
        )
        return response.json()

    async def get_batch_status(self, job_id: str):
        """查询批量任务状态"""
        response = await self.client.get(
            f"{self.base_url}/api/llm/batch-analyze/{job_id}"
        )
        return response.json()

# 使用示例
async def main():
    client = LLMAnalysisClient()

    # 分析单个文件
    result = await client.analyze_file(
        "/data/extracted/document.pdf",
        generate_summary=True,
        generate_description=True,
        extract_keywords=True
    )

    print(f"文件: {result['file_path']}")
    print(f"摘要: {result['summary']}")
    print(f"关键词: {', '.join(result['keywords'])}")

    # 批量分析
    job = await client.batch_analyze(
        task_id="task_123",
        file_filter={"category": "documents"},
        max_parallel=5
    )

    job_id = job['job_id']
    print(f"批量分析任务已创建: {job_id}")

    # 查询状态
    while True:
        status = await client.get_batch_status(job_id)
        print(f"进度: {status['progress']}%")

        if status['status'] == 'completed':
            print(f"完成! 分析了 {status['analyzed_count']} 个文件")
            break

        await asyncio.sleep(5)

import asyncio
asyncio.run(main())
```

---

## 6. 常见问题 (FAQ)

**Q1:支持哪些LLM提供商?如何配置?**

A:支持任何OpenAI兼容的API:

**支持的提供商**:
1. **本地模型**(推荐用于敏感数据):
   - LM Studio:`http://localhost:1234/v1`
   - Ollama:`http://localhost:11434/v1`
   - llama.cpp:自定义端口

2. **云API**:
   - OpenAI:`https://api.openai.com/v1`
   - Azure OpenAI:`https://your-resource.openai.azure.com/`
   - DeepSeek:`https://api.deepseek.com/v1`
   - Groq:`https://api.groq.com/openai/v1`

**配置方法**:
```env
# 本地模型(LM Studio)
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=qwen2.5:7b
LLM_API_KEY=  # 留空,本地模型不需要

# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL=gpt-4-turbo

# DeepSeek(中国用户推荐)
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-your-deepseek-key
LLM_MODEL=deepseek-chat
```

**推荐选择**:
- **高隐私要求**:本地LM Studio + Qwen 2.5
- **高质量分析**:OpenAI GPT-4 Turbo
- **性价比**:DeepSeek(中文优秀,价格低)
- **企业级**:Azure OpenAI

---

**Q2:如何提高LLM分析质量?**

A:多维度优化分析质量:

**1. 选择更强大的模型**
```cpp
// 使用GPT-4而非GPT-3.5
LLMConfig config;
config.model = "gpt-4-turbo";  // 而非 "gpt-3.5-turbo"
config.contextLength = 128000;  // 更大的上下文窗口
```

**2. 优化提示词(Prompt Engineering)**
```cpp
// 差的提示词
analyzer.setSummaryPrompt("总结这个文件");

// 好的提示词
analyzer.setSummaryPrompt(
    "你是一位资深的数字取证分析专家。请分析以下文件内容,"
    "生成100字左右的摘要,重点关注:"
    "1. 文件的主要用途和性质"
    "2. 涉及的人物、组织、时间等关键信息"
    "3. 是否包含敏感或机密内容"
    "4. 对案件的潜在价值"
    "请用专业、准确的语言描述。"
);
```

**3. 提供丰富上下文**
```cpp
// 在分析前提供案件背景
std::string context =
    "案件背景:员工离职前可能窃取了公司机密资料。"
    "分析重点:识别与保密协议、客户名单、技术文档相关的内容。";

result = analyzer.analyzeFile(filePath);
// 或在system prompt中包含上下文
```

**4. 使用Few-shot示例**
```cpp
std::string systemPrompt =
    "以下是文件摘要的示例格式:\n"
    "示例1:\n"
    "文件:合同.pdf\n"
    "摘要:ABC公司与XYZ项目的保密协议,包含商业机密条款,有效期至2026年\n\n"
    "示例2:\n"
    "文件:预算.xlsx\n"
    "摘要:2024年Q1财务预算表,包含各部门预算分配和支出预测\n\n"
    "请按照以上格式生成摘要。";

response = client.chat(userPrompt, systemPrompt);
```

**5. 多模型交叉验证**
```cpp
// 使用两个不同的模型分析同一文件
auto router = std::make_shared<ModelRouter>();

router->addModel("gpt4", gpt4Config, gpt4Info);
router->addModel("claude", claudeConfig, claudeInfo);

auto result1 = analyzer1.analyzeFile(filePath);
auto result2 = analyzer2.analyzeFile(filePath);

// 比较结果,找出一致性较高的结论
```

**6. 调整Temperature参数**
```cpp
// 低temperature(0.1-0.3):更确定、一致的结果
config.temperature = 0.2;  // 适用于事实性分析

// 高temperature(0.7-1.0):更多样、创造性的结果
config.temperature = 0.8;  // 适用于开放性分析
```

---

**Q3:LLM分析速度如何?如何优化?**

A:速度分析和优化:

**典型响应时间** (Intel i7, RTX 3080):

| 模型类型 | 模型示例 | 单文件分析 | 批量(100文件) |
|---------|---------|------------|---------------|
| 本地7B | Qwen 2.5 7B | 2-5秒 | 5-10分钟 |
| 本地14B | Qwen 2.5 14B | 5-10秒 | 15-30分钟 |
| 云API | GPT-3.5 Turbo | 1-3秒 | 3-8分钟 |
| 云API | GPT-4 Turbo | 3-8秒 | 10-25分钟 |

**优化策略**:

**1. 使用本地模型**
- 优势:无网络延迟,可并发处理
- 劣势:需要GPU加速(CPU慢10-20倍)
- 建议:使用RTX 3060以上显卡

**2. 并发批处理**
```cpp
BatchAnalysisRequest request;
request.filePaths = fileList;
request.maxContentLength = 5000;  // 限制内容长度

// 设置并发数
request.maxParallel = 5;  // 同时分析5个文件

auto results = analyzer.analyzeBatch(request);
```

**3. 限制Token使用**
```cpp
// 降低max_tokens减少响应时间
config.maxTokens = 1024;  // 而非 4096

// 限制发送的内容长度
request.maxContentLength = 3000;  // 只发送前3000字符
```

**4. 使用更小的模型**
```cpp
// 对于简单任务,小模型足够
config.model = "qwen2.5:3b";  // 比7B快2-3倍
```

**5. 缓存分析结果**
```cpp
// 分析前检查缓存
if (isAnalyzed(filePath)) {
    return getCachedResult(filePath);
}

// 分析后保存缓存
saveToCache(filePath, result);
```

---

**Q4:如何降低LLM API成本?**

A:多策略降低成本:

**1. 使用本地模型(零API成本)**
```bash
# 安装LM Studio(免费)
# 下载开源模型(免费)
# 本地推理,零API费用
```

**2. 混合策略**
```cpp
// 大部分文件用本地模型分析
LLMConfig localConfig;
localConfig.model = "qwen2.5:7b";  // 本地

// 仅关键文件用GPT-4复核
LLMConfig premiumConfig;
premiumConfig.model = "gpt-4-turbo";  // 云API

router->addModel("local", localConfig, localInfo);
router->addModel("premium", premiumConfig, premiumInfo);
router->setStrategy(RoutingStrategy::Fallback);
```

**3. 批量处理减少请求次数**
```cpp
// 不好的做法:每个文件单独请求
for (const auto& file : files) {
    analyzer.analyzeFile(file);  // 1000次请求
}

// 好的做法:批量处理
BatchAnalysisRequest request;
request.filePaths = files;  // 一次批量请求
auto results = analyzer.analyzeBatch(request);
```

**4. 限制输入Token**
```cpp
// 使用摘要而非全文
std::string summary = generateQuickSummary(content);  // 本地规则
analyzer.analyze(summary);  // 仅发送摘要给LLM

// 或仅发送前N字符
request.maxContentLength = 3000;  // 而非全文
```

**5. 使用更经济的API**
| 提供商 | 模型 | 价格(每1M tokens) |
|--------|------|-----------------|
| OpenAI | GPT-3.5 Turbo | $0.50 |
| OpenAI | GPT-4 Turbo | $10.00 |
| DeepSeek | DeepSeek Chat | $0.14 (国内) |
| Groq | Llama 3 8B | $0.05 |
| 本地模型 | 任何 | $0.00 |

**成本估算示例**:
- 1000个文件,每个文件1000字
- GPT-3.5 Turbo:约$2-5
- GPT-4 Turbo:约$20-50
- DeepSeek:约$0.5-2
- 本地模型:$0(仅电费)

---

**Q5:数据隐私如何保障?**

A:多层次数据安全保护:

**1. 使用本地模型(最安全)**
```cpp
// 完全本地处理,数据不离开网络
LLMConfig config;
config.baseUrl = "http://localhost:1234";  // 本地LM Studio
```

**2. 数据脱敏**
```cpp
// 发送给LLM前移除敏感信息
std::string sanitizeContent(const std::string& content) {
    std::string sanitized = content;

    // 移除身份证号
    sanitized = std::regex_replace(sanitized,
        std::regex("\\d{15}[\\dXx]"), "[身份证号]");

    // 移除手机号
    sanitized = std::regex_replace(sanitized,
        std::regex("1[3-9]\\d{9}"), "[手机号]");

    // 移除邮箱
    sanitized = std::regex_replace(sanitized,
        std::regex("\\b[\\w.-]+@[\\w.-]+\\.\\w+\\b"), "[邮箱]");

    return sanitized;
}
```

**3. HTTPS加密传输**
```cpp
// 云API使用HTTPS
config.baseUrl = "https://api.openai.com/v1";  // 而非 http://
```

**4. 路径白名单(MCP)**
```cpp
MCPIntegration mcp(router, 8890);
mcp.setAllowedPaths({
    "/data/extracted",  // 仅允许这些路径
    "/tmp/forensic"
});
// 其他路径的访问将被拒绝
```

**5. 审计日志**
```cpp
// 所有LLM请求都记录在审计日志中
AuditLog::instance().log(
    "llm_request",
    "file=" + filePath +
    ", model=" + modelUsed +
    ", tokens=" + std::to_string(tokensUsed)
);
```

**6. 选择隐私友好的提供商**
- 检查提供商的数据保留政策
- OpenAI:不会用API数据训练模型(企业协议)
- Azure OpenAI:企业级隐私保证
- 本地模型:完全控制

**最佳实践建议**:
1. **敏感取证**:优先使用本地模型
2. **非敏感分析**:可使用云API提高效率
3. **混合策略**:本地初筛,云API复核
4. **法律合规**:遵守当地数据保护法规(GDPR等)

---

**Q6:如何处理LLM的幻觉(Hallucination)问题?**

A:多策略降低幻觉风险:

**1. 降低Temperature**
```cpp
// 低temperature减少随机性
config.temperature = 0.1;  // 而非 0.7
```

**2. 明确要求不确定性**
```cpp
std::string prompt =
    "如果文件内容不足以得出确切结论,请明确说明'无法确定',"
    "不要编造信息。"
    "如果对某个判断的置信度低于80%,请使用'可能'等不确定词汇。";
```

**3. 要求引用原文**
```cpp
std::string prompt =
    "请在摘要中引用原文的关键语句,用引号标出。"
    "例如:'文件提到'保密协议的有效期为3年'。'";
```

**4. 多模型交叉验证**
```cpp
// 使用多个模型分析,比较结果
auto result1 = analyzer1.analyzeFile(filePath);
auto result2 = analyzer2.analyzeFile(filePath);

// 仅当多个模型一致时才采信
if (result1.summary == result2.summary) {
    return result1.summary;  // 高置信度
} else {
    return "[需要人工复核] " + result1.summary;  // 低置信度
}
```

**5. 限制回答范围**
```cpp
std::string prompt =
    "请仅基于提供的文件内容回答,不要引入外部知识。"
    "如果文件中没有提及某个方面,请明确说明'文件未提及'。";
```

**6. 人工复核机制**
```cpp
// 对低置信度结果标记人工复核
if (result.confidence < 0.8) {
    result.needsReview = true;
    addToReviewQueue(result);
}
```

**技术支持**:
- LM Studio:https://lmstudio.ai
- OpenAI API:https://platform.openai.com/docs
