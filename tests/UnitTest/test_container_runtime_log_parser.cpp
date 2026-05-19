// test_container_runtime_log_parser.cpp
// Unit tests for ContainerRuntimeLogParser - Phase 8

#include <gtest/gtest.h>
#include "Parsers/Container/ContainerRuntimeLogParser.h"

using namespace forensics::linux;

class ContainerRuntimeLogParserTest : public ::testing::Test {
protected:
    ContainerRuntimeLogParser parser;
};

// ============================================================================
// Docker json-file Log Parsing Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogBasic) {
    std::string content = R"({"log":"Hello from Docker!\n","stream":"stdout","time":"2023-10-06T10:23:45.123456789Z"})";
    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc123/abc123-json.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "Hello from Docker!");
    EXPECT_EQ(entries[0].stream, "stdout");
    EXPECT_EQ(entries[0].containerId, "abc123");
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogMultipleLines) {
    std::string content =
        R"({"log":"Line 1\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})" "\n"
        R"({"log":"Line 2\n","stream":"stderr","time":"2023-10-06T10:23:46.000000000Z"})" "\n"
        R"({"log":"Line 3\n","stream":"stdout","time":"2023-10-06T10:23:47.000000000Z"})";

    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/test123/test123-json.log");

    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].message, "Line 1");
    EXPECT_EQ(entries[0].stream, "stdout");
    EXPECT_EQ(entries[1].message, "Line 2");
    EXPECT_EQ(entries[1].stream, "stderr");
    EXPECT_EQ(entries[2].message, "Line 3");
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogTimestamp) {
    std::string content = R"({"log":"test\n","stream":"stdout","time":"2023-10-06T10:23:45.123456789Z"})";
    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc/abc-json.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_GT(entries[0].timestamp, 0);
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogEmptyLine) {
    std::string content = R"({"log":"test\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})" "\n\n"
                          R"({"log":"test2\n","stream":"stdout","time":"2023-10-06T10:23:46.000000000Z"})";

    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc/abc-json.log");

    ASSERT_EQ(entries.size(), 2);
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogContainerIdExtraction) {
    std::string content = R"({"log":"msg\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})";

    // Test different path formats
    auto entries1 = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abcdef123456/abcdef123456-json.log");
    ASSERT_EQ(entries1.size(), 1);
    EXPECT_EQ(entries1[0].containerId, "abcdef123456");

    // Short container ID
    auto entries2 = parser.parseDockerJsonLog(content, "/containers/abc/abc-json.log");
    ASSERT_EQ(entries2.size(), 1);
    EXPECT_EQ(entries2[0].containerId, "abc");
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogTrailingNewline) {
    std::string content = R"({"log":"Hello World\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})";
    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc/abc-json.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "Hello World");  // trailing \n stripped
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogInvalidJson) {
    std::string content = "this is not json\n";
    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc/abc-json.log");

    // Should skip invalid lines (no "log" field found, message stays empty)
    EXPECT_EQ(entries.size(), 0);
}

