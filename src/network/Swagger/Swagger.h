#pragma once

#include <string>
#include <vector>
#include <map>
#include <nlohmann/json.hpp>
#include <mutex>
#include <memory>

namespace forensics {

class Swagger {
public:
    struct Parameter {
        std::string name;
        std::string in; // query, path, header, cookie
        std::string description;
        bool required = false;
        std::string type = "string";
    };

    struct Response {
        int code;
        std::string description;
        nlohmann::json schema; // Optional schema
    };

    struct Operation {
        std::string method;
        std::string summary;
        std::string description;
        std::vector<std::string> tags;
        std::vector<Parameter> parameters;
        std::vector<Response> responses;
    };

    static Swagger& instance();

    /**
     * @brief Register a new API endpoint
     * @param path The URL path (e.g. /api/users)
     * @param method HTTP method (GET, POST, etc.)
     * @param summary Short summary of the endpoint
     * @param description Detailed description
     * @param tags List of tags for grouping
     * @param parameters List of request parameters
     * @param responses List of possible responses
     */
    void RegisterEndpoint(
        const std::string& path,
        const std::string& method,
        const std::string& summary,
        const std::string& description,
        const std::vector<std::string>& tags = {},
        const std::vector<Parameter>& parameters = {},
        const std::vector<Response>& responses = {}
    );

    /**
     * @brief Generate OpenAPI 3.0 JSON specification
     * @return JSON object containing the full spec
     */
    nlohmann::json GetSwaggerJSON() const;

private:
    Swagger();
    ~Swagger() = default;
    
    // Non-copyable
    Swagger(const Swagger&) = delete;
    Swagger& operator=(const Swagger&) = delete;

    mutable std::mutex mutex_;
    std::map<std::string, std::vector<Operation>> paths_;
};

} // namespace forensics
