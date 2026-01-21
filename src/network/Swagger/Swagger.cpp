#include "Swagger.h"
#include <iostream>

namespace forensics {

Swagger& Swagger::instance() {
    static Swagger instance;
    return instance;
}

Swagger::Swagger() {}

void Swagger::RegisterEndpoint(
    const std::string& path,
    const std::string& method,
    const std::string& summary,
    const std::string& description,
    const std::vector<std::string>& tags,
    const std::vector<Parameter>& parameters,
    const std::vector<Response>& responses
) {
    std::lock_guard<std::mutex> lock(mutex_);

    Operation op;
    op.method = method;
    op.summary = summary;
    op.description = description;
    op.tags = tags;
    op.parameters = parameters;
    op.responses = responses;

    paths_[path].push_back(op);
}

nlohmann::json Swagger::GetSwaggerJSON() const {
    std::lock_guard<std::mutex> lock(mutex_);

    nlohmann::json doc;
    doc["openapi"] = "3.0.0";
    doc["info"] = {
        {"title", "ForensicsProject C++ Service"},
        {"description", "C++ HTTP Backend for ForensicsProject digital forensics tool."},
        {"version", "1.0.0"}
    };
    doc["paths"] = nlohmann::json::object();

    for (const auto& [path, operations] : paths_) {
        // Convert Crow path syntax to OpenAPI syntax if needed (e.g., /api/extract/<string> -> /api/extract/{job_id})
        // For now, we'll keep it simple and assume manual correction or just use as is unless we add regex replacement.
        // Simple heuristic: replace <string>, <int> etc with {}
        
        std::string openapi_path = path;
        size_t pos = 0;
        while ((pos = openapi_path.find("<string>", pos)) != std::string::npos) {
            openapi_path.replace(pos, 8, "{param}");
            pos += 7;
        }
        pos = 0;
        while ((pos = openapi_path.find("<int>", pos)) != std::string::npos) {
            openapi_path.replace(pos, 5, "{id}");
            pos += 4;
        }

        nlohmann::json path_item;
        
        for (const auto& op : operations) {
            nlohmann::json operation;
            operation["summary"] = op.summary;
            operation["description"] = op.description;
            operation["tags"] = op.tags;
            
            operation["parameters"] = nlohmann::json::array();
            for (const auto& param : op.parameters) {
                nlohmann::json p;
                p["name"] = param.name;
                p["in"] = param.in;
                p["description"] = param.description;
                p["required"] = param.required;
                p["schema"] = {{"type", param.type}};
                operation["parameters"].push_back(p);
            }

            operation["responses"] = nlohmann::json::object();
            for (const auto& resp : op.responses) {
                nlohmann::json r;
                r["description"] = resp.description;
                if (!resp.schema.is_null()) {
                    r["content"] = {
                        {"application/json", {
                            {"schema", resp.schema}
                        }}
                    };
                }
                operation["responses"][std::to_string(resp.code)] = r;
            }

            // Convert method to lowercase
            std::string method_lower = op.method;
            std::transform(method_lower.begin(), method_lower.end(), method_lower.begin(), ::tolower);
            
            path_item[method_lower] = operation;
        }

        doc["paths"][openapi_path] = path_item;
    }

    return doc;
}

} // namespace forensics