// ============================================================================
// CRI Log Parsing Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogBasic) {
    std::string content = "2023-10-06T10:23:45.123456789Z stdout F Hello from container\n";
    auto entries = parser.parseCRILog(content, "/var/log/pods/default_my-pod_abc123/container/0.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].stream, "stdout");
    EXPECT_EQ(entries[0].message, "Hello from container");
    EXPECT_EQ(entries[0].podName, "my-pod");
    EXPECT_EQ(entries[0].namespace_, "default");
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogMultipleLines) {
    std::string content =
        "2023-10-06T10:23:45.000000000Z stdout F Line 1\n"
        "2023-10-06T10:23:46.000000000Z stderr F Error line\n"
        "2023-10-06T10:23:47.000000000Z stdout P Partial line\n";

    auto entries = parser.parseCRILog(content, "/var/log/pods/ns_pod_abc/container/0.log");

    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].stream, "stdout");
    EXPECT_EQ(entries[0].message, "Line 1");
    EXPECT_EQ(entries[1].stream, "stderr");
    EXPECT_EQ(entries[1].message, "Error line");
    EXPECT_EQ(entries[2].stream, "stdout");
    EXPECT_EQ(entries[2].message, "Partial line");
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogTimestamp) {
    std::string content = "2023-10-06T10:23:45.123456789Z stdout F Test message\n";
    auto entries = parser.parseCRILog(content, "/var/log/pods/default_pod_abc/container/0.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_GT(entries[0].timestamp, 0);
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogPodMetadataExtraction) {
    std::string content = "2023-10-06T10:23:45.000000000Z stdout F Test\n";

    // Test metadata extraction from path: /var/log/pods/<namespace>_<podName>_<uid>/<containerName>/<file>.log
    auto entries = parser.parseCRILog(content, "/var/log/pods/my-namespace_my-pod-name_abc123def/my-container/0.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].podName, "my-pod-name");
    EXPECT_EQ(entries[0].namespace_, "my-namespace");
    EXPECT_EQ(entries[0].containerName, "my-container");
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogEmptyLine) {
    std::string content =
        "2023-10-06T10:23:45.000000000Z stdout F Line 1\n"
        "\n"
        "2023-10-06T10:23:47.000000000Z stdout F Line 2\n";

    auto entries = parser.parseCRILog(content, "/var/log/pods/default_pod_abc/container/0.log");

    ASSERT_EQ(entries.size(), 2);
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogFallbackParsing) {
    // Lines that don't match CRI format are treated as plain messages (fallback)
    std::string content =
        "2023-10-06T10:23:45.000000000Z stdout F Good line\n"
        "This is a plain log line without CRI format\n"
        "2023-10-06T10:23:46.000000000Z stderr F Another good line\n";

    auto entries = parser.parseCRILog(content, "/var/log/pods/default_pod_abc/container/0.log");

    // All 3 lines produce entries (fallback for non-CRI lines)
    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].message, "Good line");
    EXPECT_EQ(entries[1].message, "This is a plain log line without CRI format");
    EXPECT_EQ(entries[2].message, "Another good line");
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogPartialFlag) {
    std::string content = "2023-10-06T10:23:45.000000000Z stdout P Partial message\n";
    auto entries = parser.parseCRILog(content, "/var/log/pods/default_pod_abc/container/0.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].stream, "stdout");
    EXPECT_EQ(entries[0].message, "Partial message");
}

// ============================================================================
// Kubernetes Pod Log Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, ParseK8sPodLogBasic) {
    std::string content = "2023-10-06T10:23:45.000000000Z stdout F Pod log message\n";
    auto entries = parser.parseKubernetesPodLog(content, "/var/log/pods/default_my-pod_abc123/my-container/0.log");

    ASSERT_GE(entries.size(), 1);
}

// ============================================================================
// Security Analysis Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityPrivileged) {
    ContainerConfig config;
    config.privileged = true;
    config.containerName = "test-container";
    config.containerId = "abc123";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "privileged") {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityHostPID) {
    ContainerConfig config;
    config.hostPID = true;
    config.containerName = "test-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "hostPID") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityHostNetwork) {
    ContainerConfig config;
    config.hostNetwork = true;
    config.containerName = "test-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "hostNetwork") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityHostIPC) {
    ContainerConfig config;
    config.hostIPC = true;
    config.containerName = "test-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "hostIPC") {
            found = true;
            EXPECT_EQ(f.severity, "medium");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityDockerSocket) {
    ContainerConfig config;
    config.dockerSocketMounted = true;
    config.dockerSocketPath = "/var/run/docker.sock";
    config.containerName = "test-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "dockerSocket") {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityHostPath) {
    ContainerConfig config;
    config.hostPaths.push_back("/");
    config.hostPaths.push_back("/etc");
    config.containerName = "test-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    int hostPathCount = 0;
    for (const auto& f : findings) {
        if (f.findingType == "hostPath") {
            hostPathCount++;
        }
    }
    EXPECT_GE(hostPathCount, 2);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityNoIssues) {
    ContainerConfig config;
    config.privileged = false;
    config.hostPID = false;
    config.hostNetwork = false;
    config.hostIPC = false;
    config.containerName = "safe-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    // Should have no critical findings
    for (const auto& f : findings) {
        EXPECT_NE(f.severity, "critical");
    }
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityMultipleIssues) {
    ContainerConfig config;
    config.privileged = true;
    config.hostPID = true;
    config.hostNetwork = true;
    config.hostIPC = true;
    config.dockerSocketMounted = true;
    config.hostPaths.push_back("/");
    config.containerName = "dangerous-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    // Should have multiple findings
    EXPECT_GE(findings.size(), 5);
}

