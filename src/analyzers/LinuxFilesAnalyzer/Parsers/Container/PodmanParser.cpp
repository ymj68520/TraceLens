// PodmanParser.cpp
// Implementation of Podman parser

#include "PodmanParser.h"
#include <fstream>
#include <filesystem>
#include <nlohmann/json.hpp>
#include "AuditLog/AuditLog.h"

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace LinuxAnalysis {

PodmanParser::ParseResult PodmanParser::parseContainers(
    const std::string& podmanDir) {

    ParseResult result;

    // Check both user and system containers
    std::vector<std::string> searchPaths = {
        podmanDir + "/libpod/containers",
        podmanDir + "/storage/overlay-containers"
    };

    bool foundAny = false;
    for (const auto& containerPath : searchPaths) {
        if (!fs::exists(containerPath)) continue;

        try {
            for (const auto& entry : fs::directory_iterator(containerPath)) {
                if (entry.is_directory()) {
                    foundAny = true;
                    std::string configPath = entry.path().string() + "/config";

                    PodmanContainerInfo container;
                    container.containerId = entry.path().filename().string();
                    container.isRootless = isRootlessContainer(entry.path().string());

                    if (fs::exists(configPath)) {
                        container = parseContainerConfig(configPath);
                        container.containerId = entry.path().filename().string();
                        container.isRootless = isRootlessContainer(entry.path().string());
                    }

                    result.containers.push_back(container);
                }
            }
        } catch (const std::exception& e) {
            AuditLog::instance().log("ERROR", "PODMAN_PARSE_ERROR",
                "Error parsing Podman containers: " + std::string(e.what()));
        }
    }

    if (!foundAny) {
        result.error = {
            .code = ErrorCode::PODMAN_DIR_NOT_FOUND,
            .component = "PodmanParser",
            .details = "No Podman containers found",
            .isRecoverable = true
        };
    }

    AuditLog::instance().log("SUCCESS", "PODMAN_CONTAINERS_PARSED",
        "Parsed " + std::to_string(result.containers.size()) + " Podman containers");

    return result;
}

std::vector<PodmanPodInfo> PodmanParser::parsePods(const std::string& podmanDir) {
    std::vector<PodmanPodInfo> pods;

    std::vector<std::string> searchPaths = {
        podmanDir + "/libpod/pods",
        podmanDir + "/storage/overlay-pods"
    };

    for (const auto& podsPath : searchPaths) {
        if (!fs::exists(podsPath)) continue;

        try {
            for (const auto& entry : fs::directory_iterator(podsPath)) {
                if (entry.is_directory()) {
                    std::string configPath = entry.path().string() + "/config.json";

                    PodmanPodInfo pod;
                    pod.podId = entry.path().filename().string();

                    if (fs::exists(configPath)) {
                        pod = parsePodConfig(configPath);
                        pod.podId = entry.path().filename().string();
                    }

                    pods.push_back(pod);
                }
            }
        } catch (const std::exception& e) {
            AuditLog::instance().log("ERROR", "PODMAN_PODS_PARSE_ERROR",
                "Error parsing Podman pods: " + std::string(e.what()));
        }
    }

    AuditLog::instance().log("SUCCESS", "PODMAN_PODS_PARSED",
        "Parsed " + std::to_string(pods.size()) + " Podman pods");

    return pods;
}

bool PodmanParser::isRootlessContainer(const std::string& containerPath) {
    // Rootless containers are typically in user home directories
    return containerPath.find("/home/") != std::string::npos ||
           containerPath.find("/root/") != std::string::npos;
}

PodmanContainerInfo PodmanParser::parseContainerConfig(const std::string& configPath) {
    PodmanContainerInfo container;

    try {
        std::ifstream f(configPath);
        if (!f.is_open()) {
            return container;
        }

        // Podman config files are JSON
        json config = json::parse(f);

        if (config.contains("rootfs")) {
            container.imageName = config["rootfs"];
        }
        if (config.contains("name")) {
            container.containerId = config["name"];
        }
        if (config.contains("created")) {
            container.createdAt = config["created"];
        }
        if (config.contains("pod")) {
            container.podName = config["pod"];
        }

        // Determine state from various fields
        if (config.contains("state")) {
            container.state = config["state"];
        } else {
            container.state = "unknown";
        }

    } catch (const std::exception& e) {
        AuditLog::instance().log("ERROR", "PODMAN_CONFIG_PARSE_FAILED",
            "Failed to parse Podman config: " + std::string(e.what()));
    }

    return container;
}

PodmanPodInfo PodmanParser::parsePodConfig(const std::string& configPath) {
    PodmanPodInfo pod;

    try {
        std::ifstream f(configPath);
        if (!f.is_open()) {
            return pod;
        }

        json config = json::parse(f);

        if (config.contains("name")) {
            pod.podName = config["name"];
        }
        if (config.contains("created")) {
            pod.createdAt = config["created"];
        }

        // Get state
        if (config.contains("State")) {
            pod.state = config["State"];
        } else {
            pod.state = "unknown";
        }

        // Find container IDs in this pod
        if (config.contains("containers")) {
            for (const auto& c : config["containers"]) {
                if (c.contains("id")) {
                    pod.containerIds.push_back(c["id"]);
                }
            }
        }

    } catch (const std::exception& e) {
        AuditLog::instance().log("ERROR", "PODMAN_POD_CONFIG_PARSE_FAILED",
            "Failed to parse Podman pod config: " + std::string(e.what()));
    }

    return pod;
}

} // namespace LinuxAnalysis
