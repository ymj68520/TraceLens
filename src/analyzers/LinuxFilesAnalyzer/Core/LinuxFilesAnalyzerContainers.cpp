// LinuxFilesAnalyzerContainers.cpp
// Container-related analysis methods of LinuxFilesAnalyzer
// (Docker, Podman, container runtime logs)

#include "LinuxFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"

#include <filesystem>
#include <fstream>
#include <sstream>

// Container parsers
#include "Parsers/Container/DockerContainerParser.h"
#include "Parsers/Container/PodmanParser.h"

// Container runtime log parser (Phase 8)
#include "Parsers/Container/ContainerRuntimeLogParser.h"

using forensics::linux::ContainerRuntimeLogParser;
using forensics::linux::CRILogEntry;
using forensics::linux::ContainerConfig;

namespace fs = std::filesystem;

// ============================================================================
// Container Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::analyzeDockerContainers() {
    std::cout << "Analyzing Docker containers..." << std::endl;

    // Look for Docker directory
    auto dockerDirs = queryFilesByPattern("var/lib/docker/%");
    if (dockerDirs.empty()) {
        std::cout << "  No Docker data found (skipping)" << std::endl;
        AuditLog::instance().log("LINUX", "DOCKER_NOT_FOUND", "No Docker directory found in image");
        return;
    }

    // Extract Docker containers directory
    std::string extractPath = getExtractPath("docker/containers");
    fs::create_directories(extractPath);

    // Query and extract container config files
    auto containerConfigs = queryFilesByPattern("var/lib/docker/containers/%/config.json");
    for (const auto& file : containerConfigs) {
        std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".json";
        if (extractFileToPath(file.inode, outputPath)) {
            AuditLog::instance().log("LINUX", "DOCKER_CONFIG_EXTRACTED",
                "Extracted container config: " + file.name);
        }
    }

    // Parse containers
    auto result = LinuxAnalysis::DockerContainerParser::parseContainers(extractPath);
    if (result.success()) {
        linuxDb_->insertDockerContainers(result.containers);
        std::cout << "  Found " << result.containers.size() << " Docker containers" << std::endl;
        AuditLog::instance().log("SUCCESS", "DOCKER_CONTAINERS_PARSED",
            "Parsed " + std::to_string(result.containers.size()) + " Docker containers");
    } else {
        AuditLog::instance().log("ERROR", "DOCKER_PARSE_FAILED",
            "Failed to parse Docker containers: " + result.error.details());
    }
}

