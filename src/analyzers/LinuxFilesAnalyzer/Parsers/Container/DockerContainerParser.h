// DockerContainerParser.h
// Parses Docker container artifacts from /var/lib/docker

#pragma once
#ifndef DOCKER_CONTAINER_PARSER_H
#define DOCKER_CONTAINER_PARSER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Parses Docker container configurations and metadata
 *
 * Extracts information from Docker installation directories:
 * 1. Container configuration files from /var/lib/docker/containers/
 * 2. Image metadata from /var/lib/docker/image/overlay2/layerdb
 * 3. Volume metadata from /var/lib/docker/volumes/
 */
class DockerContainerParser {
public:
    struct ParseResult {
        std::vector<DockerContainerInfo> containers;
        std::vector<DockerImageInfo> images;
        std::vector<DockerVolumeInfo> volumes;
        LinuxAnalyzerError error;

        bool success() const { return !error.isError(); }
    };

    /**
     * @brief Parse Docker containers from directory
     * @param dockerDir Path containing extracted Docker container configs
     * @return Parse result with container information
     */
    static ParseResult parseContainers(const std::string& dockerDir);

    /**
     * @brief Parse Docker images from directory
     * @param dockerDir Path containing extracted Docker image metadata
     * @return Vector of Docker image information
     */
    static std::vector<DockerImageInfo> parseImages(const std::string& dockerDir);

    /**
     * @brief Parse Docker volumes from directory
     * @param dockerDir Path containing extracted Docker volume metadata
     * @return Vector of Docker volume information
     */
    static std::vector<DockerVolumeInfo> parseVolumes(const std::string& dockerDir);

    /**
     * @brief Extract container command from config JSON
     * @param configJson JSON configuration string
     * @return Command string or empty if parsing fails
     */
    static std::string extractContainerCommand(const std::string& configJson);

    /**
     * @brief Validate container info
     * @param container Container info to validate
     * @return true if container has valid required fields
     */
    static bool isValidContainer(const DockerContainerInfo& container);

private:
    /**
     * @brief Parse container config.json file
     * @param configPath Path to config.json
     * @return Parsed container information
     */
    static DockerContainerInfo parseContainerConfig(const std::string& configPath);

    /**
     * @brief Enumerate container directories
     * @param dockerDir Path to Docker containers directory
     * @return List of container directory paths
     */
    static std::vector<std::string> enumerateContainerDirectories(const std::string& dockerDir);

    /**
     * @brief Helper to join vector of strings with delimiter
     * @param vec String vector to join
     * @param delim Delimiter to use
     * @return Joined string
     */
    static std::string joinVector(const std::vector<std::string>& vec,
                                   const std::string& delim = ",");
};

} // namespace LinuxAnalysis

#endif // DOCKER_CONTAINER_PARSER_H
