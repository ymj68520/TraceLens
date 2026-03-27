#pragma once

#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "FileClassifierTypes.h"

namespace forensics {

/**
 * @brief File extension and pattern mappings
 */
class FileClassifierMappings {
public:
    static void initializeExtensionMap(std::unordered_map<std::string, FileCategory>& extensionMap);
    static void initializeExtendedExtensionMap(std::unordered_map<std::string, FileCategory>& extendedExtensionMap);
    static void initializePathPatterns(
        std::unordered_set<std::string>& osConfigPaths,
        std::unordered_set<std::string>& bootPaths,
        std::unordered_set<std::string>& libraryPaths,
        std::unordered_set<std::string>& logPaths,
        std::unordered_set<std::string>& cachePaths,
        std::unordered_set<std::string>& tempPaths
    );
    static void initializeFilenamePatterns(
        std::vector<std::string>& systemConfigFiles,
        std::vector<std::string>& bootFiles,
        std::vector<std::string>& logPatterns,
        std::vector<std::string>& backupPatterns
    );
};

} // namespace forensics
