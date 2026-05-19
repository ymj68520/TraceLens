// ExtendedHistoryParser.h
// Extended shell/development tool history parsing (Python, MySQL, PostgreSQL, Redis, Git, Docker, Kube, Cloud credentials)

#pragma once
#ifndef EXTENDED_HISTORY_PARSER_H
#define EXTENDED_HISTORY_PARSER_H

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

#include <string>
#include <vector>
#include <cstdint>
#include "LinuxDataTypes.h"

namespace forensics {
namespace linux {

struct ExtendedHistoryEntry {
    int64_t timestamp = 0;
    std::string toolType;       // python, mysql, psql, redis, sqlite, git, docker, kubectl, aws, gcloud, az
    std::string username;
    std::string command;
    std::string database;       // for DB CLIs
    std::string workingDir;
    std::string sourceFile;
    bool isSensitive = false;   // contains credentials, tokens, keys
    std::string sensitiveReason;
    EvidenceProvenance provenance;
    NormalizedTimestamp normalizedTime;
};

struct CredentialConfig {
    std::string configType;     // aws_credentials, gcloud_config, azure_profile, docker_config, kube_config
    std::string filePath;
    std::string username;
    std::string profile;
    bool hasCredentials = false;
    bool hasTokens = false;
    std::string lastModified;
    EvidenceProvenance provenance;
};

class ExtendedHistoryParser {
public:
    // Parse Python history (~/.python_history)
    static std::vector<ExtendedHistoryEntry> parsePythonHistory(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse MySQL history (~/.mysql_history)
    static std::vector<ExtendedHistoryEntry> parseMysqlHistory(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse PostgreSQL history (~/.psql_history)
    static std::vector<ExtendedHistoryEntry> parsePsqlHistory(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse Redis CLI history (~/.rediscli_history)
    static std::vector<ExtendedHistoryEntry> parseRedisHistory(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse SQLite history (~/.sqlite_history)
    static std::vector<ExtendedHistoryEntry> parseSqliteHistory(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse Git reflog (.git/logs/HEAD)
    static std::vector<ExtendedHistoryEntry> parseGitReflog(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse Git config (~/.gitconfig)
    static std::vector<CredentialConfig> parseGitConfig(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse Docker config (~/.docker/config.json)
    static std::vector<CredentialConfig> parseDockerConfig(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse Kubernetes config (~/.kube/config)
    static std::vector<CredentialConfig> parseKubeConfig(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Parse cloud credential configs
    static std::vector<CredentialConfig> parseAWSCredentials(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    static std::vector<CredentialConfig> parseGCloudConfig(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    static std::vector<CredentialConfig> parseAzureProfile(
        const std::string& content,
        const std::string& filePath,
        const std::string& username);

    // Flag entries with sensitive content
    static void flagSensitive(std::vector<ExtendedHistoryEntry>& entries);

private:
    static bool containsSensitiveContent(const std::string& command,
                                          std::string& reason);
    static std::vector<ExtendedHistoryEntry> parseSimpleLineHistory(
        const std::string& content,
        const std::string& filePath,
        const std::string& username,
        const std::string& toolType);
};

} // namespace linux
} // namespace forensics

#endif // EXTENDED_HISTORY_PARSER_H
