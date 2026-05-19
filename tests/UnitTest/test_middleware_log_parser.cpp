// test_middleware_log_parser.cpp
// Unit tests for MiddlewareLogParser (Phase 7: Web and Middleware Log Enhancement)

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include "Parsers/WebServer/MiddlewareLogParser.h"
#include "Parsers/TimestampNormalizer.h"

using namespace forensics::linux;

class MiddlewareLogParserTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

// ============================================================================
// Apache Error Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseApacheErrorLogBasic) {
    std::string content =
        "[Fri Oct 06 10:23:45.123456 2023] [core:error] [pid 1234] [client 192.168.1.1:12345] AH00128: File does not exist\n"
        "[Fri Oct 06 10:24:00 2023] [mpm_prefork:notice] [pid 1234] AH00163: Apache/2.4.41 configured\n";

    auto entries = MiddlewareLogParser::parseApacheErrorLog(content, "/var/log/apache2/error.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "Apache");
    EXPECT_EQ(entries[0].module, "core");
    EXPECT_EQ(entries[0].level, "error");
    EXPECT_NE(entries[0].message.find("File does not exist"), std::string::npos);
    EXPECT_EQ(entries[0].clientIp, "192.168.1.1");
    EXPECT_EQ(entries[0].filePath, "/var/log/apache2/error.log");
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].source, "Apache");
    EXPECT_EQ(entries[1].level, "notice");
    EXPECT_EQ(entries[1].module, "mpm_prefork");

    // Check provenance
    EXPECT_EQ(entries[0].provenance.parserName, "MiddlewareLogParser");
    EXPECT_EQ(entries[0].provenance.parserVersion, "1.0.0");
}

TEST_F(MiddlewareLogParserTest, ParseApacheErrorLogTimestamp) {
    std::string content =
        "[Fri Oct 06 10:23:45.123456 2023] [core:error] Test message\n";

    auto entries = MiddlewareLogParser::parseApacheErrorLog(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_GT(entries[0].timestamp, 0);
    // 2023-10-06 10:23:45 UTC
    EXPECT_NEAR(entries[0].timestamp / 1000000, 1696587825, 2);
}

TEST_F(MiddlewareLogParserTest, ParseApacheErrorLogNoClientIp) {
    std::string content =
        "[Fri Oct 06 10:23:45 2023] [mpm_prefork:notice] [pid 1234] AH00163: Apache configured\n";

    auto entries = MiddlewareLogParser::parseApacheErrorLog(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_TRUE(entries[0].clientIp.empty());
}

TEST_F(MiddlewareLogParserTest, ParseApacheErrorLogFallback) {
    std::string content = "Random unstructured error line\n";

    auto entries = MiddlewareLogParser::parseApacheErrorLog(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "Random unstructured error line");
    EXPECT_EQ(entries[0].level, "error");
}

// ============================================================================
// Nginx Error Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseNginxErrorLogBasic) {
    std::string content =
        "2023/10/06 10:23:45 [error] 1234#0: *5678 open() \"/var/www/html/favicon.ico\" failed (2: No such file or directory), client: 192.168.1.1, server: example.com\n"
        "2023/10/06 10:24:00 [warn] 1234#0: *5679 upstream server temporarily disabled\n";

    auto entries = MiddlewareLogParser::parseNginxErrorLog(content, "/var/log/nginx/error.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "Nginx");
    EXPECT_EQ(entries[0].level, "error");
    EXPECT_EQ(entries[0].pid, "1234");
    EXPECT_NE(entries[0].message.find("favicon.ico"), std::string::npos);
    EXPECT_EQ(entries[0].clientIp, "192.168.1.1");
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].level, "warn");
}

