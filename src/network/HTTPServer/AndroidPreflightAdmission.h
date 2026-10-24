#pragma once

#include <map>
#include <string>

struct AndroidPreflightAdmissionResult {
    bool accepted = false;
    std::string code;
    std::string detail;
    std::map<std::string, std::string> metadata;
};

AndroidPreflightAdmissionResult admitAndroidArchiveSource(
    const std::string& path, const std::string& adapter,
    const std::string& jobId, const std::string& claimedHash,
    const std::string& claimedKind, bool passwordSupplied);

AndroidPreflightAdmissionResult admitAndroidFilesystemImage(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind);

AndroidPreflightAdmissionResult admitAndroidContainerSource(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind,
    const std::string& claimedPlanHash, int selectedSlot);

bool sourceMatchesPreflightHash(const std::string& path,
                                const std::string& expectedSha256);

AndroidPreflightAdmissionResult admitAliyunImage(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind);
