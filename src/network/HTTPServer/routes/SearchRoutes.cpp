#include "SearchRoutes.h"
#include "../../Swagger/Swagger.h"
#include "RouteHelpers.h"
#include "FullTextSearch.h"
#include "TextExtractor.h"
#include "../../core/PathManager/PathManager.h"
#include <filesystem>
#include <cstdlib>

namespace forensics {

using json = nlohmann::json;

// Confine a user-supplied filesystem path to an allowed root so the indexer
// cannot read/return arbitrary files (e.g. /etc/passwd). The root defaults to
// PathManager's data dir; operators can widen it via FTS_ALLOWED_ROOT.
static bool fts_path_within_allowed_root(const std::string& p, std::string& allowed_out) {
    namespace fs = std::filesystem;
    fs::path allowed;
    if (const char* env = std::getenv("FTS_ALLOWED_ROOT"); env && *env) {
        allowed = fs::path(env);
    } else {
        allowed = PathManager::instance().getDataDir();
    }
    std::error_code ec;
    fs::path allowed_canon = fs::weakly_canonical(allowed, ec);
    if (ec) allowed_canon = fs::absolute(allowed);
    allowed_out = allowed_canon.string();

    ec.clear();
    fs::path cand = fs::weakly_canonical(fs::path(p), ec);
    if (ec) cand = fs::absolute(fs::path(p));
    fs::path rel = cand.lexically_relative(allowed_canon);
    return !rel.empty() && (*rel.begin()) != "..";
}

SearchRoutes::SearchRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/search/fulltext").methods("GET"_method)([this](const crow::request& req) {
        return handle_fulltext_search(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/search/fulltext", "GET",
        "Full-text search",
        "Search for text content across analyzed files.",
        {"Search"},
        {
            {"q", "query", "Search query term", true},
            {"index", "query", "Index path", false},
            {"limit", "query", "Results limit", false, "integer"},
            {"offset", "query", "Pagination offset", false, "integer"}
        },
        {{200, "Search results"}, {400, "Missing query or parameters"}, {500, "Internal server error"}}
    );

    CROW_ROUTE(app, "/api/search/index").methods("POST"_method)([this](const crow::request& req) {
        return handle_fulltext_index(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/search/index", "POST",
        "Create search index",
        "Create or update a full-text search index for a given directory.",
        {"Search"},
        {},
        {{200, "Indexing result"}, {400, "Invalid parameters"}, {500, "Internal server error"}}
    );
}

crow::response SearchRoutes::handle_fulltext_search(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
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
    RouteHelpers::add_cors_headers(res);
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

        std::string allowed_root;
        if (!fts_path_within_allowed_root(source_path, allowed_root) ||
            !fts_path_within_allowed_root(index_path, allowed_root)) {
            json error = {{"error", "source_path/index_path must be under the allowed root"},
                          {"allowed_root", allowed_root},
                          {"hint", "set FTS_ALLOWED_ROOT to widen the permitted directory"}};
            res.code = 403;
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

} // namespace forensics
