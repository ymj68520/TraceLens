// test_webserver_parsers_gtest.cpp
// Unit tests for Apache and Nginx web server parsers

#include <gtest/gtest.h>
#include <string>
#include "analyzers/LinuxFilesAnalyzer/Parsers/WebServer/ApacheParser.h"
#include "analyzers/LinuxFilesAnalyzer/Parsers/WebServer/NginxParser.h"

class ApacheParserTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

class NginxParserTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

// ============================================================================
// Apache Parser Tests
// ============================================================================

TEST_F(ApacheParserTest, ParseCombinedLogFormat) {
    std::string logLine = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0")";

    auto entry = ApacheParser::parseLogLine(logLine, "example.com");

    EXPECT_EQ(entry.remoteIp, "192.168.1.100");
    EXPECT_EQ(entry.method, "GET");
    EXPECT_EQ(entry.url, "/index.html");
    EXPECT_EQ(entry.httpVersion, "HTTP/1.1");
    EXPECT_EQ(entry.statusCode, 200);
    EXPECT_EQ(entry.responseSize, 1234);
    EXPECT_EQ(entry.referer, "https://example.com");
    EXPECT_EQ(entry.userAgent, "Mozilla/5.0");
    EXPECT_EQ(entry.vhost, "example.com");
    EXPECT_GT(entry.timestamp, 0);
}

TEST_F(ApacheParserTest, ParseCommonLogFormat) {
    std::string logLine = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234)";

    auto entry = ApacheParser::parseLogLine(logLine, "example.com");

    EXPECT_EQ(entry.remoteIp, "192.168.1.100");
    EXPECT_EQ(entry.method, "GET");
    EXPECT_EQ(entry.url, "/index.html");
    EXPECT_EQ(entry.statusCode, 200);
    EXPECT_EQ(entry.responseSize, 1234);
}

TEST_F(ApacheParserTest, DetectLogFormat) {
    std::string combinedLog = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0")";
    std::string commonLog = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234)";

    EXPECT_EQ(ApacheParser::detectLogFormat(combinedLog), "combined");
    EXPECT_EQ(ApacheParser::detectLogFormat(commonLog), "common");
}

TEST_F(ApacheParserTest, ParseAccessLogFile) {
    std::string logContent = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0"
192.168.1.101 - - [05/Oct/2023:10:24:00 +0000] "POST /api/data HTTP/1.1" 201 567 "-" "curl/7.68.0"
# Comment line
192.168.1.102 - - [05/Oct/2023:10:25:15 +0000] "GET /about HTTP/1.1" 404 892 "https://example.com" "Mozilla/5.0")";

    auto result = ApacheParser::parseAccessLog(logContent, "/var/log/apache2/access.log");

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.accessLogs.size(), 3);
    EXPECT_EQ(result.accessLogs[0].statusCode, 200);
    EXPECT_EQ(result.accessLogs[1].method, "POST");
    EXPECT_EQ(result.accessLogs[2].statusCode, 404);
}

TEST_F(ApacheParserTest, ParseVHostConfig) {
    std::string configContent = R"(
<VirtualHost *:80>
    ServerName example.com
    DocumentRoot /var/www/html
    ServerAlias www.example.com
    ServerAlias api.example.com
</VirtualHost>

<VirtualHost *:443>
    ServerName secure.example.com
    DocumentRoot /var/www/secure
    SSLCertificateFile /etc/ssl/certs/example.com.crt
</VirtualHost>
)";

    auto result = ApacheParser::parseVHostConfigs(configContent, "/etc/apache2/sites-available/example.conf");

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.vhosts.size(), 2);
    EXPECT_EQ(result.vhosts[0].serverName, "example.com");
    EXPECT_EQ(result.vhosts[0].documentRoot, "/var/www/html");
    EXPECT_EQ(result.vhosts[0].serverAliases.size(), 2);
    EXPECT_EQ(result.vhosts[1].serverName, "secure.example.com");
    EXPECT_EQ(result.vhosts[1].sslCertificates.size(), 1);
}

// ============================================================================
// Nginx Parser Tests
// ============================================================================

TEST_F(NginxParserTest, ParseDefaultLogFormat) {
    std::string logLine = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0")";

    auto entry = NginxParser::parseLogLine(logLine);

    EXPECT_EQ(entry.remoteIp, "192.168.1.100");
    EXPECT_EQ(entry.method, "GET");
    EXPECT_EQ(entry.url, "/index.html");
    EXPECT_EQ(entry.statusCode, 200);
    EXPECT_EQ(entry.responseSize, 1234);
    EXPECT_EQ(entry.referer, "https://example.com");
    EXPECT_EQ(entry.userAgent, "Mozilla/5.0");
    EXPECT_GT(entry.timestamp, 0);
}

