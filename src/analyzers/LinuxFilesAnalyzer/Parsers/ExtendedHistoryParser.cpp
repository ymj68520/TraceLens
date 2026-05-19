// ExtendedHistoryParser.cpp
// Extended shell/development tool history parsing

#include "ExtendedHistoryParser.h"
#include "TimestampNormalizer.h"
#include <sstream>
#include <regex>
#include <algorithm>

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// ============================================================================
// Simple line-based history parsing (Python, MySQL, PSQL, Redis, SQLite)
// ============================================================================

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parseSimpleLineHistory(
    const std::string& content,
    const std::string& filePath,
    const std::string& username,
    const std::string& toolType) {

    std::vector<ExtendedHistoryEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;

        ExtendedHistoryEntry entry;
        entry.provenance.parserName = "ExtendedHistoryParser";
        entry.provenance.parserVersion = "1.0";
        entry.provenance.sourceFile = filePath;
        entry.provenance.sourceLine = lineNum;
        entry.toolType = toolType;
        entry.username = username;
        entry.command = line;
        entry.sourceFile = filePath;
        entry.provenance.rawRecord = line;

        entry.isSensitive = containsSensitiveContent(entry.command, entry.sensitiveReason);
        entries.push_back(std::move(entry));
    }
    return entries;
}

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parsePythonHistory(
    const std::string& content, const std::string& filePath, const std::string& username) {
    return parseSimpleLineHistory(content, filePath, username, "python");
}

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parseMysqlHistory(
    const std::string& content, const std::string& filePath, const std::string& username) {
    return parseSimpleLineHistory(content, filePath, username, "mysql");
}

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parsePsqlHistory(
    const std::string& content, const std::string& filePath, const std::string& username) {
    return parseSimpleLineHistory(content, filePath, username, "psql");
}

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parseRedisHistory(
    const std::string& content, const std::string& filePath, const std::string& username) {
    return parseSimpleLineHistory(content, filePath, username, "redis");
}

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parseSqliteHistory(
    const std::string& content, const std::string& filePath, const std::string& username) {
    return parseSimpleLineHistory(content, filePath, username, "sqlite");
}

// ============================================================================
// Git reflog parsing
// Format: "old_hash new_hash author_name <email> timestamp +0800\tmessage"
// ============================================================================

std::vector<ExtendedHistoryEntry> ExtendedHistoryParser::parseGitReflog(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<ExtendedHistoryEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        ExtendedHistoryEntry entry;
        entry.provenance.parserName = "ExtendedHistoryParser";
        entry.provenance.parserVersion = "1.0";
        entry.provenance.sourceFile = filePath;
        entry.toolType = "git";
        entry.username = username;
        entry.sourceFile = filePath;

        // Parse: "old new author <email> timestamp tz\tmessage"
        std::regex reflogRegex(R"(\w+ (\w+) .+ <[^>]+> (\d+) [+-]\d{4}\t(.*))");
        std::smatch match;

        if (std::regex_search(line, match, reflogRegex)) {
            // match[1] = new hash, match[2] = epoch timestamp, match[3] = message
            try {
                entry.timestamp = std::stoll(match[2].str());
            } catch (...) {
                entry.timestamp = 0;
            }
            entry.command = match[3].str();
        } else {
            entry.command = line;
        }

        entry.provenance.rawRecord = line;
        entries.push_back(std::move(entry));
    }
    return entries;
}

// ============================================================================
// Credential config parsing
// ============================================================================

std::vector<CredentialConfig> ExtendedHistoryParser::parseGitConfig(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<CredentialConfig> configs;
    CredentialConfig config;
    config.configType = "git_config";
    config.filePath = filePath;
    config.username = username;
    config.provenance.parserName = "ExtendedHistoryParser";
    config.provenance.sourceFile = filePath;

    // Check for credential helpers and tokens
    if (content.find("credential") != std::string::npos) {
        config.hasTokens = true;
    }
    if (content.find("token") != std::string::npos ||
        content.find("password") != std::string::npos) {
        config.hasCredentials = true;
    }

    configs.push_back(std::move(config));
    return configs;
}

std::vector<CredentialConfig> ExtendedHistoryParser::parseDockerConfig(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<CredentialConfig> configs;
    CredentialConfig config;
    config.configType = "docker_config";
    config.filePath = filePath;
    config.username = username;
    config.provenance.parserName = "ExtendedHistoryParser";
    config.provenance.sourceFile = filePath;

    // Docker config.json contains auth tokens (base64 encoded)
    if (content.find("\"auth\"") != std::string::npos) {
        config.hasCredentials = true;
    }
    if (content.find("identitytoken") != std::string::npos) {
        config.hasTokens = true;
    }

    configs.push_back(std::move(config));
    return configs;
}

