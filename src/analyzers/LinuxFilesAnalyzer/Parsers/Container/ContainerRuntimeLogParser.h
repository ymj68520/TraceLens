// ContainerRuntimeLogParser.h
// Parser for Docker, containerd, CRI-O, and Kubernetes runtime logs
// Phase 8: Container Log Enhancement

#pragma once
#ifndef CONTAINER_RUNTIME_LOG_PARSER_H
#define CONTAINER_RUNTIME_LOG_PARSER_H

#include <string>
#include <vector>
#include <map>
#include "Common/LinuxDataTypes.h"

#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Docker json-file log entry
struct DockerLogEntry {
    int64_t timestamp = 0;
    std::string stream;             // stdout, stderr
    std::string message;
    std::string containerId;
    std::string containerName;
    std::string filePath;
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// CRI (containerd/CRI-O) log entry
// Format: <timestamp> <stream> <flags> <log>
struct CRILogEntry {
    int64_t timestamp = 0;
    std::string stream;             // stdout, stderr
    std::string flags;              // F (full), P (partial)
    std::string message;
    std::string containerId;
    std::string podName;
    std::string namespace_;
    std::string containerName;
    std::string filePath;
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// Kubernetes Pod log entry
struct KubernetesPodLogEntry {
    int64_t timestamp = 0;
    std::string stream;
    std::string message;
    std::string podName;
    std::string namespace_;
    std::string containerName;
    std::string containerId;
    std::string nodeName;
    std::string filePath;
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// Container security finding
struct ContainerSecurityFinding {
    std::string findingType;        // privileged, hostPID, hostNetwork, hostPath, dockerSocket
    std::string severity;           // critical, high, medium, low
    std::string containerId;
    std::string containerName;
    std::string podName;
    std::string namespace_;
    std::string description;
    std::string evidence;
    std::string filePath;
    EvidenceProvenance provenance;
};

// Container configuration for security analysis
struct ContainerConfig {
    std::string containerId;
    std::string containerName;
    std::string podName;
    std::string namespace_;
    std::string imageName;
    bool privileged = false;
    bool hostPID = false;
    bool hostNetwork = false;
    bool hostIPC = false;
    std::vector<std::string> hostPaths;      // hostPath mounts
    bool dockerSocketMounted = false;
    std::string dockerSocketPath;
    std::string runAsUser;
    bool runAsRoot = false;
    std::vector<std::string> capabilities;
    std::string restartPolicy;
    int restartCount = 0;
    std::string filePath;
    EvidenceProvenance provenance;
};

class ContainerRuntimeLogParser {
public:
    // Docker json-file log parsing
    static std::vector<DockerLogEntry> parseDockerJsonLog(
        const std::string& content, const std::string& filePath = "");

    // CRI log parsing (containerd / CRI-O)
    static std::vector<CRILogEntry> parseCRILog(
        const std::string& content, const std::string& filePath = "");

    // Kubernetes Pod log parsing
    static std::vector<KubernetesPodLogEntry> parseKubernetesPodLog(
        const std::string& content, const std::string& filePath = "");

    // Container security analysis
    static std::vector<ContainerSecurityFinding> analyzeContainerSecurity(
        const std::vector<ContainerConfig>& configs);

    // Parse container config for security issues
    static ContainerConfig parseContainerSecurityConfig(
        const std::string& configJson, const std::string& filePath = "");

    // Extract restart count from container metadata
    static int extractRestartCount(const std::string& metadataJson);

    // Detect runtime type from log format
    static std::string detectRuntimeType(const std::string& logContent);

private:
    // Parse Docker json-file line: {"log":"...","stream":"stdout","time":"..."}
    static DockerLogEntry parseDockerJsonLine(const std::string& line, const std::string& filePath);

    // Parse CRI log line: 2023-10-06T10:23:45.123456Z stdout F message
    static CRILogEntry parseCRILine(const std::string& line, const std::string& filePath);

    // Parse timestamp from Docker format
    static int64_t parseDockerTimestamp(const std::string& timestampStr);

    // Parse timestamp from CRI format
    static int64_t parseCRITimestamp(const std::string& timestampStr);

    // Check for privileged container
    static bool isPrivileged(const std::string& configJson);

    // Check for host namespace sharing
    static bool hasHostPID(const std::string& configJson);
    static bool hasHostNetwork(const std::string& configJson);
    static bool hasHostIPC(const std::string& configJson);

    // Check for hostPath mounts
    static std::vector<std::string> extractHostPaths(const std::string& configJson);

    // Check for Docker socket mount
    static bool hasDockerSocketMount(const std::string& configJson);
};

} // namespace linux
} // namespace forensics

#endif // CONTAINER_RUNTIME_LOG_PARSER_H
