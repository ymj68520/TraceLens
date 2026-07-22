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
        {"input_path", "/in/a.txt"},
        {"output_path", "/out/a.txt.md"},
        {"output_size", 17},
        {"error", ""}
    };
    MarkitdownProxy proxy("http://127.0.0.1:0",
                          make_mock_poster({{"input_root", "/in"},
                                            {"input_file", "/in/a.txt"},
                                            {"output_root", "/out"}},
                                           200, std::move(response_body)));
    const auto result = proxy.convertOneToMarkdown("/in", "/in/a.txt", "/out");
    EXPECT_EQ(result.status, SingleConversionStatus::Converted);
    EXPECT_EQ(result.output_path, "/out/a.txt.md");
    EXPECT_EQ(result.output_bytes, 17U);
}

TEST(MarkitdownProxyConvertOne, MapsPerFileAndServiceFailures) {
    auto skip_poster = make_mock_poster({{"input_root", "/in"},
                                         {"input_file", "/in/skip.bin"},
                                         {"output_root", "/out"}},
                                        200,
                                        {{"success", true},
                                         {"status", "skipped"},
                                         {"input_path", "/in/skip.bin"},
                                         {"output_path", ""},
                                         {"output_size", 0},
                                         {"error", ""}});
    MarkitdownProxy proxy("http://127.0.0.1:48080", std::move(skip_poster));
    EXPECT_EQ(proxy.convertOneToMarkdown("/in", "/in/skip.bin", "/out").status,
              SingleConversionStatus::Skipped);

    auto failure_poster = make_mock_poster({{"input_root", "/in"},
                                            {"input_file", "/in/bad.evtx"},
                                            {"output_root", "/out"}},
                                           400,
                                           {{"detail", "unsafe path"}});
    MarkitdownProxy proxy2("http://127.0.0.1:48081", std::move(failure_poster));
    const auto clientFailure = proxy2.convertOneToMarkdown("/in", "/in/bad.evtx", "/out");
    EXPECT_EQ(clientFailure.status, SingleConversionStatus::Failed);
    EXPECT_NE(clientFailure.error.find("HTTP 400"), std::string::npos);
    EXPECT_NE(clientFailure.error.find("unsafe path"), std::string::npos);

    auto server_error_poster = make_mock_poster({{"input_root", "/in"},
                                                 {"input_file", "/in/write.txt"},
                                                 {"output_root", "/out"}},
                                                500,
                                                {{"detail", "disk full"}});
    MarkitdownProxy proxy3("http://127.0.0.1:48082", std::move(server_error_poster));
    EXPECT_EQ(proxy3.convertOneToMarkdown("/in", "/in/write.txt", "/out").status,
              SingleConversionStatus::ServiceError);
}

TEST(MarkitdownProxyConvertOne, MapsFailedAndMalformedResponses) {
    auto failed_poster = make_mock_poster({{"input_root", "/in"},
                                           {"input_file", "/in/failed.txt"},
                                           {"output_root", "/out"}},
                                          200,
                                          {{"success", false},
                                           {"status", "failed"},
                                           {"error", "extractor failed"}});
    MarkitdownProxy proxy("http://127.0.0.1:48080", std::move(failed_poster));
    const auto failed = proxy.convertOneToMarkdown("/in", "/in/failed.txt", "/out");
    EXPECT_EQ(failed.status, SingleConversionStatus::Failed);
    EXPECT_EQ(failed.error, "extractor failed");

    auto malformed_poster = [](const std::string&, const std::string&, const std::string&) -> httplib::Result {
        auto response = std::make_unique<httplib::Response>();
        response->status = 200;
        response->set_content("not valid json", "application/json");
        return httplib::Result{std::move(response), httplib::Error::Success};
    };
    MarkitdownProxy proxy2("http://127.0.0.1:48081", std::move(malformed_poster));
    const auto malformed = proxy2.convertOneToMarkdown("/in", "/in/malformed.txt", "/out");
    EXPECT_EQ(malformed.status, SingleConversionStatus::ServiceError);
    EXPECT_FALSE(malformed.error.empty());
}

TEST(MarkitdownProxyConvertOne, MapsUnreachableServiceToServiceError) {
    MarkitdownProxy proxy("http://127.0.0.1:0");
    const auto result = proxy.convertOneToMarkdown("/in", "/in/a.txt", "/out");
    EXPECT_EQ(result.status, SingleConversionStatus::ServiceError);
    EXPECT_FALSE(result.error.empty());
}

} // namespace
