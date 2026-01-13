#include "SearchRoutes.h"
#include "FullTextSearch.h"
#include "TextExtractor.h"
#include <filesystem>

namespace forensics {

using json = nlohmann::json;

SearchRoutes::SearchRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/search/fulltext").methods("GET"_method)([this](const crow::request& req) {
        return handle_fulltext_search(req);
    });

    CROW_ROUTE(app, "/api/search/index").methods("POST"_method)([this](const crow::request& req) {
        return handle_fulltext_index(req);
    });
}

crow::response SearchRoutes::handle_fulltext_search(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        std::string query = "";
        std::string index_path = "";
        int limit = 50;
        int offset = 0;

        if (req.url_params.get("q") != nullptr) {
            query = req.url_params.get("q");
        }
        if (req.url_params.get("index") != nullptr) {
            index_path = req.url_params.get("index");
        }
        if (req.url_params.get("limit") != nullptr) {
            limit = std::stoi(req.url_params.get("limit"));
        }
        if (req.url_params.get("offset") != nullptr) {
            offset = std::stoi(req.url_params.get("offset"));
        }

        if (query.empty()) {
            json error = {{"error", "Query parameter 'q' is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        if (index_path.empty()) {
            json error = {{"error", "Index path parameter 'index' is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        XapianSearcher searcher(index_path);
        auto results = searcher.search(query, limit, offset);

        json response = {
            {"query", query},
            {"results", json::array()},
            {"count", results.size()},
            {"limit", limit},
            {"offset", offset}
        };

        for (const auto& result : results) {
            response["results"].push_back(json{
                {"path", result.path},
                {"score", result.score},
                {"snippet", result.snippet}
            });
        }

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response SearchRoutes::handle_fulltext_index(const crow::request& req) {
    crow::response res;
    add_cors_headers(res);
    try {
        auto body = json::parse(req.body);

        std::string source_path = body.value("source_path", "");
        std::string index_path = body.value("index_path", "");
        bool recursive = body.value("recursive", true);

        if (source_path.empty() || index_path.empty()) {
            json error = {{"error", "Both source_path and index_path are required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        if (!std::filesystem::exists(source_path)) {
            json error = {{"error", "Source path does not exist"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        XapianIndexer indexer(index_path);
        int indexed_count = 0;

        if (std::filesystem::is_directory(source_path)) {
            // Index all files in directory
            for (const auto& entry : std::filesystem::recursive_directory_iterator(source_path)) {
                if (entry.is_regular_file()) {
                    TextExtractor extractor;
                    std::string content = extractor.extract(entry.path().string());
                    if (!content.empty()) {
                        indexer.addDocument(entry.path().string(), content);
                        indexed_count++;
                    }
                }
            }
            indexer.commit();
        } else {
            TextExtractor extractor;
            std::string content = extractor.extract(source_path);
            indexer.addDocument(source_path, content);
            indexer.commit();
            indexed_count = 1;
        }

        json response = {
            {"success", true},
            {"source_path", source_path},
            {"index_path", index_path},
            {"indexed_count", indexed_count}
        };

        res.set_header("Content-Type", "application/json");
        res.write(response.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

void SearchRoutes::add_cors_headers(crow::response& res) {
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

} // namespace forensics
