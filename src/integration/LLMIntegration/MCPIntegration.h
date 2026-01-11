#pragma once

#include "LLMDataTypes.h"
#include "ModelRouter.h"
#include <memory>
#include <functional>
#include <string>
#include <vector>
#include <map>

// Forward declarations for MCP types
namespace mcp {
    class server;
    struct tool;
}

namespace forensics {
namespace llm {

/**
 * @brief MCP tool handler function type
 */
using MCPToolHandler = std::function<std::string(const std::string& argsJson)>;

/**
 * @brief MCP Protocol integration for file analysis
 * 
 * Registers file analysis tools with MCP server:
 * - read_file: Read file contents
 * - analyze_file: Analyze and summarize file
 * - list_files: List directory contents
 * - generate_description: Generate file description
 */
class MCPIntegration {
public:
    /**
     * @brief Constructor
     * @param router Model router for LLM requests
     * @param port MCP server port (default: 8890)
     */
    MCPIntegration(std::shared_ptr<ModelRouter> router, int port = 8890);
    ~MCPIntegration();
    
    // Non-copyable
    MCPIntegration(const MCPIntegration&) = delete;
    MCPIntegration& operator=(const MCPIntegration&) = delete;
    
    /**
     * @brief Start the MCP server
     * @param blocking If true, blocks until server stops
     */
    void start(bool blocking = false);
    
    /**
     * @brief Stop the MCP server
     */
    void stop();
    
    /**
     * @brief Check if server is running
     */
    bool isRunning() const;
    
    /**
     * @brief Register a custom tool
     * @param name Tool name
     * @param description Tool description
     * @param parametersJson JSON schema for parameters
     * @param handler Tool handler function
     */
    void registerTool(const std::string& name,
                      const std::string& description,
                      const std::string& parametersJson,
                      MCPToolHandler handler);
    
    /**
     * @brief Get server port
     */
    int getPort() const;
    
    /**
     * @brief Set allowed paths for file operations
     */
    void setAllowedPaths(const std::vector<std::string>& paths);
    
    /**
     * @brief Get list of registered tool names
     */
    std::vector<std::string> getRegisteredTools() const;

private:
    std::shared_ptr<ModelRouter> router_;
    std::unique_ptr<mcp::server> server_;
    int port_;
    bool running_ = false;
    std::vector<std::string> allowedPaths_;
    std::map<std::string, MCPToolHandler> customHandlers_;
    
    // Built-in tool handlers
    std::string handleReadFile(const std::string& argsJson);
    std::string handleAnalyzeFile(const std::string& argsJson);
    std::string handleListFiles(const std::string& argsJson);
    std::string handleGenerateDescription(const std::string& argsJson);
    
    void registerBuiltinTools();
    bool isPathAllowed(const std::string& path) const;
    std::string readFileContent(const std::string& path, size_t maxBytes = 0);
};

} // namespace llm
} // namespace forensics
