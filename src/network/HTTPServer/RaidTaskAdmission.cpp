// SPDX-License-Identifier: MIT
#include "RaidTaskAdmission.h"
#include "AndroidPreflightAdmission.h"
#include "PathManager/PathManager.h"
#include <filesystem>
#include <fstream>
#include <regex>
#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
namespace {
bool contained(const fs::path& root, const fs::path& path) {
    const auto relative = fs::canonical(path).lexically_relative(fs::canonical(root));
    if (relative.empty() || relative.is_absolute()) return false;
    for (const auto& part : relative) if (part == "..") return false;
    return true;
}
bool regular(const fs::path& path) {
    return fs::is_regular_file(path) && !fs::is_symlink(fs::symlink_status(path));
}
nlohmann::json readJson(const fs::path& path) {
    if (!regular(path) || fs::file_size(path) > 2 * 1024 * 1024) throw std::runtime_error("invalid private manifest");
    std::ifstream input(path); nlohmann::json data; input >> data; return data;
}
}

bool isPreparedRaidImage(const std::string& imagePath) {
    try {
        const auto root = forensics::PathManager::instance().getDataDir() / "raid_intake";
        return fs::exists(root) && fs::exists(imagePath) && contained(root, imagePath);
    } catch (...) { return false; }
}

RaidTaskAdmissionResult admitRaidImage(const std::string& imagePath,
    const std::string& jobId, const std::string& manifestHash,
    const std::string& principal, bool allowPartial) {
    RaidTaskAdmissionResult result;
    if (!std::regex_match(jobId, std::regex("[0-9a-f]{32}")) ||
        !std::regex_match(manifestHash, std::regex("[0-9a-f]{64}")) || principal.empty()) return result;
    try {
        const auto root = forensics::PathManager::instance().getDataDir() / "raid_intake";
        const auto jobRoot = root / jobId;
        if (fs::is_symlink(jobRoot) || !contained(root, jobRoot)) return result;
        const auto job = readJson(jobRoot / "job.json");
        if (job.at("id") != jobId || job.at("owner") != principal || job.at("status") != "ready" ||
            job.at("manifest_sha256") != manifestHash || job.at("allow_partial").get<bool>() != allowPartial)
            return result;
        const fs::path package = job.at("package_directory").get<std::string>();
        const fs::path image = imagePath;
        if (!contained(jobRoot / "packages", package) || fs::is_symlink(package) ||
            fs::canonical(image) != fs::canonical(package / "logical.img") || !regular(image) ||
            fs::canonical(image) != fs::canonical(job.at("image_path").get<std::string>())) return result;
        const auto manifestPath = package / "raid_manifest.json";
        const auto manifest = readJson(manifestPath);
        const std::string status = manifest.at("status");
        if ((status != "COMPLETE" && !(allowPartial && status == "PARTIAL")) ||
            job.at("integrity_status") != status || manifest.at("manifest_sha256") != manifestHash ||
            manifest.at("derived_image").at("sha256") != job.at("image_sha256")) return result;
        if (!manifest.at("source_sha256").is_object() || manifest.at("source_sha256").size() < 2)
            return result;
        if (!sourceMatchesPreflightHash(manifestPath.string(), job.at("manifest_file_sha256")) ||
            !sourceMatchesPreflightHash(imagePath, job.at("image_sha256"))) {
            result.code = "RAID_PREPARED_IMAGE_CHANGED"; return result;
        }
        const fs::path sourceRoot = manifest.at("source_root").get<std::string>();
        if (fs::canonical(sourceRoot) != fs::canonical(job.at("source_root").get<std::string>())) return result;
        for (const auto& [name, hash] : manifest.at("source_sha256").items()) {
            const fs::path relative(name);
            if (relative.is_absolute()) return result;
            fs::path current = sourceRoot;
            for (const auto& part : relative) {
                if (part == ".." || part == ".") return result;
                current /= part;
                if (fs::is_symlink(fs::symlink_status(current))) return result;
            }
            if (!contained(sourceRoot, current) || !regular(current) ||
                !sourceMatchesPreflightHash(current.string(), hash)) {
                result.code = "RAID_ORIGINAL_MEMBER_CHANGED"; return result;
            }
        }
        result.accepted = true; result.code.clear();
        result.metadata = {{"source_kind", "raid"}, {"source_label", job.at("display_name")},
            {"source_verification", "RAID_DERIVED_IMAGE_VERIFIED"}, {"raid_job_id", jobId},
            {"raid_manifest_sha256", manifestHash}, {"raid_manifest_path", manifestPath.string()},
            {"raid_manifest_file_sha256", job.at("manifest_file_sha256")},
            {"raid_image_sha256", job.at("image_sha256")}, {"raid_integrity_status", status},
            {"raid_allow_partial", allowPartial ? "true" : "false"},
            {"raid_requested_by", principal}};
    } catch (...) {}
    return result;
}
