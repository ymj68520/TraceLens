#include "AndroidPreflightAdmission.h"

#include "PathManager/PathManager.h"

#include <nlohmann/json.hpp>
#include <openssl/evp.h>

#include <array>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace fs = std::filesystem;
namespace {
bool isHex(const std::string& value, std::size_t length) {
    if (value.size() != length) return false;
    for (char ch : value)
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) return false;
    return true;
}

std::string sha256(const std::string& path) {
    std::ifstream source(path, std::ios::binary);
    if (!source) return {};
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) return {};
    bool okay = EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr) == 1;
    std::array<char, 1 << 20> bytes{};
    while (okay && source) {
        source.read(bytes.data(), bytes.size());
        if (source.gcount() > 0)
            okay = EVP_DigestUpdate(ctx, bytes.data(), static_cast<std::size_t>(source.gcount())) == 1;
    }
    unsigned char digest[EVP_MAX_MD_SIZE]{};
    unsigned int length = 0;
    okay = okay && !source.bad() && EVP_DigestFinal_ex(ctx, digest, &length) == 1;
    EVP_MD_CTX_free(ctx);
    if (!okay) return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned int i = 0; i < length; ++i) out << std::setw(2) << static_cast<int>(digest[i]);
    return out.str();
}
} // namespace

bool sourceMatchesPreflightHash(const std::string& path, const std::string& expectedSha256) {
    if (!isHex(expectedSha256, 64)) return false;
    return sha256(path) == expectedSha256;
}

AndroidPreflightAdmissionResult admitAliyunImage(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind) {
    AndroidPreflightAdmissionResult result;
    result.code = "PREFLIGHT_REQUIRED";
    result.detail = "阿里云镜像导出包须先完成完整 SHA-256 预检";
    if (!isHex(jobId, 32) || !isHex(claimedHash, 64) || claimedKind != "aliyun_raw_export") return result;
    try {
        const auto root = forensics::PathManager::instance().getDataDir() / "evidence_preflight";
        const auto file = root / jobId / "job.json";
        if (!fs::is_regular_file(file) || fs::is_symlink(file) || fs::is_symlink(file.parent_path()) ||
            fs::file_size(file) > 8 * 1024 * 1024 || fs::is_symlink(path)) return result;
        nlohmann::json job;
        std::ifstream stream(file);
        stream >> job;
        if (job.at("id") != jobId || job.at("status") != "completed" ||
            job.at("integrity_status") != "verified" || !job.at("full_hash").get<bool>() ||
            job.at("sha256") != claimedHash || job.at("detected").at("kind") != claimedKind ||
            job.at("detected").at("adapter") != "aliyun-image" ||
            !job.at("aliyun_image").at("ready").get<bool>()) return result;
        const auto source = fs::canonical(path);
        if (source != fs::canonical(job.at("source_path").get<std::string>()) ||
            fs::file_size(source) != job.at("source_size").get<uint64_t>()) {
            result.code = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            result.detail = "镜像来源已变化，请重新预检";
            return result;
        }
        // Rehash while unpacking in the worker. Do not block HTTP admission on
        // a multi-GB read; no filesystem analysis begins before that check passes.
        result.metadata = {{"preflight_job_id", jobId}, {"preflight_source_sha256", claimedHash},
            {"source_kind", "aliyun-image"}, {"source_label", source.filename().string()},
            {"aliyun_original_source", source.string()}, {"preflight_detected_kind", claimedKind}};
        result.accepted = true;
        result.code = "ACCEPTED";
        result.detail = "预检已通过，任务将完整校验并解包 RAW";
    } catch (...) {}
    return result;
}

AndroidPreflightAdmissionResult admitXiaomiImage(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind) {
    AndroidPreflightAdmissionResult result;
    result.code = "PREFLIGHT_REQUIRED";
    result.detail = "小米手机镜像须先完成完整 SHA-256 预检";
#ifdef _WIN32
    result.code="XIAOMI_REQUIRES_LINUX_RUNTIME";
    result.detail="小米镜像读取需要 Linux 或 WSL 后端";
    return result;
#endif
    if (!isHex(jobId, 32) || !isHex(claimedHash, 64) || claimedKind != "xiaomi_export_image") return result;
    try {
        const auto root = forensics::PathManager::instance().getDataDir() / "evidence_preflight";
        const auto file = root / jobId / "job.json";
        if (!fs::is_regular_file(file) || fs::is_symlink(file) || fs::is_symlink(file.parent_path()) ||
            fs::file_size(file) > 8 * 1024 * 1024 || fs::is_symlink(path)) return result;
        nlohmann::json job;
        std::ifstream stream(file);
        stream >> job;
        if (job.at("id") != jobId || job.at("status") != "completed" ||
            job.at("integrity_status") != "verified" || !job.at("full_hash").get<bool>() ||
            job.at("sha256") != claimedHash || job.at("detected").at("kind") != claimedKind ||
            job.at("detected").at("adapter") != "xiaomi-image" ||
            !job.at("xiaomi_image").at("ready").get<bool>()) return result;
        const auto source = fs::canonical(path);
        if (source != fs::canonical(job.at("source_path").get<std::string>()) ||
            fs::file_size(source) != job.at("source_size").get<uint64_t>()) {
            result.code = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            result.detail = "镜像来源已变化，请重新预检";
            return result;
        }
        // The index worker rehashes the image; the task compares that identity
        // before classification, mobile parsing or intelligence starts.
        result.metadata = {{"preflight_job_id", jobId}, {"preflight_source_sha256", claimedHash},
            {"source_kind", "xiaomi-image"}, {"source_label", source.filename().string()},
            {"xiaomi_original_source", source.string()}, {"preflight_detected_kind", claimedKind}};
        result.accepted = true;
        result.code = "ACCEPTED";
        result.detail = "预检已通过，任务将验证镜像并建立来源索引";
    } catch (...) {}
    return result;
}

