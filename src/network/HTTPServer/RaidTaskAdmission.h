#pragma once
#include <map>
#include <string>

struct RaidTaskAdmissionResult {
    bool accepted = false;
    std::string code = "RAID_PREFLIGHT_REQUIRED";
    std::map<std::string, std::string> metadata;
};

RaidTaskAdmissionResult admitRaidImage(const std::string& imagePath,
    const std::string& jobId, const std::string& manifestHash,
    const std::string& principal, bool allowPartial);
bool isPreparedRaidImage(const std::string& imagePath);