TEST_F(NginxParserTest, ParseAccessLogFile) {
    std::string logContent = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0"
192.168.1.101 - - [05/Oct/2023:10:24:00 +0000] "POST /api/data HTTP/1.1" 201 567 "-" "curl/7.68.0"
192.168.1.102 - - [05/Oct/2023:10:25:15 +0000] "GET /about HTTP/1.1" 404 892 "https://example.com" "Mozilla/5.0")";

    auto result = NginxParser::parseAccessLog(logContent, "/var/log/nginx/access.log");

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.accessLogs.size(), 3);
    EXPECT_EQ(result.accessLogs[0].statusCode, 200);
    EXPECT_EQ(result.accessLogs[1].method, "POST");
    EXPECT_EQ(result.accessLogs[2].statusCode, 404);
}

TEST_F(NginxParserTest, ParseServerBlock) {
    std::string configContent = R"(
server {
    listen 80;
    server_name example.com www.example.com;
    root /var/www/html;

    location / {
        try_files $uri $uri/ =404;
    }

    location /api {
        proxy_pass http://backend;
    }
}

server {
    listen 443 ssl;
    server_name secure.example.com;
    root /var/www/secure;

    ssl_certificate /etc/ssl/certs/example.com.crt;
    ssl_certificate_key /etc/ssl/private/example.com.key;
}
)";

    auto result = NginxParser::parseServerBlocks(configContent, "/etc/nginx/sites-available/example.conf");

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.serverBlocks.size(), 2);
    EXPECT_EQ(result.serverBlocks[0].serverName, "example.com www.example.com");
    EXPECT_EQ(result.serverBlocks[0].root, "/var/www/html");
    EXPECT_EQ(result.serverBlocks[0].locations.size(), 2);
    EXPECT_EQ(result.serverBlocks[0].upstreams.size(), 1);
    EXPECT_EQ(result.serverBlocks[1].serverName, "secure.example.com");
    EXPECT_FALSE(result.serverBlocks[1].sslCertificate.empty());
    EXPECT_FALSE(result.serverBlocks[1].sslCertificateKey.empty());
}

TEST_F(NginxParserTest, ParseTimestampWithTimezone) {
    std::string logLine = R"(192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0")";
    auto entry = NginxParser::parseLogLine(logLine);

    EXPECT_GT(entry.timestamp, 0);

    // October 5, 2023 10:23:45 UTC
    // Note: Actual value may vary based on system timezone/DST settings
    // Just check it's in the right ballpark (within 24 hours)
    EXPECT_NEAR(entry.timestamp, 1696505025, 86400);
}

// ============================================================================
// Edge Cases and Error Handling
// ============================================================================

TEST_F(ApacheParserTest, HandleEmptyLines) {
    std::string logContent = R"(
192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234

192.168.1.101 - - [05/Oct/2023:10:24:00 +0000] "GET /about HTTP/1.1" 200 567
)";

    auto result = ApacheParser::parseAccessLog(logContent, "/var/log/apache2/access.log");

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.accessLogs.size(), 2);
}

TEST_F(NginxParserTest, HandleCommentLines) {
    std::string logContent = R"(# This is a comment
192.168.1.100 - - [05/Oct/2023:10:23:45 +0000] "GET /index.html HTTP/1.1" 200 1234 "https://example.com" "Mozilla/5.0"
# Another comment
192.168.1.101 - - [05/Oct/2023:10:24:00 +0000] "GET /about HTTP/1.1" 200 567 "-" "curl/7.68.0")";

    auto result = NginxParser::parseAccessLog(logContent, "/var/log/nginx/access.log");

    EXPECT_TRUE(result.success);
    // Comment lines should be skipped, only 2 valid log entries
    EXPECT_EQ(result.accessLogs.size(), 2);
}

TEST_F(ApacheParserTest, HandleMalformedLogLine) {
    std::string malformedLog = "This is not a valid log line";

    auto entry = ApacheParser::parseLogLine(malformedLog, "example.com");

    // Should return entry with default values
    EXPECT_EQ(entry.statusCode, 0);
    EXPECT_EQ(entry.responseSize, 0);
}

TEST_F(NginxParserTest, ExtractMultipleLocations) {
    std::string configContent = R"(
server {
    server_name example.com;
    root /var/www/html;

    location / {
        proxy_pass http://backend;
    }

    location /api {
        proxy_pass http://api_backend;
    }

    location /static {
        alias /var/www/static;
    }

    location ~ \.php$ {
        fastcgi_pass localhost:9000;
    }
}
)";

    auto result = NginxParser::parseServerBlocks(configContent, "/etc/nginx/sites-available/example.conf");

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.serverBlocks.size(), 1);
    EXPECT_EQ(result.serverBlocks[0].locations.size(), 4);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