AndroidPreflightAdmissionResult admitAndroidContainerSource(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind,
    const std::string& claimedPlanHash, int selectedSlot) {
    AndroidPreflightAdmissionResult result;
    result.code = "PREFLIGHT_REQUIRED";
    result.detail = "Completed full-hash container validation and normalization plan required";
    if (!isHex(jobId, 32) || !isHex(claimedHash, 64) ||
        !isHex(claimedPlanHash, 64) || selectedSlot < 0 || selectedSlot > 31)
        return result;
    const std::map<std::string, std::string> allowed{
        {"android_sparse_userdata", "ANDROID_SPARSE_USERDATA"},
        {"android_raw_super", "ANDROID_RAW_SUPER"},
        {"android_sparse_super", "ANDROID_SPARSE_SUPER"},
        {"android_full_disk_super", "ANDROID_FULL_DISK_SUPER"}};
    const auto expectedKind = allowed.find(claimedKind);
    if (expectedKind == allowed.end()) return result;
    try {
        const fs::path jobFile = forensics::PathManager::instance().getDataDir() /
                                 "evidence_preflight" / jobId / "job.json";
        std::error_code ec;
        if (!fs::is_regular_file(jobFile, ec) || ec ||
            fs::is_symlink(fs::symlink_status(jobFile, ec))) return result;
        std::ifstream input(jobFile);
        nlohmann::json job; input >> job;
        const auto& container = job.at("container");
        if (job.at("id") != jobId || job.at("status") != "completed" ||
            job.at("integrity_status") != "verified" || job.at("full_hash") != true ||
            job.at("sha256") != claimedHash ||
            job.at("detected").at("kind") != claimedKind ||
            job.at("detected").at("adapter") != "android-container" ||
            job.at("selected_slot").get<int>() != selectedSlot ||
            container.at("selected_slot").get<int>() != selectedSlot ||
            container.at("kind") != expectedKind->second ||
            container.at("plan_sha256") != claimedPlanHash ||
            container.at("ready") != true) return result;
        if (claimedKind == "android_sparse_userdata" &&
            (container.at("sparse").at("validation_status") != "VALIDATED" ||
             container.at("userdata_preflight").at("ready") != true)) return result;
        if (claimedKind != "android_sparse_userdata" &&
            (container.at("super_inventory").at("status") != "ANDROID_SUPER" ||
             container.at("super_inventory").at("ready") != true)) return result;
        const fs::path source = fs::canonical(path);
        if (source != fs::canonical(job.at("source_path").get<std::string>()) ||
            fs::file_size(source) != job.at("source_size").get<std::uint64_t>() ||
            !sourceMatchesPreflightHash(source.string(), claimedHash)) {
            result.code = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            result.detail = "Container source changed after preflight";
            return result;
        }
        result.accepted = true;
        result.code.clear(); result.detail.clear();
        result.metadata = {{"preflight_job_id", jobId},
                           {"preflight_source_sha256", claimedHash},
                           {"preflight_detected_kind", claimedKind},
                           {"preflight_adapter", "android-container"},
                           {"preflight_plan_sha256", claimedPlanHash},
                           {"preflight_selected_slot", std::to_string(selectedSlot)},
                           {"preflight_source_size", std::to_string(fs::file_size(source))},
                           {"preflight_container_kind", expectedKind->second}};
    } catch (const std::exception&) { return result; }
    return result;
}

