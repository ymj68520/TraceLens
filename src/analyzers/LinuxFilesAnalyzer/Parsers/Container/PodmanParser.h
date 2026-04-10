// PodmanParser.h
// Parses Podman container artifacts

#pragma once
#ifndef PODMAN_PARSER_H
#define PODMAN_PARSER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Parses Podman container and pod configurations
 *
 * Podman stores data differently from Docker:
 * - System containers: /var/lib/containers/storage/overlay-containers/
 * - User (rootless) containers: ~/.local/share/containers/storage/overlay-containers/
 * - Pods: /var/lib/containers/storage/overlay-pods/ or ~/.local/share/containers/
 */
class PodmanParser {
public:
    struct ParseResult {
        std::vector<PodmanContainerInfo> containers;
        std::vector<PodmanPodInfo> pods;
        LinuxAnalyzerError error;

        bool success() const { return !error.isError(); }
    };

    /**
     * @brief Parse Podman containers from directory
     * @param podmanDir Path containing extracted Podman data
     * @return Parse result with container and pod information
     */
    static ParseResult parseContainers(const std::string& podmanDir);

    /**
     * @brief Parse Podman pods from directory
     * @param podmanDir Path containing extracted Podman pod data
     * @return Vector of Podman pod information
     */
    static std::vector<PodmanPodInfo> parsePods(const std::string& podmanDir);

private:
    /**
     * @brief Check if container is rootless (user-owned)
     * @param containerPath Path to container directory
     * @return true if container is in user directory
     */
    static bool isRootlessContainer(const std::string& containerPath);

    /**
     * @brief Parse container config file
     * @param configPath Path to config file
     * @return Parsed container information
     */
    static PodmanContainerInfo parseContainerConfig(const std::string& configPath);

    /**
     * @brief Parse pod config file
     * @param configPath Path to pod config file
     * @return Parsed pod information
     */
    static PodmanPodInfo parsePodConfig(const std::string& configPath);
};

} // namespace LinuxAnalysis

#endif // PODMAN_PARSER_H