TEST_F(MiddlewareLogParserTest, ParseNginxErrorLogTimestamp) {
    std::string content = "2023/10/06 10:23:45 [error] Test message\n";

    auto entries = MiddlewareLogParser::parseNginxErrorLog(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_GT(entries[0].timestamp, 0);
    // 2023/10/06 10:23:45 UTC
    EXPECT_NEAR(entries[0].timestamp / 1000000, 1696587825, 2);
}

// ============================================================================
// PHP-FPM Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParsePhpFpmLogBasic) {
    std::string content =
        "[06-Oct-2023 10:23:45] PHP Fatal error: Uncaught Error: Call to undefined function foo() in /var/www/html/index.php:10\n"
        "[06-Oct-2023 10:24:00] PHP Warning: Division by zero in /var/www/html/calc.php:25\n";

    auto entries = MiddlewareLogParser::parsePhpFpmLog(content, "/var/log/php-fpm/error.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "PHP-FPM");
    EXPECT_EQ(entries[0].level, "Fatal error");
    EXPECT_NE(entries[0].message.find("undefined function"), std::string::npos);
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].level, "Warning");
}

TEST_F(MiddlewareLogParserTest, ParsePhpFpmLogTimestamp) {
    std::string content = "[06-Oct-2023 10:23:45] PHP Notice: Undefined variable\n";

    auto entries = MiddlewareLogParser::parsePhpFpmLog(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_GT(entries[0].timestamp, 0);
}

// ============================================================================
// Tomcat Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseTomcatLogBasic) {
    std::string content =
        "06-Oct-2023 10:23:45.123 INFO [main] org.apache.catalina.startup.Catalina.start Server startup in [1234] milliseconds\n"
        "06-Oct-2023 10:24:00.456 SEVERE [http-nio-8080-exec-1] org.apache.coyote.AbstractProcessor.process Error processing request\n";

    auto entries = MiddlewareLogParser::parseTomcatLog(content, "/var/log/tomcat/catalina.out");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "Tomcat");
    EXPECT_EQ(entries[0].level, "INFO");
    EXPECT_EQ(entries[0].thread, "main");
    EXPECT_NE(entries[0].message.find("Server startup"), std::string::npos);
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].level, "SEVERE");
    EXPECT_EQ(entries[1].thread, "http-nio-8080-exec-1");
}

// ============================================================================
// Jetty Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseJettyLogBasic) {
    std::string content =
        "2023-10-06 10:23:45.123:INFO:oejs.Server:main: Started Server\n"
        "2023-10-06 10:24:00.456:WARN:oejs.AbstractConnector:main: Accept timed out\n";

    auto entries = MiddlewareLogParser::parseJettyLog(content, "/var/log/jetty/jetty.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "Jetty");
    EXPECT_EQ(entries[0].level, "INFO");
    EXPECT_EQ(entries[0].logger, "oejs.Server");
    EXPECT_EQ(entries[0].thread, "main");
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].level, "WARN");
}

// ============================================================================
// PM2 Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParsePm2LogBasic) {
    std::string content =
        "2023-10-06T10:23:45: App started on port 3000\n"
        "my-app  | 2023-10-06T10:24:00: Error connecting to database\n";

    auto entries = MiddlewareLogParser::parsePm2Log(content, "/var/log/pm2/app.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "PM2");
    EXPECT_EQ(entries[0].level, "INFO");
    EXPECT_NE(entries[0].message.find("App started"), std::string::npos);
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].level, "ERROR");
}

// ============================================================================
// Gunicorn Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseGunicornLogBasic) {
    std::string content =
        "[2023-10-06 10:23:45 +0000] [1234] [INFO] Starting gunicorn 20.0.0\n"
        "[2023-10-06 10:24:00 +0000] [1234] [ERROR] Worker timeout\n";

    auto entries = MiddlewareLogParser::parseGunicornLog(content, "/var/log/gunicorn/access.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "Gunicorn");
    EXPECT_EQ(entries[0].level, "INFO");
    EXPECT_EQ(entries[0].pid, "1234");
    EXPECT_GT(entries[0].timestamp, 0);

    EXPECT_EQ(entries[1].level, "ERROR");
}

// ============================================================================
// uWSGI Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseUwsgiLogBasic) {
    std::string content =
        "[pid: 1234|app: 0|req: 1/1] client (GET /api/test) => generated 100 bytes in 50 msecs (HTTP/1.1 200)\n"
        "--- uWSGI error ---\n";

    auto entries = MiddlewareLogParser::parseUwsgiLog(content, "/var/log/uwsgi/app.log");

    ASSERT_EQ(entries.size(), 2);

    EXPECT_EQ(entries[0].source, "uWSGI");
    EXPECT_EQ(entries[0].pid, "1234");
    EXPECT_EQ(entries[0].level, "INFO");

    EXPECT_EQ(entries[1].level, "ERROR");
}