AndroidPreflightAdmissionResult admitAndroidFilesystemImage(
    const std::string& path, const std::string& jobId,
    const std::string& claimedHash, const std::string& claimedKind) {
    AndroidPreflightAdmissionResult result;
    result.code = "PREFLIGHT_REQUIRED";
    result.detail = "A completed, verified image preflight is required";
    if (!isHex(jobId, 32) || !isHex(claimedHash, 64) ||
        (claimedKind != "android_userdata_image" &&
         claimedKind != "android_userdata_locked")) return result;
    try {
        const fs::path jobFile = forensics::PathManager::instance().getDataDir() /
                                 "evidence_preflight" / jobId / "job.json";
        std::error_code ec;
        if (!fs::is_regular_file(jobFile, ec) || ec ||
            fs::is_symlink(fs::symlink_status(jobFile, ec))) return result;
        std::ifstream input(jobFile);
        nlohmann::json job; input >> job;
        if (job.at("id") != jobId || job.at("status") != "completed" ||
            job.at("integrity_status") != "verified" || job.at("full_hash") != true ||
            job.at("sha256") != claimedHash || job.at("detected").at("kind") != claimedKind ||
            job.at("detected").at("adapter") != "filesystem-image" ||
            (job.at("image").at("ready") != true &&
             job.at("image").at("selected_partition").at("locked") != true)) return result;
        const auto source = fs::canonical(path);
        if (source != fs::canonical(job.at("source_path").get<std::string>()) ||
            fs::file_size(source) != job.at("source_size").get<std::uint64_t>() ||
            !sourceMatchesPreflightHash(source.string(), claimedHash)) {
            result.code = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            result.detail = "Image path, size, or SHA-256 changed after preflight";
            return result;
        }
        const auto& selected = job.at("image").at("selected_partition");
        const std::string filesystem = selected.at("kind").get<std::string>();
        if (filesystem != "ext4" && filesystem != "f2fs") return result;
        const std::string container = job.at("image").at("container").get<std::string>();
        if (container != "raw" && container != "e01") return result;
        result.accepted = true;
        result.code.clear(); result.detail.clear();
        result.metadata = {{"preflight_job_id", jobId},
                           {"preflight_source_sha256", claimedHash},
                           {"preflight_detected_kind", claimedKind},
                           {"preflight_adapter", "filesystem-image"},
                           {"preflight_source_size", std::to_string(fs::file_size(source))},
                           {"preflight_partition_offset", std::to_string(selected.at("base").get<std::uint64_t>())},
                           {"preflight_partition_name", selected.value("name", std::string())},
                           {"preflight_filesystem", filesystem},
                           {"preflight_container", container},
                           {"preflight_locked", selected.at("locked").get<bool>() ? "true" : "false"},
                           {"preflight_encryption_state", selected.at("encryption").at("state").get<std::string>()}};
    } catch (const std::exception&) { return result; }
    return result;
}

AndroidPreflightAdmissionResult admitAndroidArchiveSource(
    const std::string& path, const std::string& adapter,
    const std::string& jobId, const std::string& claimedHash,
    const std::string& claimedKind, bool passwordSupplied) {
    AndroidPreflightAdmissionResult result;
    result.code = "PREFLIGHT_REQUIRED";
    result.detail = "A completed full-hash preflight is required for this Android container source";
    if (!isHex(jobId, 32) || !isHex(claimedHash, 64)) return result;
    const std::map<std::string, std::string> allowed{
        {"tar", "tar_container"}, {"seven-zip", "seven_zip_container"},
        {"android-backup", "android_backup"}};
    auto selected = allowed.find(adapter);
    if (selected == allowed.end()) return result;
    const bool unlockedAb = adapter == "android-backup" &&
        claimedKind == "android_backup_encrypted" && passwordSupplied;
    if (claimedKind != selected->second && !unlockedAb) return result;
    const fs::path jobFile = forensics::PathManager::instance().getDataDir() /
                             "evidence_preflight" / jobId / "job.json";
    std::error_code ec;
    if (!fs::is_regular_file(jobFile, ec) || ec || fs::is_symlink(fs::symlink_status(jobFile, ec))) return result;
    nlohmann::json job;
    try {
        std::ifstream in(jobFile);
        if (!in) return result;
        in >> job;
        const auto detected = job.at("detected");
        if (job.at("id").get<std::string>() != jobId ||
            job.at("status").get<std::string>() != "completed" ||
            job.at("integrity_status").get<std::string>() != "verified" ||
            !job.at("full_hash").get<bool>() ||
            detected.at("kind").get<std::string>() != claimedKind ||
            detected.at("adapter").get<std::string>() != adapter ||
            !job.at("archive").at("inspected").get<bool>() ||
            !job.at("archive").at("ready").get<bool>()) return result;
        if (unlockedAb && (!job.value("password_supplied", false) ||
                           job.at("archive").value("encryption_status", std::string()) != "unlocked"))
            return result;
        const std::string beforeHash = job.at("sha256").get<std::string>();
        if (beforeHash != claimedHash) {
            result.code = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            result.detail = "Claimed source hash differs from the completed preflight";
            return result;
        }
        const auto source = fs::canonical(path);
        if (source != fs::canonical(job.at("source_path").get<std::string>()) ||
            fs::file_size(source) != job.at("source_size").get<std::uint64_t>() ||
            !sourceMatchesPreflightHash(source.string(), beforeHash)) {
            result.code = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            result.detail = "Source path, size, or SHA-256 changed after preflight";
            return result;
        }
        result.accepted = true;
        result.code.clear();
        result.detail.clear();
        result.metadata = {{"preflight_job_id", jobId},
                           {"preflight_source_sha256", beforeHash},
                           {"preflight_detected_kind", claimedKind},
                           {"preflight_adapter", adapter},
                           {"preflight_source_size", std::to_string(fs::file_size(source))},
                           {"preflight_root_mapping", job.at("archive").value("root_mapping", std::string())}};
        return result;
    } catch (const std::exception&) {
        return result;
    }
}