void LinuxFilesAnalyzer::analyzeDockerImages() {
    std::cout << "Analyzing Docker images..." << std::endl;

    auto dockerDirs = queryFilesByPattern("var/lib/docker/%");
    if (dockerDirs.empty()) {
        std::cout << "  No Docker data found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("docker/images");
    fs::create_directories(extractPath);

    // Look for image metadata
    auto imageFiles = queryFilesByPattern("var/lib/docker/image/%/%/repositories.json");
    for (const auto& file : imageFiles) {
        std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".json";
        extractFileToPath(file.inode, outputPath);
    }

    auto images = LinuxAnalysis::DockerContainerParser::parseImages(extractPath);
    if (!images.empty()) {
        linuxDb_->insertDockerImages(images);
        std::cout << "  Found " << images.size() << " Docker images" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzeDockerVolumes() {
    std::cout << "Analyzing Docker volumes..." << std::endl;

    auto dockerDirs = queryFilesByPattern("var/lib/docker/%");
    if (dockerDirs.empty()) {
        std::cout << "  No Docker data found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("docker/volumes");
    fs::create_directories(extractPath);

    auto volumes = LinuxAnalysis::DockerContainerParser::parseVolumes(extractPath);
    if (!volumes.empty()) {
        linuxDb_->insertDockerVolumes(volumes);
        std::cout << "  Found " << volumes.size() << " Docker volumes" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzePodmanContainers() {
    std::cout << "Analyzing Podman containers..." << std::endl;

    // Check both system and user-level Podman directories
    std::vector<std::string> podmanPaths = {
        "var/lib/containers/%",
        "home/%/.local/share/containers/%"
    };

    bool foundPodman = false;
    for (const auto& pattern : podmanPaths) {
        auto files = queryFilesByPattern(pattern);
        if (!files.empty()) {
            foundPodman = true;
            break;
        }
    }

    if (!foundPodman) {
        std::cout << "  No Podman data found (skipping)" << std::endl;
        AuditLog::instance().log("LINUX", "PODMAN_NOT_FOUND", "No Podman directory found");
        return;
    }

    std::string extractPath = getExtractPath("podman");
    fs::create_directories(extractPath);

    auto result = LinuxAnalysis::PodmanParser::parseContainers(extractPath);
    if (result.success()) {
        linuxDb_->insertPodmanContainers(result.containers);
        linuxDb_->insertPodmanPods(result.pods);
        std::cout << "  Found " << result.containers.size() << " Podman containers, "
                  << result.pods.size() << " pods" << std::endl;
    }
}

// ============================================================================
// Container Runtime Log Analysis Implementation (Phase 8)
// ============================================================================

void LinuxFilesAnalyzer::analyzeContainerRuntimeLogs() {
    using namespace forensics::linux;

    std::cout << "Analyzing container runtime logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "CONTAINER_LOG_START", "Starting container runtime log analysis: " + imagePath_);

    int totalDockerLogs = 0;
    int totalCRILogs = 0;
    int totalSecurityFindings = 0;

    // Helper to read file content
    auto readFile = [](const std::string& path) -> std::string {
        std::ifstream f(path, std::ios::binary);
        if (!f.is_open()) return "";
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    };

    // Docker json-file log paths
    std::vector<std::string> dockerLogPatterns = {
        "/var/lib/docker/containers/*/*-json.log",
        "/var/lib/docker/containers/*/*.log"
    };

    // CRI / Kubernetes log paths
    std::vector<std::string> criLogPatterns = {
        "/var/log/containers/*.log",
        "/var/log/pods/*/*.log",
        "/var/log/kubelet.log",
        "/var/log/crio/pods/*.log"
    };

    // Process Docker json-file logs
    for (const auto& pattern : dockerLogPatterns) {
        // Use glob to find matching files
        std::string cmd = "ls " + extractDir_ + pattern + " 2>/dev/null";
        FILE* pipe = popen(cmd.c_str(), "r");
        if (!pipe) continue;

        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), pipe)) {
            std::string filePath(buffer);
            // Trim newline
            while (!filePath.empty() && (filePath.back() == '\n' || filePath.back() == '\r')) {
                filePath.pop_back();
            }
            if (filePath.empty()) continue;

            std::string content = readFile(filePath);
            if (content.empty()) continue;

            auto entries = ContainerRuntimeLogParser::parseDockerJsonLog(content, filePath);
            if (!entries.empty()) {
                if (linuxDb_->insertContainerLogs(entries)) {
                    totalDockerLogs += entries.size();
                    std::cout << "  Parsed " << entries.size() << " Docker log entries from " << filePath << std::endl;
                }
            }
        }
        pclose(pipe);
    }

    // Process CRI / Kubernetes logs
    for (const auto& pattern : criLogPatterns) {
        std::string cmd = "ls " + extractDir_ + pattern + " 2>/dev/null";
        FILE* pipe = popen(cmd.c_str(), "r");
        if (!pipe) continue;

        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), pipe)) {
            std::string filePath(buffer);
            while (!filePath.empty() && (filePath.back() == '\n' || filePath.back() == '\r')) {
                filePath.pop_back();
            }
            if (filePath.empty()) continue;

            std::string content = readFile(filePath);
            if (content.empty()) continue;

            // Auto-detect runtime type
            std::string runtimeType = ContainerRuntimeLogParser::detectRuntimeType(content);

            if (runtimeType == "cri" || runtimeType == "unknown") {
                // Try parsing as Kubernetes pod log first (extracts pod metadata from filename)
                auto podEntries = ContainerRuntimeLogParser::parseKubernetesPodLog(content, filePath);
                if (!podEntries.empty()) {
                    // Convert to CRI entries for storage
                    std::vector<CRILogEntry> criEntries;
                    for (const auto& pod : podEntries) {
                        CRILogEntry cri;
                        cri.timestamp = pod.timestamp;
                        cri.stream = pod.stream;
                        cri.message = pod.message;
                        cri.containerId = pod.containerId;
                        cri.podName = pod.podName;
                        cri.namespace_ = pod.namespace_;
                        cri.containerName = pod.containerName;
                        cri.filePath = pod.filePath;
                        cri.provenance = pod.provenance;
                        criEntries.push_back(cri);
                    }
                    if (linuxDb_->insertCRILogs(criEntries)) {
                        totalCRILogs += criEntries.size();
                        std::cout << "  Parsed " << criEntries.size() << " K8s pod log entries from " << filePath << std::endl;
                    }
                }
            }
        }
        pclose(pipe);
    }

    // Analyze container security configurations
    // Look for Docker container config files
    std::string configCmd = "ls " + extractDir_ + "/var/lib/docker/containers/*/config.v2.json 2>/dev/null";
    FILE* configPipe = popen(configCmd.c_str(), "r");
    if (configPipe) {
        std::vector<ContainerConfig> configs;
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), configPipe)) {
            std::string configPath(buffer);
            while (!configPath.empty() && (configPath.back() == '\n' || configPath.back() == '\r')) {
                configPath.pop_back();
            }
            if (configPath.empty()) continue;

            std::string content = readFile(configPath);
            if (content.empty()) continue;

            auto config = ContainerRuntimeLogParser::parseContainerSecurityConfig(content, configPath);

            // Extract container ID from path
            size_t lastSlash = configPath.rfind('/');
            if (lastSlash != std::string::npos) {
                size_t secondLast = configPath.rfind('/', lastSlash - 1);
                if (secondLast != std::string::npos) {
                    config.containerId = configPath.substr(secondLast + 1, lastSlash - secondLast - 1);
                }
            }

            configs.push_back(config);
        }
        pclose(configPipe);

        if (!configs.empty()) {
            auto findings = ContainerRuntimeLogParser::analyzeContainerSecurity(configs);
            if (!findings.empty()) {
                if (linuxDb_->insertContainerSecurityFindings(findings)) {
                    totalSecurityFindings += findings.size();
                    std::cout << "  Found " << findings.size() << " container security findings" << std::endl;

                    for (const auto& finding : findings) {
                        if (finding.severity == "critical") {
                            std::cout << "    [CRITICAL] " << finding.findingType
                                      << ": " << finding.description << std::endl;
                        }
                    }
                }
            }
        }
    }

    std::cout << "  Docker logs: " << totalDockerLogs
              << ", CRI/K8s logs: " << totalCRILogs
              << ", Security findings: " << totalSecurityFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "CONTAINER_LOG_COMPLETE",
        "Container log analysis: " + std::to_string(totalDockerLogs) + " Docker logs, " +
        std::to_string(totalCRILogs) + " CRI logs, " +
        std::to_string(totalSecurityFindings) + " security findings");
}
