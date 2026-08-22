#include <chrono>
#include <functional>
#include <stdexcept>
#include <string>
#include <thread>
#include <optional>

#include <gtest/gtest.h>
#include <httplib.h>
#include <nlohmann/json.hpp>

#include "LLMIntegration/MarkitdownProxy.h"

namespace {

using forensics::llm::MarkitdownProxy;
using forensics::llm::SingleConversionStatus;

auto make_mock_poster(nlohmann::json expected_body,
                      int status_code,
                      nlohmann::json response_body) {
        using PosterResult = httplib::Result;
        auto payload = response_body.dump();
    return [expected_body = std::move(expected_body),
            status_code,
            response_body = std::move(response_body)](
               const std::string&, const std::string& body,
               const std::string& content_type) mutable -> httplib::Result {
        EXPECT_EQ(content_type, "application/json");
        const auto parsed = nlohmann::json::parse(body);
        for (const auto& [key, value] : expected_body.items()) {
            EXPECT_EQ(parsed[key], value);
        }
        auto response = std::make_unique<httplib::Response>();
        response->status = status_code;
        response->set_content(response_body.dump(), "application/json");
        return httplib::Result{std::move(response), httplib::Error::Success};
    };
}

TEST(MarkitdownProxyConvertOne, MapsConvertedResponse) {
    nlohmann::json response_body = {
        {"success", true},
        {"status", "converted"},
        {"input_path", "/task/in/a.txt"},
        {"output_path", "/task/out/a.txt.md"},
        {"output_size", 17},
        {"error", ""}
    };
    MarkitdownProxy proxy("http://127.0.0.1:0",
                          make_mock_poster({{"input_root", "/task/in"},
                                            {"input_file", "/task/in/a.txt"},
                                            {"output_root", "/task/out"},
                                            {"workspace_root", "/task"}},
                                           200, std::move(response_body)));
    const auto result = proxy.convertOneToMarkdown("/task/in", "/task/in/a.txt", "/task/out");
    EXPECT_EQ(result.status, SingleConversionStatus::Converted);
    EXPECT_EQ(result.output_path, "/task/out/a.txt.md");
    EXPECT_EQ(result.output_bytes, 17U);
}

TEST(MarkitdownProxyConvertOne, MapsPerFileAndServiceFailures) {
    auto skip_poster = make_mock_poster({{"input_root", "/task/in"},
                                         {"input_file", "/task/in/skip.bin"},
                                            {"output_root", "/task/out"},
                                            {"workspace_root", "/task"}},
                                        200,
                                        {{"success", true},
                                         {"status", "skipped"},
                                         {"input_path", "/task/in/skip.bin"},
                                         {"output_path", ""},
                                         {"output_size", 0},
                                         {"error", ""}});
    MarkitdownProxy proxy("http://127.0.0.1:48080", std::move(skip_poster));
    EXPECT_EQ(proxy.convertOneToMarkdown("/task/in", "/task/in/skip.bin", "/task/out").status,
              SingleConversionStatus::Skipped);

    auto failure_poster = make_mock_poster({{"input_root", "/task/in"},
                                            {"input_file", "/task/in/bad.evtx"},
                                            {"output_root", "/task/out"},
                                            {"workspace_root", "/task"}},
                                           400,
                                           {{"detail", "unsafe path"}});
    MarkitdownProxy proxy2("http://127.0.0.1:48081", std::move(failure_poster));
    const auto clientFailure = proxy2.convertOneToMarkdown("/task/in", "/task/in/bad.evtx", "/task/out");
    EXPECT_EQ(clientFailure.status, SingleConversionStatus::Failed);
    EXPECT_NE(clientFailure.error.find("HTTP 400"), std::string::npos);
    EXPECT_NE(clientFailure.error.find("unsafe path"), std::string::npos);

    auto server_error_poster = make_mock_poster({{"input_root", "/task/in"},
                                                 {"input_file", "/task/in/write.txt"},
                                                 {"output_root", "/task/out"},
                                            {"workspace_root", "/task"}},
                                                500,
                                                {{"detail", "disk full"}});
    MarkitdownProxy proxy3("http://127.0.0.1:48082", std::move(server_error_poster));
    EXPECT_EQ(proxy3.convertOneToMarkdown("/task/in", "/task/in/write.txt", "/task/out").status,
              SingleConversionStatus::ServiceError);
}

TEST(MarkitdownProxyConvertOne, MapsFailedAndMalformedResponses) {
    auto failed_poster = make_mock_poster({{"input_root", "/task/in"},
                                           {"input_file", "/task/in/failed.txt"},
                                              {"output_root", "/task/out"},
                                            {"workspace_root", "/task"}},
                                          200,
                                          {{"success", false},
                                           {"status", "failed"},
                                           {"error", "extractor failed"}});
    MarkitdownProxy proxy("http://127.0.0.1:48080", std::move(failed_poster));
    const auto failed = proxy.convertOneToMarkdown("/task/in", "/task/in/failed.txt", "/task/out");
    EXPECT_EQ(failed.status, SingleConversionStatus::Failed);
    EXPECT_EQ(failed.error, "extractor failed");

    auto malformed_poster = [](const std::string&, const std::string&, const std::string&) -> httplib::Result {
        auto response = std::make_unique<httplib::Response>();
        response->status = 200;
        response->set_content("not valid json", "application/json");
        return httplib::Result{std::move(response), httplib::Error::Success};
    };
    MarkitdownProxy proxy2("http://127.0.0.1:48081", std::move(malformed_poster));
    const auto malformed = proxy2.convertOneToMarkdown("/task/in", "/task/in/malformed.txt", "/task/out");
    EXPECT_EQ(malformed.status, SingleConversionStatus::ServiceError);
    EXPECT_FALSE(malformed.error.empty());
}

TEST(MarkitdownProxyConvertOne, MapsUnreachableServiceToServiceError) {
    MarkitdownProxy proxy("http://127.0.0.1:0");
    const auto result = proxy.convertOneToMarkdown("/task/in", "/task/in/a.txt", "/task/out");
    EXPECT_EQ(result.status, SingleConversionStatus::ServiceError);
    EXPECT_FALSE(result.error.empty());
}

} // namespace
