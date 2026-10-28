#pragma once

#include "IFileExtractor.h"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <functional>
#include <map>
#include <string>
#include <vector>

// Android logical extraction produced by 雷电手机快取 (ThunderForensic).
//
// The evidence is a plain ustar container whose members carry the parsed
// artifacts of any supported Android brand (OPPO, vivo, OnePlus, ...):
// ThunderForensic.json manifest, PhoneData/*.json artifacts, LogData/*.log
// system logs, sdcard payloads and per-package data trees
// (<package>.tar/... or <package>.ab/...).
//
// Indexing does not go through libarchive: the writer emits a non-octal gid
// ("-6667000") and, in some samples, on the very first member. libarchive
// rejects such an archive before it can index anything. A bounded header walk
// accepts the quirk, runs 7-20x faster on large containers (memory mapping,
// no per-member decompression), and still understands GNU long names and PAX
// path/size records.
//
// `root` may be either the tar file itself or the ThunderForensic project
// directory (the container is resolved under filesystem/1/tar/).
class ThunderForensicBackupExtractor final : public IFileExtractor {
public:
    struct Entry {
        std::string path;  // tar member name, e.g. "PhoneData/wifi.json"
        std::uint64_t offset = 0;
        std::uint64_t size = 0;
        std::int64_t modified = 0;
    };
    explicit ThunderForensicBackupExtractor(std::string root);
    /// True for a ThunderForensic tar file or a project directory holding one.
    /// When `deviceBrand` is provided it receives the manifest brand/model.
    static bool recognizes(const std::string& path, std::string* deviceBrand = nullptr);
    bool initialize() override;
    bool extractFileByPath(const std::string& path, const std::string& output) override;
    std::vector<std::string> findPathsByFilename(const std::string& filename,
                                                 std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;
    const std::map<std::string, Entry>& entries() const { return entries_; }
    const nlohmann::json& manifest() const { return manifest_; }
    const std::filesystem::path& containerPath() const { return container_; }
    /// Absolute project directory when the source was a project folder; empty
    /// when the evidence was the tar file alone.
    const std::filesystem::path& projectRoot() const { return projectRoot_; }
    const std::string& error() const { return error_; }
    const std::string& deviceBrand() const { return deviceBrand_; }
    /// Empty when the container exceeds the full-hash size policy; see
    /// containerHashStatus().
    const std::string& containerSha256() const { return containerSha256_; }
    const std::string& containerHashStatus() const { return containerHashStatus_; }
    std::size_t duplicateMemberCount() const { return duplicateMembers_; }
    void setProgress(std::function<void(std::size_t)> progress,
                     std::function<bool()> cancelled = {});
    static std::string sha256(const std::filesystem::path& path,
                              const std::function<bool()>& cancelled = {});
    /// Read one member fully into memory (bounded); returns false when absent
    /// or larger than maxBytes.
    bool readMemberBytes(const std::string& path, std::string& out,
                         std::uint64_t maxBytes = 64ULL << 20);

private:
    std::filesystem::path root_;
    std::filesystem::path container_;
    std::filesystem::path projectRoot_;
    std::uint64_t containerSize_ = 0;
    std::int64_t containerTime_ = 0;
    std::map<std::string, Entry> entries_;
    std::map<std::string, AndroidSourceProvenance> used_;
    nlohmann::json manifest_;
    std::string deviceBrand_;
    std::string containerSha256_;
    std::string containerHashStatus_;
    std::size_t duplicateMembers_ = 0;
    std::string error_;
    std::function<void(std::size_t)> progress_;
    std::function<bool()> cancelled_;

    bool resolveContainer();
    bool indexTar(const std::filesystem::path& tarPath);
    bool loadManifest();
    static std::string sha256Bytes(const std::string& bytes);
    void recordProvenance(const Entry& entry, const std::string& memberSha256);
    void recordManifestProvenance(const Entry& entry, const std::string& memberSha256);
};

/// True when `path` is a ThunderForensic tar (optionally resolving a project
/// directory's filesystem/1/tar container). Bounded header-only scan.
bool thunderForensicTarLooksLike(const std::filesystem::path& path,
                                 std::string* deviceBrand = nullptr);
/// Canonical source id for ThunderForensic extractions.
inline constexpr const char* kThunderForensicSource = "thunder-backup";
/// Legacy OPPO-only source id; still accepted and normalized to the generic
/// adapter so existing tasks keep working.
inline constexpr const char* kLegacyOppoSource = "oppo-backup";
bool isThunderForensicSource(const std::string& source);
