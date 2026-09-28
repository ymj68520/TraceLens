#pragma once

#include <cstddef>
#include <string>
#include <unordered_map>
#include <vector>

struct AndroidPathMappingResult {
    bool valid = false;
    std::string rootMapping;
    std::string confidence;
    std::string reason;
    std::unordered_map<std::string, std::string> normalizedToMember;
    std::size_t nestedContainerCount = 0;
};

// Maps only demonstrable Android filesystem roots. It never follows links or
// treats an arbitrary directory named "data" as an Android extraction.
class AndroidPathMapper {
public:
    static AndroidPathMappingResult build(const std::vector<std::string>& regularMembers,
                                          bool androidBackup = false);
    // A userdata partition is mounted at /data on Android. Its filesystem root
    // contains data/, system/, misc/, user/, etc.; no wrapper is guessed.
    static AndroidPathMappingResult buildUserdata(const std::vector<std::string>& regularPaths);
    static bool safeMemberPath(const std::string& raw, std::string& cleaned,
                               std::string& reason);
    static bool normalizeRequest(const std::string& raw, std::string& normalized);
};
