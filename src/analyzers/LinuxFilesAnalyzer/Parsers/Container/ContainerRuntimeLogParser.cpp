// ContainerRuntimeLogParser.cpp
// Implementation of Docker, containerd, CRI-O, and Kubernetes runtime log parser
// Phase 8: Container Log Enhancement

#ifdef linux
#undef linux
#endif

#include "ContainerRuntimeLogParser.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <iostream>
#include <ctime>

using namespace forensics::linux;

// ============================================================================
// Docker json-file Log Parsing
// ============================================================================

std::vector<DockerLogEntry> ContainerRuntimeLogParser::parseDockerJsonLog(
    const std::string& content, const std::string& filePath) {
    std::vector<DockerLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto entry = parseDockerJsonLine(line, filePath);
        if (!entry.message.empty()) {
            entries.push_back(entry);
        }
    }
    return entries;
}

DockerLogEntry ContainerRuntimeLogParser::parseDockerJsonLine(
    const std::string& line, const std::string& filePath) {
    DockerLogEntry entry;
    entry.filePath = filePath;
    entry.provenance.parserName = "ContainerRuntimeLogParser";
    entry.provenance.parserVersion = "1.0.0";
    entry.provenance.sourceFile = filePath;
    entry.provenance.rawRecord = line;

    // Extract container ID from path: /var/lib/docker/containers/<id>/<id>-json.log
    if (!filePath.empty()) {
        // Find the container ID segment
        size_t containersPos = filePath.find("/containers/");
        if (containersPos != std::string::npos) {
            size_t idStart = containersPos + 12; // skip "/containers/"
            size_t idEnd = filePath.find('/', idStart);
            if (idEnd != std::string::npos) {
                entry.containerId = filePath.substr(idStart, idEnd - idStart);
            }
        }
    }

    // Docker json-file format: {"log":"message\n","stream":"stdout","time":"2023-10-06T10:23:45.123456Z"}
    // Simple JSON parsing without external library

    // Extract "log" field
    size_t logPos = line.find("\"log\":\"");
    if (logPos != std::string::npos) {
        logPos += 7; // skip "log":"
        size_t logEnd = logPos;
        // Find closing quote, handling escaped quotes
        while (logEnd < line.length()) {
            if (line[logEnd] == '"' && line[logEnd - 1] != '\\') break;
            logEnd++;
        }
        entry.message = line.substr(logPos, logEnd - logPos);
        // Unescape common sequences
        size_t pos;
        while ((pos = entry.message.find("\\n")) != std::string::npos) {
            entry.message.replace(pos, 2, "\n");
        }
        while ((pos = entry.message.find("\\\"")) != std::string::npos) {
            entry.message.replace(pos, 2, "\"");
        }
        while ((pos = entry.message.find("\\\\")) != std::string::npos) {
            entry.message.replace(pos, 2, "\\");
        }
        // Trim trailing newline
        while (!entry.message.empty() && entry.message.back() == '\n') {
            entry.message.pop_back();
        }
    }

    // Extract "stream" field
    size_t streamPos = line.find("\"stream\":\"");
    if (streamPos != std::string::npos) {
        streamPos += 10;
        size_t streamEnd = line.find("\"", streamPos);
        if (streamEnd != std::string::npos) {
            entry.stream = line.substr(streamPos, streamEnd - streamPos);
        }
    }

    // Extract "time" field
    size_t timePos = line.find("\"time\":\"");
    if (timePos != std::string::npos) {
        timePos += 8;
        size_t timeEnd = line.find("\"", timePos);
        if (timeEnd != std::string::npos) {
            std::string timeStr = line.substr(timePos, timeEnd - timePos);
            entry.timestamp = parseDockerTimestamp(timeStr);
        }
    }

    return entry;
}

