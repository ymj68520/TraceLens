#include <chrono>
#include <functional>
#include <stdexcept>
#include <string>
#include <thread>

#include <gtest/gtest.h>
#include <httplib.h>
#include <nlohmann/json.hpp>

#include "LLMIntegration/MarkitdownProxy.h"

namespace {

class LocalServer {
public:
    explicit LocalServer(std::function<void(httplib::Server&)> configure) {
        configure(server_);
        port_ = server_.bind_to_any_port("127.0.0.1");
        if (port_ < 0) {
            throw std::runtime_error("test server failed to bind");
        }
        thread_ = std::thread([this] { server_.listen_after_bind(); });
        for (int i = 0; i < 100 && !server_.is_running(); ++i) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        if (!server_.is_running()) {
            server_.stop();
            if (thread_.joinable()) thread_.join();
            throw std::runtime_error("test server did not start");
        }
    }
    ~LocalServer() {
        server_.stop();
        if (thread_.joinable()) thread_.join();
    }
    std::string url() const {
        return "http://127.0.0.1:" + std::to_string(port_);
    }
private:
    httplib::Server server_;
    int port_ = -1;
    std::thread thread_;
};

using forensics::llm::MarkitdownProxy;
using forensics::llm::SingleConversionStatus;

TEST(MarkitdownProxyConvertOne, MapsConvertedResponse) {
    LocalServer server([](httplib::Server& app) {
        app.Post("/api/markitdown/convert-one",
            [](const httplib::Request& req, httplib::Response& res) {
                const auto body = nlohmann::json::parse(req.body);
                EXPECT_EQ(body["input_root"], "/in");
                EXPECT_EQ(body["input_file"], "/in/a.txt");
                EXPECT_EQ(body["output_root"], "/out");
                res.set_content(nlohmann::json({
                    {"success", true}, {"status", "converted"},
                    {"input_path", "/in/a.txt"},
                    {"output_path", "/out/a.txt.md"},
                    {"output_size", 17}, {"error", ""}
                }).dump(), "application/json");
            });
    });
    MarkitdownProxy proxy(server.url());
    const auto result = proxy.convertOneToMarkdown("/in", "/in/a.txt", "/out");
    EXPECT_EQ(result.status, SingleConversionStatus::Converted);
    EXPECT_EQ(result.output_path, "/out/a.txt.md");
    EXPECT_EQ(result.output_bytes, 17U);
}

TEST(MarkitdownProxyConvertOne, MapsPerFileAndServiceFailures) {
    LocalServer server([](httplib::Server& app) {
        app.Post("/api/markitdown/convert-one",
            [](const httplib::Request& req, httplib::Response& res) {
                if (req.body.find("skip.bin") != std::string::npos) {
                    res.set_content(R"({"success":false,"status":"skipped","input_path":"/in/skip.bin","output_path":"","output_size":0,"error":""})", "application/json");
                } else if (req.body.find("bad.evtx") != std::string::npos) {
                    res.status = 400;
                    res.set_content(R"({"detail":"unsafe path"})", "application/json");
                } else {
                    res.status = 500;
                    res.set_content(R"({"detail":"disk full"})", "application/json");
                }
            });
    });
    MarkitdownProxy proxy(server.url());
    EXPECT_EQ(proxy.convertOneToMarkdown("/in", "/in/skip.bin", "/out").status,
              SingleConversionStatus::Skipped);

    const auto clientFailure = proxy.convertOneToMarkdown("/in", "/in/bad.evtx", "/out");
    EXPECT_EQ(clientFailure.status, SingleConversionStatus::Failed);
    EXPECT_NE(clientFailure.error.find("HTTP 400"), std::string::npos);
    EXPECT_NE(clientFailure.error.find("unsafe path"), std::string::npos);

    EXPECT_EQ(proxy.convertOneToMarkdown("/in", "/in/write.txt", "/out").status,
              SingleConversionStatus::ServiceError);
}

TEST(MarkitdownProxyConvertOne, MapsFailedAndMalformedResponses) {
    LocalServer server([](httplib::Server& app) {
        app.Post("/api/markitdown/convert-one",
            [](const httplib::Request& req, httplib::Response& res) {
                if (req.body.find("failed.txt") != std::string::npos) {
                    res.set_content(R"({"success":false,"status":"failed","error":"extractor failed"})", "application/json");
                } else {
                    res.set_content("not valid json", "application/json");
                }
            });
    });
    MarkitdownProxy proxy(server.url());

    const auto failed = proxy.convertOneToMarkdown("/in", "/in/failed.txt", "/out");
    EXPECT_EQ(failed.status, SingleConversionStatus::Failed);
    EXPECT_EQ(failed.error, "extractor failed");

    const auto malformed = proxy.convertOneToMarkdown("/in", "/in/malformed.txt", "/out");
    EXPECT_EQ(malformed.status, SingleConversionStatus::ServiceError);
    EXPECT_FALSE(malformed.error.empty());
}

TEST(MarkitdownProxyConvertOne, MapsUnreachableServiceToServiceError) {
    MarkitdownProxy proxy("http://127.0.0.1:1");

    const auto result = proxy.convertOneToMarkdown("/in", "/in/a.txt", "/out");

    EXPECT_EQ(result.status, SingleConversionStatus::ServiceError);
    EXPECT_FALSE(result.error.empty());
}

} // namespace