// ============================================================================
// ModSecurity Audit Log Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseModSecurityLogBasic) {
    std::string content =
        "--a1b2c3d4--\n"
        "GET /admin/config.php HTTP/1.1\n"
        "Host: example.com\n"
        "X-Forwarded-For: 10.0.0.1\n"
        "--a1b2c3d4-H--\n"
        "Message: Warning. detected SQL injection. [id \"942100\"] [msg \"SQL Injection Attack Detected\"]\n"
        "--a1b2c3d4--\n";

    auto entries = MiddlewareLogParser::parseModSecurityLog(content, "/var/log/modsec_audit.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].method, "GET");
    EXPECT_EQ(entries[0].uri, "/admin/config.php");
}

// ============================================================================
// Auto-detection Tests
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseErrorLogAutoApache) {
    std::string content =
        "[Fri Oct 06 10:23:45 2023] [core:error] Test Apache error\n";

    auto entries = MiddlewareLogParser::parseErrorLogAuto(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].source, "Apache");
}

TEST_F(MiddlewareLogParserTest, ParseErrorLogAutoNginx) {
    std::string content =
        "2023/10/06 10:23:45 [error] Test Nginx error\n";

    auto entries = MiddlewareLogParser::parseErrorLogAuto(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].source, "Nginx");
}

TEST_F(MiddlewareLogParserTest, ParseErrorLogAutoEmpty) {
    auto entries = MiddlewareLogParser::parseErrorLogAuto("", "test.log");
    EXPECT_TRUE(entries.empty());
}

// ============================================================================
// Edge Cases
// ============================================================================

TEST_F(MiddlewareLogParserTest, ParseEmptyContent) {
    EXPECT_TRUE(MiddlewareLogParser::parseApacheErrorLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseNginxErrorLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parsePhpFpmLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseTomcatLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseJettyLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parsePm2Log("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseGunicornLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseUwsgiLog("", "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseModSecurityLog("", "test.log").empty());
}

TEST_F(MiddlewareLogParserTest, ParseBlankLines) {
    std::string content = "\n\n\n";
    EXPECT_TRUE(MiddlewareLogParser::parseApacheErrorLog(content, "test.log").empty());
    EXPECT_TRUE(MiddlewareLogParser::parseNginxErrorLog(content, "test.log").empty());
}

TEST_F(MiddlewareLogParserTest, ProvenancePopulated) {
    std::string content =
        "[Fri Oct 06 10:23:45 2023] [core:error] Test message\n";

    auto entries = MiddlewareLogParser::parseApacheErrorLog(content, "/test/path.log");
    ASSERT_EQ(entries.size(), 1);

    EXPECT_EQ(entries[0].provenance.parserName, "MiddlewareLogParser");
    EXPECT_EQ(entries[0].provenance.parserVersion, "1.0.0");
    EXPECT_EQ(entries[0].provenance.sourceFile, "/test/path.log");
    EXPECT_FALSE(entries[0].provenance.rawRecord.empty());
}

TEST_F(MiddlewareLogParserTest, MultipleApacheEntries) {
    std::string content;
    for (int i = 0; i < 100; i++) {
        content += "[Fri Oct 06 10:23:45 2023] [core:error] [client 192.168.1.1:12345] Error " + std::to_string(i) + "\n";
    }

    auto entries = MiddlewareLogParser::parseApacheErrorLog(content, "test.log");
    EXPECT_EQ(entries.size(), 100);
}

TEST_F(MiddlewareLogParserTest, NginxWithConnectionId) {
    std::string content =
        "2023/10/06 10:23:45 [error] 1234#0: *5678 open() \"/test\" failed, client: 10.0.0.1\n";

    auto entries = MiddlewareLogParser::parseNginxErrorLog(content, "test.log");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].pid, "1234");
    EXPECT_EQ(entries[0].clientIp, "10.0.0.1");
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