// ============================================================================
// Runtime Detection Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, DetectRuntimeTypeDocker) {
    std::string dockerLog = R"({"log":"test\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})";
    EXPECT_EQ(parser.detectRuntimeType(dockerLog), "docker");
}

TEST_F(ContainerRuntimeLogParserTest, DetectRuntimeTypeCRI) {
    std::string criLog = "2023-10-06T10:23:45.000000000Z stdout F Test message\n";
    EXPECT_EQ(parser.detectRuntimeType(criLog), "cri");
}

TEST_F(ContainerRuntimeLogParserTest, DetectRuntimeTypeUnknown) {
    std::string unknownLog = "just some random text\n";
    EXPECT_EQ(parser.detectRuntimeType(unknownLog), "unknown");
}

// ============================================================================
// Provenance Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, DockerLogProvenance) {
    std::string content = R"({"log":"test\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})";
    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc/abc-json.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_FALSE(entries[0].provenance.parserName.empty());
    EXPECT_FALSE(entries[0].provenance.sourceFile.empty());
}

TEST_F(ContainerRuntimeLogParserTest, CRILogProvenance) {
    std::string content = "2023-10-06T10:23:45.000000000Z stdout F Test\n";
    auto entries = parser.parseCRILog(content, "/var/log/pods/default_pod_abc/container/0.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_FALSE(entries[0].provenance.parserName.empty());
    EXPECT_FALSE(entries[0].provenance.sourceFile.empty());
}

TEST_F(ContainerRuntimeLogParserTest, SecurityFindingProvenance) {
    ContainerConfig config;
    config.privileged = true;
    config.containerName = "test-container";
    config.provenance.parserName = "TestParser";
    config.provenance.sourceFile = "/test/config.json";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    ASSERT_GE(findings.size(), 1);
    EXPECT_FALSE(findings[0].provenance.parserName.empty());
}

// ============================================================================
// Edge Case Tests
// ============================================================================

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogEmptyContent) {
    auto entries = parser.parseDockerJsonLog("", "/var/lib/docker/containers/abc/abc-json.log");
    EXPECT_EQ(entries.size(), 0);
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogEmptyContent) {
    auto entries = parser.parseCRILog("", "/var/log/pods/default_pod_abc/container/0.log");
    EXPECT_EQ(entries.size(), 0);
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogWhitespaceOnly) {
    auto entries = parser.parseDockerJsonLog("   \n  \n  ", "/var/lib/docker/containers/abc/abc-json.log");
    EXPECT_EQ(entries.size(), 0);
}

TEST_F(ContainerRuntimeLogParserTest, ParseCRILogWhitespaceOnly) {
    auto entries = parser.parseCRILog("   \n  \n  ", "/var/log/pods/default_pod_abc/container/0.log");
    EXPECT_EQ(entries.size(), 0);
}

TEST_F(ContainerRuntimeLogParserTest, ParseDockerJsonLogLargeEntry) {
    std::string longMessage(10000, 'A');
    std::string content = R"({"log":")" + longMessage + R"(\n","stream":"stdout","time":"2023-10-06T10:23:45.000000000Z"})";
    auto entries = parser.parseDockerJsonLog(content, "/var/lib/docker/containers/abc/abc-json.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message.size(), 10000);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityEmptyConfig) {
    ContainerConfig config;
    config.containerName = "empty-container";

    std::vector<ContainerConfig> configs = {config};
    auto findings = parser.analyzeContainerSecurity(configs);

    // Should not crash, may have no findings
    EXPECT_GE(findings.size(), 0);
}

TEST_F(ContainerRuntimeLogParserTest, AnalyzeContainerSecurityMultipleContainers) {
    ContainerConfig config1;
    config1.privileged = true;
    config1.containerName = "container1";

    ContainerConfig config2;
    config2.hostPID = true;
    config2.containerName = "container2";

    std::vector<ContainerConfig> configs = {config1, config2};
    auto findings = parser.analyzeContainerSecurity(configs);

    // Should have findings from both containers
    EXPECT_GE(findings.size(), 2);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