std::vector<CredentialConfig> ExtendedHistoryParser::parseKubeConfig(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<CredentialConfig> configs;
    CredentialConfig config;
    config.configType = "kube_config";
    config.filePath = filePath;
    config.username = username;
    config.provenance.parserName = "ExtendedHistoryParser";
    config.provenance.sourceFile = filePath;

    if (content.find("client-key-data") != std::string::npos ||
        content.find("client-certificate-data") != std::string::npos) {
        config.hasCredentials = true;
    }
    if (content.find("token") != std::string::npos) {
        config.hasTokens = true;
    }

    configs.push_back(std::move(config));
    return configs;
}

std::vector<CredentialConfig> ExtendedHistoryParser::parseAWSCredentials(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<CredentialConfig> configs;
    CredentialConfig config;
    config.configType = "aws_credentials";
    config.filePath = filePath;
    config.username = username;
    config.provenance.parserName = "ExtendedHistoryParser";
    config.provenance.sourceFile = filePath;

    if (content.find("aws_access_key_id") != std::string::npos ||
        content.find("aws_secret_access_key") != std::string::npos) {
        config.hasCredentials = true;
    }
    if (content.find("aws_session_token") != std::string::npos) {
        config.hasTokens = true;
    }

    // Extract profile name
    std::regex profileRegex(R"(\[([^\]]+)\])");
    std::smatch match;
    if (std::regex_search(content, match, profileRegex)) {
        config.profile = match[1].str();
    }

    configs.push_back(std::move(config));
    return configs;
}

std::vector<CredentialConfig> ExtendedHistoryParser::parseGCloudConfig(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<CredentialConfig> configs;
    CredentialConfig config;
    config.configType = "gcloud_config";
    config.filePath = filePath;
    config.username = username;
    config.provenance.parserName = "ExtendedHistoryParser";
    config.provenance.sourceFile = filePath;

    if (content.find("access_token") != std::string::npos ||
        content.find("refresh_token") != std::string::npos) {
        config.hasTokens = true;
        config.hasCredentials = true;
    }

    configs.push_back(std::move(config));
    return configs;
}

std::vector<CredentialConfig> ExtendedHistoryParser::parseAzureProfile(
    const std::string& content,
    const std::string& filePath,
    const std::string& username) {

    std::vector<CredentialConfig> configs;
    CredentialConfig config;
    config.configType = "azure_profile";
    config.filePath = filePath;
    config.username = username;
    config.provenance.parserName = "ExtendedHistoryParser";
    config.provenance.sourceFile = filePath;

    if (content.find("accessToken") != std::string::npos ||
        content.find("refreshToken") != std::string::npos) {
        config.hasTokens = true;
        config.hasCredentials = true;
    }

    configs.push_back(std::move(config));
    return configs;
}

// ============================================================================
// Sensitive content detection
// ============================================================================

bool ExtendedHistoryParser::containsSensitiveContent(const std::string& command,
                                                      std::string& reason) {
    // Password patterns
    if (command.find("password") != std::string::npos ||
        command.find("passwd") != std::string::npos ||
        command.find("-p ") != std::string::npos ||
        command.find("--password") != std::string::npos) {
        reason = "Contains password reference";
        return true;
    }
    // Token/key patterns
    if (command.find("token") != std::string::npos ||
        command.find("api_key") != std::string::npos ||
        command.find("apikey") != std::string::npos ||
        command.find("secret") != std::string::npos ||
        command.find("AWS_ACCESS_KEY") != std::string::npos ||
        command.find("AWS_SECRET") != std::string::npos) {
        reason = "Contains credential/token reference";
        return true;
    }
    // Connection strings with credentials
    if (command.find("mysql://") != std::string::npos ||
        command.find("postgres://") != std::string::npos ||
        command.find("mongodb://") != std::string::npos ||
        command.find("redis://") != std::string::npos) {
        reason = "Contains database connection string";
        return true;
    }
    // SSH operations
    if (command.find("ssh-keygen") != std::string::npos ||
        command.find("ssh-copy-id") != std::string::npos ||
        command.find("scp ") != std::string::npos) {
        reason = "SSH key/credential operation";
        return true;
    }
    return false;
}

void ExtendedHistoryParser::flagSensitive(std::vector<ExtendedHistoryEntry>& entries) {
    for (auto& entry : entries) {
        entry.isSensitive = containsSensitiveContent(entry.command, entry.sensitiveReason);
    }
}

} // namespace linux
} // namespace forensics
