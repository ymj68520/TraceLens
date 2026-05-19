// CloudParser.h
// Cloud provider agent log parsing (cloud-init, waagent, amazon-ssm-agent, google-guest-agent)

#pragma once
#ifndef CLOUD_PARSER_H
#define CLOUD_PARSER_H

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

enum class CloudProvider {
    UNKNOWN,
    AWS,
    AZURE,
    GCP,
    GENERIC
};

struct CloudEvent {
    int64_t timestamp = 0;
    CloudProvider provider = CloudProvider::UNKNOWN;
    std::string agentName;          // cloud-init, waagent, amazon-ssm-agent, google-guest-agent
    std::string eventType;          // BOOT, CONFIG, NETWORK, USER_DATA, PROVISION, EXTENSION
    std::string level;              // INFO, WARNING, ERROR, CRITICAL
    std::string module;
    std::string message;
    std::string instanceId;
    std::string region;
    std::string availabilityZone;
    EvidenceProvenance provenance;
    NormalizedTimestamp normalizedTime;
};

class CloudParser {
public:
    // Parse cloud-init logs
    static std::vector<CloudEvent> parseCloudInitLog(
        const std::string& content,
        const std::string& filePath);

    // Parse Azure waagent logs
    static std::vector<CloudEvent> parseWaagentLog(
        const std::string& content,
        const std::string& filePath);

    // Parse AWS amazon-ssm-agent logs
    static std::vector<CloudEvent> parseSSMAgentLog(
        const std::string& content,
        const std::string& filePath);

    // Parse GCP google-guest-agent logs
    static std::vector<CloudEvent> parseGuestAgentLog(
        const std::string& content,
        const std::string& filePath);

    // Auto-detect cloud provider from metadata or agent files
    static CloudProvider detectProvider(
        const std::vector<std::string>& fileList);

    // Parse generic log with cloud context
    static std::vector<CloudEvent> parseGenericCloudLog(
        const std::string& content,
        const std::string& filePath,
        CloudProvider provider);

private:
    static CloudEvent parseCloudInitLine(const std::string& line,
                                          const std::string& filePath);
    static CloudEvent parseWaagentLine(const std::string& line,
                                        const std::string& filePath);
    static CloudEvent parseSSMAgentLine(const std::string& line,
                                         const std::string& filePath);
    static CloudEvent parseGuestAgentLine(const std::string& line,
                                           const std::string& filePath);
};

} // namespace linux
} // namespace forensics

#endif // CLOUD_PARSER_H