int64_t ContainerRuntimeLogParser::parseDockerTimestamp(const std::string& timestampStr) {
    // Docker format: 2023-10-06T10:23:45.123456Z
    struct tm tm = {};
    int microseconds = 0;

    // Parse base timestamp
    std::regex tsRegex("(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2})(?:\\.(\\d+))?Z?");
    std::smatch match;
    if (std::regex_search(timestampStr, match, tsRegex)) {
        if (match[2].matched) {
            std::string usStr = match[2].str();
            // Pad or truncate to 6 digits
            if (usStr.length() > 6) usStr = usStr.substr(0, 6);
            while (usStr.length() < 6) usStr += "0";
            microseconds = std::stoi(usStr);
        }
        if (strptime(match[1].str().c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL + microseconds;
        }
    }
    return 0;
}

// ============================================================================
// CRI Log Parsing (containerd / CRI-O)
// ============================================================================

std::vector<CRILogEntry> ContainerRuntimeLogParser::parseCRILog(
    const std::string& content, const std::string& filePath) {
    std::vector<CRILogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto entry = parseCRILine(line, filePath);
        if (!entry.message.empty()) {
            entries.push_back(entry);
        }
    }
    return entries;
}

CRILogEntry ContainerRuntimeLogParser::parseCRILine(
    const std::string& line, const std::string& filePath) {
    CRILogEntry entry;
    entry.filePath = filePath;
    entry.provenance.parserName = "ContainerRuntimeLogParser";
    entry.provenance.parserVersion = "1.0.0";
    entry.provenance.sourceFile = filePath;
    entry.provenance.rawRecord = line;

    // Extract pod metadata from path: /var/log/pods/<namespace>_<podName>_<uid>/<containerName>/<file>.log
    if (!filePath.empty()) {
        size_t podsPos = filePath.find("/pods/");
        if (podsPos != std::string::npos) {
            size_t metaStart = podsPos + 6; // skip "/pods/"
            size_t metaEnd = filePath.find('/', metaStart);
            if (metaEnd != std::string::npos) {
                std::string meta = filePath.substr(metaStart, metaEnd - metaStart);
                // Format: <namespace>_<podName>_<uid>
                size_t firstUnderscore = meta.find('_');
                size_t lastUnderscore = meta.rfind('_');
                if (firstUnderscore != std::string::npos && lastUnderscore != std::string::npos &&
                    firstUnderscore != lastUnderscore) {
                    entry.namespace_ = meta.substr(0, firstUnderscore);
                    entry.podName = meta.substr(firstUnderscore + 1, lastUnderscore - firstUnderscore - 1);
                }
                // Extract container name from next path segment
                size_t containerStart = metaEnd + 1;
                size_t containerEnd = filePath.find('/', containerStart);
                if (containerEnd != std::string::npos) {
                    entry.containerName = filePath.substr(containerStart, containerEnd - containerStart);
                }
            }
        }
    }

    // CRI format: 2023-10-06T10:23:45.123456Z stdout F message
    // Or: 2023-10-06T10:23:45.123456789Z stdout F message (nanosecond precision)
    std::regex criRegex(
        "(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d+Z?)\\s+(stdout|stderr)\\s+(F|P)\\s+(.*)");
    std::smatch match;

    if (std::regex_match(line, match, criRegex)) {
        entry.timestamp = parseCRITimestamp(match[1].str());
        entry.stream = match[2].str();
        entry.flags = match[3].str();
        entry.message = match[4].str();
    } else {
        // Skip lines that are just whitespace
        bool onlyWhitespace = true;
        for (char c : line) {
            if (!std::isspace(static_cast<unsigned char>(c))) {
                onlyWhitespace = false;
                break;
            }
        }
        if (onlyWhitespace) {
            entry.message = "";
        } else {
            // Fallback: treat as plain message
            entry.message = line;
            entry.stream = "stdout";
            entry.flags = "F";
        }
    }

    return entry;
}

