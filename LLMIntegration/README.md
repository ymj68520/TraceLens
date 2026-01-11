# LLMIntegration Module

LLM (Large Language Model) integration module for forensic file analysis using LM Studio or any OpenAI-compatible API.

## Features

- **OpenAI-Compatible API Client** - Connect to LM Studio or other local/remote LLM servers
- **Multi-Model Routing** - Route requests to multiple models with fallback and load balancing
- **Content-Type Based Routing** - Automatically route text to GPT OSS and images to Qwen3 VL
- **MCP Protocol Support** - Expose file analysis tools via Model Context Protocol
- **File Analysis** - Generate summaries, descriptions, and keywords for files
- **Vision Analysis** - Analyze images, extract text (OCR), and compare images

## Components

| Component | Description |
|-----------|-------------|
| `LLMClient` | HTTP client for OpenAI-compatible chat completions API |
| `ModelRouter` | Multi-model routing with priority, round-robin, and fallback strategies |
| `MCPIntegration` | MCP server with file analysis tools |
| `FileAnalyzer` | High-level file analysis with LLM (text model) |
| `VisionAnalyzer` | Image/video analysis with vision models (Qwen3 VL) |
| `ConfigManager` | Load configuration from `.env` file |

## Usage

### Basic LLM Client

```cpp
#include "LLMIntegration/LLMClient.h"

using namespace forensics::llm;

// Connect to LM Studio (default: localhost:1234)
LLMConfig config;
config.baseUrl = "http://localhost:1234";
config.model = "your-model-name";

LLMClient client(config);

// Test connection
if (client.testConnection()) {
    // Simple chat
    auto response = client.chat("Summarize this file content...", 
                                 "You are a file analyst.");
    if (response.success) {
        std::cout << response.content << std::endl;
    }
}
```

### Multi-Model Router

```cpp
#include "LLMIntegration/ModelRouter.h"

using namespace forensics::llm;

auto router = std::make_shared<ModelRouter>();

// Add multiple models
LLMConfig config1, config2;
config1.baseUrl = "http://localhost:1234";
config2.baseUrl = "http://localhost:5678";

ModelInfo info1, info2;
info1.name = "model1";
info1.priority = 10;
info2.name = "model2";
info2.priority = 5;

router->addModel("primary", config1, info1);
router->addModel("backup", config2, info2);

// Set routing strategy
router->setStrategy(RoutingStrategy::Fallback);

// Requests automatically route to best available model
auto response = router->chat("Analyze this...");
```

### File Analysis

```cpp
#include "LLMIntegration/FileAnalyzer.h"

using namespace forensics::llm;

auto router = std::make_shared<ModelRouter>();
// ... configure router ...

FileAnalyzer analyzer(router);

// Analyze a single file
auto result = analyzer.analyzeFile("/path/to/file.txt");
if (result.success) {
    std::cout << "Summary: " << result.summary << std::endl;
    std::cout << "Description: " << result.description << std::endl;
    for (const auto& kw : result.keywords) {
        std::cout << "  - " << kw << std::endl;
    }
}

// Batch analysis
BatchAnalysisRequest request;
request.filePaths = {"/path/to/file1.txt", "/path/to/file2.log"};
auto results = analyzer.analyzeBatch(request);
```

### MCP Server

```cpp
#include "LLMIntegration/MCPIntegration.h"

using namespace forensics::llm;

auto router = std::make_shared<ModelRouter>();
// ... configure router ...

MCPIntegration mcp(router, 8890);

// Restrict file access paths
mcp.setAllowedPaths({"/data/forensics", "/tmp/analysis"});

// Start server (blocks)
mcp.start(true);
```

## MCP Tools

The MCP server exposes these tools:

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents |
| `analyze_file` | Analyze and summarize file using LLM |
| `list_files` | List directory contents |
| `generate_description` | Generate natural language file descriptions |

## Dependencies

- **cpp-mcp** - MCP protocol implementation (in `libs/cpp-mcp/`)
- **cpp-dotenv** - Environment variable loading (in `libs/cpp-dotenv/`)
- **httplib** - HTTP client (bundled with cpp-mcp)
- **nlohmann/json** - JSON parsing (bundled with cpp-mcp)

## Configuration

All configuration is stored in the `.env` file at project root. Use `ConfigManager` for typed access:

```cpp
#include "LLMIntegration/ConfigManager.h"

using namespace forensics::llm;

// Load configuration
ConfigManager::instance().load(".env");

// Get LLM config
LLMConfig config = ConfigManager::instance().getLLMConfig();

// Or access individual values
std::string baseUrl = ConfigManager::instance().getLLMBaseUrl();
int maxTokens = ConfigManager::instance().getLLMMaxTokens();
```

### Available Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_BASE_URL` | `http://localhost:1234` | LM Studio API URL |
| `LLM_ENDPOINT` | `/v1/chat/completions` | API endpoint |
| `LLM_MODEL` | (auto) | Model name |
| `LLM_MAX_TOKENS` | `2048` | Max response tokens |
| `LLM_TEMPERATURE` | `0.7` | Sampling temperature |
| `MCP_SERVER_PORT` | `8890` | MCP server port |
| `FILE_ANALYSIS_MAX_CONTENT` | `10000` | Max chars to analyze |
