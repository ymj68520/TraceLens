// CloudParser.cpp
// Cloud provider agent log parsing

#include "CloudParser.h"
#include "TimestampNormalizer.h"
#include <sstream>
#include <regex>

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// ============================================================================
// cloud-init log parsing
// Format: "2024-01-15 10:30:00,123 - module_name.py[INFO]: message"
// ============================================================================

std::vector<CloudEvent> CloudParser::parseCloudInitLog(
    const std::string& content,
    const std::string& filePath) {

    std::vector<CloudEvent> events;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto event = parseCloudInitLine(line, filePath);
        if (!event.message.empty()) {
            events.push_back(std::move(event));
        }
    }
    return events;
}

CloudEvent CloudParser::parseCloudInitLine(const std::string& line,
                                            const std::string& filePath) {
    CloudEvent event;
    event.provenance.parserName = "CloudParser";
    event.provenance.parserVersion = "1.0";
    event.provenance.sourceFile = filePath;
    event.provider = CloudProvider::GENERIC;
    event.agentName = "cloud-init";

    // Format: "2024-01-15 10:30:00,123 - module.py[LEVEL]: message"
    std::regex ciRegex(R"((\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}),\d+\s+-\s+(\S+)\[(\w+)\]:\s*(.*))");
    std::smatch match;

    if (std::regex_search(line, match, ciRegex)) {
        event.normalizedTime = TimestampNormalizer::normalizeISO8601(match[1].str());
        event.timestamp = event.normalizedTime.normalizedUtcTimestamp;
        event.module = match[2].str();
        event.level = match[3].str();
        event.message = match[4].str();
    } else {
        event.message = line;
    }

    // Classify event type
    if (event.module.find("user") != std::string::npos) {
        event.eventType = "USER_DATA";
    } else if (event.module.find("network") != std::string::npos) {
        event.eventType = "NETWORK";
    } else if (event.module.find("config") != std::string::npos) {
        event.eventType = "CONFIG";
    } else {
        event.eventType = "BOOT";
    }

    event.provenance.rawRecord = line;
    return event;
}

// ============================================================================
// Azure waagent log parsing
// Format: "2024/01/15 10:30:00.123456 [INFO] message"
// ============================================================================

std::vector<CloudEvent> CloudParser::parseWaagentLog(
    const std::string& content,
    const std::string& filePath) {

    std::vector<CloudEvent> events;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto event = parseWaagentLine(line, filePath);
        if (!event.message.empty()) {
            events.push_back(std::move(event));
        }
    }
    return events;
}

CloudEvent CloudParser::parseWaagentLine(const std::string& line,
                                          const std::string& filePath) {
    CloudEvent event;
    event.provenance.parserName = "CloudParser";
    event.provenance.parserVersion = "1.0";
    event.provenance.sourceFile = filePath;
    event.provider = CloudProvider::AZURE;
    event.agentName = "waagent";

    // Format: "2024/01/15 10:30:00.123456 [LEVEL] message"
    std::regex waRegex(R"((\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})\.\d+\s+\[(\w+)\]\s*(.*))");
    std::smatch match;

    if (std::regex_search(line, match, waRegex)) {
        // Convert slashes to dashes for ISO8601
        std::string ts = match[1].str();
        std::replace(ts.begin(), ts.end(), '/', '-');
        event.normalizedTime = TimestampNormalizer::normalizeISO8601(ts);
        event.timestamp = event.normalizedTime.normalizedUtcTimestamp;
        event.level = match[2].str();
        event.message = match[3].str();
    } else {
        event.message = line;
    }

    // Classify event type
    if (event.message.find("Extension") != std::string::npos) {
        event.eventType = "EXTENSION";
    } else if (event.message.find("provision") != std::string::npos ||
               event.message.find("Provision") != std::string::npos) {
        event.eventType = "PROVISION";
    } else {
        event.eventType = "CONFIG";
    }

    event.provenance.rawRecord = line;
    return event;
}

// ============================================================================
// AWS amazon-ssm-agent log parsing
// Format: "2024-01-15T10:30:00Z [INFO] message"
// ============================================================================

std::vector<CloudEvent> CloudParser::parseSSMAgentLog(
    const std::string& content,
    const std::string& filePath) {

    std::vector<CloudEvent> events;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto event = parseSSMAgentLine(line, filePath);
        if (!event.message.empty()) {
            events.push_back(std::move(event));
        }
    }
    return events;
}

CloudEvent CloudParser::parseSSMAgentLine(const std::string& line,
                                           const std::string& filePath) {
    CloudEvent event;
    event.provenance.parserName = "CloudParser";
    event.provenance.parserVersion = "1.0";
    event.provenance.sourceFile = filePath;
    event.provider = CloudProvider::AWS;
    event.agentName = "amazon-ssm-agent";

    // Format: "2024-01-15T10:30:00Z message" or with level
    std::regex ssmRegex(R"((\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)\s+(\[?\w+\]?)?\s*(.*))");
    std::smatch match;

    if (std::regex_search(line, match, ssmRegex)) {
        event.normalizedTime = TimestampNormalizer::normalizeISO8601(match[1].str());
        event.timestamp = event.normalizedTime.normalizedUtcTimestamp;
        std::string levelStr = match[2].str();
        // Strip brackets
        if (!levelStr.empty() && levelStr.front() == '[') {
            levelStr = levelStr.substr(1, levelStr.size() - 2);
        }
        event.level = levelStr;
        event.message = match[3].str();
    } else {
        event.message = line;
    }

    event.eventType = "CONFIG";
    event.provenance.rawRecord = line;
    return event;
}

// ============================================================================
// GCP google-guest-agent log parsing
// ============================================================================

std::vector<CloudEvent> CloudParser::parseGuestAgentLog(
    const std::string& content,
    const std::string& filePath) {

    std::vector<CloudEvent> events;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto event = parseGuestAgentLine(line, filePath);
        if (!event.message.empty()) {
            events.push_back(std::move(event));
        }
    }
    return events;
}

CloudEvent CloudParser::parseGuestAgentLine(const std::string& line,
                                             const std::string& filePath) {
    CloudEvent event;
    event.provenance.parserName = "CloudParser";
    event.provenance.parserVersion = "1.0";
    event.provenance.sourceFile = filePath;
    event.provider = CloudProvider::GCP;
    event.agentName = "google-guest-agent";

    // Similar to syslog format
    event.message = line;
    event.eventType = "CONFIG";
    event.provenance.rawRecord = line;
    return event;
}

// ============================================================================
// Provider Detection
// ============================================================================

CloudProvider CloudParser::detectProvider(const std::vector<std::string>& fileList) {
    for (const auto& file : fileList) {
        if (file.find("waagent") != std::string::npos) return CloudProvider::AZURE;
        if (file.find("amazon-ssm") != std::string::npos) return CloudProvider::AWS;
        if (file.find("google-guest") != std::string::npos) return CloudProvider::GCP;
        if (file.find("cloud-init") != std::string::npos) return CloudProvider::GENERIC;
    }
    return CloudProvider::UNKNOWN;
}

std::vector<CloudEvent> CloudParser::parseGenericCloudLog(
    const std::string& content,
    const std::string& filePath,
    CloudProvider provider) {

    switch (provider) {
        case CloudProvider::AZURE: return parseWaagentLog(content, filePath);
        case CloudProvider::AWS: return parseSSMAgentLog(content, filePath);
        case CloudProvider::GCP: return parseGuestAgentLog(content, filePath);
        default: return parseCloudInitLog(content, filePath);
    }
}

} // namespace linux
} // namespace forensics