int64_t ContainerRuntimeLogParser::parseCRITimestamp(const std::string& timestampStr) {
    struct tm tm = {};
    int microseconds = 0;

    std::regex tsRegex("(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2})(?:\\.(\\d+))?Z?");
    std::smatch match;
    if (std::regex_search(timestampStr, match, tsRegex)) {
        if (match[2].matched) {
            std::string usStr = match[2].str();
            if (usStr.length() > 6) usStr = usStr.substr(0, 6);
            while (usStr.length() < 6) usStr += "0";
            microseconds = std::stoi(usStr);
        }
        if (strptime(match[1].str().c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
            return static_cast<int64_t>(timegm(&tm)) * 1000000LL + microseconds;
        }
    }
    return 0;
}

// ============================================================================
// Kubernetes Pod Log Parsing
// ============================================================================

std::vector<KubernetesPodLogEntry> ContainerRuntimeLogParser::parseKubernetesPodLog(
    const std::string& content, const std::string& filePath) {
    std::vector<KubernetesPodLogEntry> entries;

    // Kubernetes pod logs are typically CRI format
    // Filename convention: <podName>_<namespace>_<containerName>-<containerId>.log
    // Extract metadata from filename
    std::string podName, namespace_, containerName, containerId;

    // Try to extract from filename pattern
    std::regex filenameRegex("([^_]+)_([^_]+)_([^\\-]+)-([a-f0-9]+)\\.log");
    std::smatch match;
    std::string filename = filePath;
    // Get just the filename part
    size_t lastSlash = filename.rfind('/');
    if (lastSlash != std::string::npos) {
        filename = filename.substr(lastSlash + 1);
    }
    if (std::regex_match(filename, match, filenameRegex)) {
        podName = match[1].str();
        namespace_ = match[2].str();
        containerName = match[3].str();
        containerId = match[4].str();
    }

    // Parse as CRI logs
    auto criEntries = parseCRILog(content, filePath);

    for (const auto& criEntry : criEntries) {
        KubernetesPodLogEntry entry;
        entry.timestamp = criEntry.timestamp;
        entry.stream = criEntry.stream;
        entry.message = criEntry.message;
        entry.podName = podName;
        entry.namespace_ = namespace_;
        entry.containerName = containerName;
        entry.containerId = containerId;
        entry.filePath = filePath;
        entry.normalizedTime = criEntry.normalizedTime;
        entry.provenance = criEntry.provenance;
        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Runtime Type Detection
// ============================================================================

std::string ContainerRuntimeLogParser::detectRuntimeType(const std::string& logContent) {
    if (logContent.empty()) return "unknown";

    std::string firstLine = logContent.substr(0, logContent.find('\n'));

    // Docker json-file: starts with {"log":
    if (firstLine.find("{\"log\":") == 0 || firstLine.find("{\"log\" :") == 0) {
        return "docker";
    }

    // CRI format: timestamp stream flags message
    std::regex criPattern("\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d+Z?\\s+(stdout|stderr)\\s+(F|P)\\s+");
    if (std::regex_search(firstLine, criPattern)) {
        return "cri";
    }

    return "unknown";
}

// ============================================================================
// Container Security Analysis
// ============================================================================

ContainerConfig ContainerRuntimeLogParser::parseContainerSecurityConfig(
    const std::string& configJson, const std::string& filePath) {
    ContainerConfig config;
    config.filePath = filePath;
    config.provenance.parserName = "ContainerRuntimeLogParser";
    config.provenance.parserVersion = "1.0.0";
    config.provenance.sourceFile = filePath;

    // Check privileged
    config.privileged = isPrivileged(configJson);

    // Check host namespace sharing
    config.hostPID = hasHostPID(configJson);
    config.hostNetwork = hasHostNetwork(configJson);
    config.hostIPC = hasHostIPC(configJson);

    // Check hostPath mounts
    config.hostPaths = extractHostPaths(configJson);

    // Check Docker socket mount
    config.dockerSocketMounted = hasDockerSocketMount(configJson);
    if (config.dockerSocketMounted) {
        config.dockerSocketPath = "/var/run/docker.sock";
    }

    return config;
}

bool ContainerRuntimeLogParser::isPrivileged(const std::string& configJson) {
    // Check for "Privileged": true
    return configJson.find("\"Privileged\":true") != std::string::npos ||
           configJson.find("\"privileged\":true") != std::string::npos;
}

bool ContainerRuntimeLogParser::hasHostPID(const std::string& configJson) {
    return configJson.find("\"PidMode\":\"host\"") != std::string::npos ||
           configJson.find("\"hostPID\":true") != std::string::npos;
}

bool ContainerRuntimeLogParser::hasHostNetwork(const std::string& configJson) {
    return configJson.find("\"NetworkMode\":\"host\"") != std::string::npos ||
           configJson.find("\"hostNetwork\":true") != std::string::npos;
}

bool ContainerRuntimeLogParser::hasHostIPC(const std::string& configJson) {
    return configJson.find("\"IpcMode\":\"host\"") != std::string::npos ||
           configJson.find("\"hostIPC\":true") != std::string::npos;
}

std::vector<std::string> ContainerRuntimeLogParser::extractHostPaths(const std::string& configJson) {
    std::vector<std::string> hostPaths;

    // Look for bind mounts from host
    // Pattern: "Type":"bind" with "Source":"/..."
    std::regex bindRegex("\"Type\"\\s*:\\s*\"bind\"[^}]*\"Source\"\\s*:\\s*\"([^\"]+)\"");
    auto begin = std::sregex_iterator(configJson.begin(), configJson.end(), bindRegex);
    auto end = std::sregex_iterator();

    for (auto it = begin; it != end; ++it) {
        std::string source = (*it)[1].str();
        // Skip common non-sensitive mounts
        if (source.find("/proc") == 0 || source.find("/sys") == 0 ||
            source.find("/dev") == 0) continue;
        hostPaths.push_back(source);
    }

    return hostPaths;
}

bool ContainerRuntimeLogParser::hasDockerSocketMount(const std::string& configJson) {
    return configJson.find("/var/run/docker.sock") != std::string::npos ||
           configJson.find("/run/docker.sock") != std::string::npos;
}

int ContainerRuntimeLogParser::extractRestartCount(const std::string& metadataJson) {
    // Look for "RestartCount": N
    std::regex restartRegex("\"RestartCount\"\\s*:\\s*(\\d+)");
    std::smatch match;
    if (std::regex_search(metadataJson, match, restartRegex)) {
        try {
            return std::stoi(match[1].str());
        } catch (...) {}
    }
    return 0;
}

std::vector<ContainerSecurityFinding> ContainerRuntimeLogParser::analyzeContainerSecurity(
    const std::vector<ContainerConfig>& configs) {
    std::vector<ContainerSecurityFinding> findings;

    for (const auto& config : configs) {
        auto addFinding = [&](const std::string& type, const std::string& severity,
                             const std::string& desc, const std::string& evidence) {
            ContainerSecurityFinding finding;
            finding.findingType = type;
            finding.severity = severity;
            finding.containerId = config.containerId;
            finding.containerName = config.containerName;
            finding.podName = config.podName;
            finding.namespace_ = config.namespace_;
            finding.description = desc;
            finding.evidence = evidence;
            finding.filePath = config.filePath;
            finding.provenance = config.provenance;
            findings.push_back(finding);
        };

        if (config.privileged) {
            addFinding("privileged", "critical",
                "Container running in privileged mode - full host access",
                "\"Privileged\":true");
        }

        if (config.hostPID) {
            addFinding("hostPID", "high",
                "Container sharing host PID namespace - can see/kill host processes",
                "PID mode set to host");
        }

        if (config.hostNetwork) {
            addFinding("hostNetwork", "high",
                "Container sharing host network namespace - full network access",
                "Network mode set to host");
        }

        if (config.hostIPC) {
            addFinding("hostIPC", "medium",
                "Container sharing host IPC namespace - can access host shared memory",
                "IPC mode set to host");
        }

        if (config.dockerSocketMounted) {
            addFinding("dockerSocket", "critical",
                "Docker socket mounted in container - can escape to host",
                "Docker socket bind mount detected: " + config.dockerSocketPath);
        }

        for (const auto& hostPath : config.hostPaths) {
            // Check for sensitive host paths
            bool isSensitive = false;
            std::string reason;

            if (hostPath.find("/etc") == 0) {
                isSensitive = true;
                reason = "Access to host system configuration";
            } else if (hostPath.find("/root") == 0 || hostPath.find("/home") == 0) {
                isSensitive = true;
                reason = "Access to host user home directories";
            } else if (hostPath.find("/var/run") == 0) {
                isSensitive = true;
                reason = "Access to host runtime sockets";
            } else if (hostPath == "/") {
                isSensitive = true;
                reason = "Full host filesystem access";
            }

            if (isSensitive) {
                addFinding("hostPath", "high",
                    "Sensitive host path mounted: " + hostPath + " - " + reason,
                    "HostPath mount: " + hostPath);
            } else {
                addFinding("hostPath", "medium",
                    "Host path mounted in container: " + hostPath,
                    "HostPath mount: " + hostPath);
            }
        }
    }

    return findings;
}
