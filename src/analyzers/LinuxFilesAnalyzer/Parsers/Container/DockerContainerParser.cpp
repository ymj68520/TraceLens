// DockerContainerParser.cpp
// Implementation of Docker container parser

#include "DockerContainerParser.h"
#include <fstream>
#include <filesystem>
#include <nlohmann/json.hpp>
#include "AuditLog/AuditLog.h"

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace LinuxAnalysis {

DockerContainerParser::ParseResult DockerContainerParser::parseContainers(
    const std::string& dockerDir) {

    ParseResult result;

    // Validate Docker directory
    std::string containersDir = dockerDir;
    if (!fs::exists(containersDir)) {
        result.error = LinuxAnalyzerError(
            ErrorCode::DOCKER_DIR_NOT_FOUND,
            "Docker containers directory not found",
            "Docker containers directory not found: " + containersDir);
        result.error.setComponent("DockerContainerParser");
        result.error.setFilePath(containersDir);
        result.error.setSuggestion("Ensure Docker is installed and has run on the analyzed system");
        result.error.setRecoverable(true);
        return result;
    }

    try {
        auto containerDirs = enumerateContainerDirectories(containersDir);

        for (const auto& containerDir : containerDirs) {
            std::string configPath = containerDir + "/config.json";

            if (!fs::exists(configPath)) {
                AuditLog::instance().log("INFO", "DOCKER_CONFIG_MISSING",
                    "Container config not found: " + configPath);
                continue;
            }

            auto container = parseContainerConfig(configPath);

            if (!isValidContainer(container)) {
                AuditLog::instance().log("INFO", "DOCKER_CONFIG_INVALID",
                    "Invalid container config: " + configPath);
                continue;
            }

            result.containers.push_back(container);
        }

    } catch (const std::exception& e) {
        result.error = LinuxAnalyzerError(
            ErrorCode::DOCKER_CONFIG_PARSE_FAILED,
            "Exception during parsing: " + std::string(e.what()));
        result.error.setComponent("DockerContainerParser");
        result.error.setSuggestion("Check Docker directory structure and permissions");
        result.error.setRecoverable(true);
    }

    AuditLog::instance().log("SUCCESS", "DOCKER_CONTAINERS_PARSED",
        "Parsed " + std::to_string(result.containers.size()) + " Docker containers");

    return result;
}

std::vector<std::string> DockerContainerParser::enumerateContainerDirectories(
    const std::string& containersDir) {

    std::vector<std::string> dirs;

    try {
        for (const auto& entry : fs::directory_iterator(containersDir)) {
            if (entry.is_directory()) {
                dirs.push_back(entry.path().string());
            }
        }
    } catch (const std::exception& e) {
        AuditLog::instance().log("ERROR", "DOCKER_DIR_READ_FAILED",
            "Failed to enumerate containers: " + std::string(e.what()));
    }

    return dirs;
}

DockerContainerInfo DockerContainerParser::parseContainerConfig(
    const std::string& configPath) {

    DockerContainerInfo container;

    try {
        std::ifstream f(configPath);
        if (!f.is_open()) {
            return container;
        }

        json config = json::parse(f);

        // Extract container ID from path
        size_t lastSlash = configPath.find_last_of("/\\");
        if (lastSlash != std::string::npos) {
            size_t prevSlash = configPath.find_last_of("/\\", lastSlash - 1);
            if (prevSlash != std::string::npos) {
                container.containerId = configPath.substr(prevSlash + 1, lastSlash - prevSlash - 1);
            }
        }

        // Parse basic fields
        if (config.contains("Image")) {
            container.imageName = config["Image"];
        }
        if (config.contains("Created")) {
            container.createdAt = config["Created"];
        }
        if (config.contains("State")) {
            auto& state = config["State"];
            if (state.contains("Status")) {
                container.state = state["Status"];
            }
            if (state.contains("Running") && state["Running"] == true) {
                container.state = "running";
            }
        }
        if (config.contains("Config")) {
            auto& cfg = config["Config"];
            if (cfg.contains("Cmd")) {
                auto& cmd = cfg["Cmd"];
                if (cmd.is_array() && !cmd.empty()) {
                    container.command = cmd[0];
                }
            }
            if (cfg.contains("Image")) {
                container.imageTag = cfg["Image"];
            }
        }
        if (config.contains("HostConfig")) {
            auto& hostCfg = config["HostConfig"];
            if (hostCfg.contains("NetworkMode")) {
                container.networkMode = hostCfg["NetworkMode"];
            }
            if (hostCfg.contains("Binds")) {
                for (const auto& bind : hostCfg["Binds"]) {
                    container.mounts.push_back(bind);
                }
            }
        }
        if (config.contains("NetworkSettings")) {
            auto& netSettings = config["NetworkSettings"];
            if (netSettings.contains("Ports")) {
                for (auto& el : netSettings["Ports"].items()) {
                    container.ports.push_back(el.key());
                }
            }
        }

    } catch (const std::exception& e) {
        AuditLog::instance().log("ERROR", "DOCKER_JSON_PARSE_FAILED",
            "Failed to parse config.json: " + std::string(e.what()));
    }

    return container;
}

bool DockerContainerParser::isValidContainer(const DockerContainerInfo& container) {
    if (container.containerId.empty()) return false;

    // Accept any state, even empty (could be created but not started)
    return true;
}

std::vector<DockerImageInfo> DockerContainerParser::parseImages(
    const std::string& dockerDir) {

    std::vector<DockerImageInfo> images;

    // Image metadata is complex and distributed across multiple files
    // For now, return empty list - full implementation requires parsing:
    // - /var/lib/docker/image/overlay2/repositories.json
    // - /var/lib/docker/image/overlay2/layerdb/sha256/*/diff
    // - /var/lib/docker/image/overlay2/imagedb/content/sha256/*

    AuditLog::instance().log("INFO", "DOCKER_IMAGES_NOT_IMPLEMENTED",
        "Docker image parsing not fully implemented");

    return images;
}

std::vector<DockerVolumeInfo> DockerContainerParser::parseVolumes(
    const std::string& dockerDir) {

    std::vector<DockerVolumeInfo> volumes;

    std::string volumeDir = dockerDir + "/volumes";
    if (!fs::exists(volumeDir)) {
        return volumes;
    }

    try {
        for (const auto& entry : fs::directory_iterator(volumeDir)) {
            if (entry.is_directory() && entry.path().filename() != "_data") {
                std::string volumeName = entry.path().filename().string();
                std::string metadataPath = entry.path().string() + "/metadata.json";

                DockerVolumeInfo volume;
                volume.volumeName = volumeName;
                volume.mountpoint = entry.path().string();
                volume.driver = "local";
                volume.createdAt = fs::last_write_time(entry.path()).time_since_epoch().count();

                // Parse metadata if available
                if (fs::exists(metadataPath)) {
                    try {
                        std::ifstream f(metadataPath);
                        json metadata = json::parse(f);
                        if (metadata.contains("CreatedAt")) {
                            volume.createdAt = metadata["CreatedAt"];
                        }
                        if (metadata.contains("Driver")) {
                            volume.driver = metadata["Driver"];
                        }
                    } catch (...) {
                        // Use default values
                    }
                }

                volumes.push_back(volume);
            }
        }
    } catch (const std::exception& e) {
        AuditLog::instance().log("ERROR", "DOCKER_VOLUME_PARSE_FAILED",
            "Failed to parse volumes: " + std::string(e.what()));
    }

    return volumes;
}

std::string DockerContainerParser::extractContainerCommand(
    const std::string& configJson) {

    try {
        json config = json::parse(configJson);
        if (config.contains("Config") && config["Config"].contains("Cmd")) {
            auto& cmd = config["Config"]["Cmd"];
            if (cmd.is_array() && !cmd.empty()) {
                return joinVector(cmd.get<std::vector<std::string>>(), " ");
            }
        }
    } catch (...) {
        // Return empty string on parse failure
    }

    return "";
}

std::string DockerContainerParser::joinVector(const std::vector<std::string>& vec,
                                               const std::string& delim) {
    if (vec.empty()) return "";

    std::string result = vec[0];
    for (size_t i = 1; i < vec.size(); ++i) {
        result += delim + vec[i];
    }
    return result;
}

} // namespace LinuxAnalysis
