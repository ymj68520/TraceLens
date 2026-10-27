#pragma once

#include "IFileExtractor.h"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <functional>
#include <map>
#include <string>
#include <vector>

// OPPO / Android logical extraction produced by 雷电手机快取 (ThunderForensic).
//
// The evidence is a single plain ustar container whose members carry the
// parsed artifacts as JSON documents (ThunderForensic.json manifest,
// PhoneData/*.json artifacts, LogData/*.log system logs, plus the sdcard
// file payloads). Member names double as image-relative paths, and the tar
// may use obsolescent base-64 numeric fields with no trailing zero blocks,
// so indexing goes through libarchive rather than a hand-rolled reader.
//
// `root` may be either the tar file itself or the ThunderForensic project
// directory (in which case the container is resolved under
// filesystem/1/tar/).
class OppoBackupExtractor final : public IFileExtractor {
public:
    struct Entry {
        std::string path;  // tar member name, e.g. "PhoneData/wifi.json"
        std::uint64_t offset = 0;
        std::uint64_t size = 0;
        std::int64_t modified = 0;
    };
    explicit OppoBackupExtractor(std::string root);
    /// True for a ThunderForensic tar file or a project directory holding one.
    static bool recognizes(const std::string& path);
    bool initialize() override;
    bool extractFileByPath(const std::string& path, const std::string& output) override;
    std::vector<std::string> findPathsByFilename(const std::string& filename,
                                                 std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;
    const std::map<std::string, Entry>& entries() const { return entries_; }
    const nlohmann::json& manifest() const { return manifest_; }
    const std::filesystem::path& containerPath() const { return container_; }
    const std::string& error() const { return error_; }
    void setProgress(std::function<void(std::size_t)> progress,
                     std::function<bool()> cancelled = {});
    static std::string sha256(const std::filesystem::path& path);
    /// Read one member fully into memory (bounded); returns false when absent
    /// or larger than maxBytes.
    bool readMemberBytes(const std::string& path, std::string& out,
                         std::uint64_t maxBytes = 64ULL << 20);

private:
    std::filesystem::path root_;
    std::filesystem::path container_;
    std::uint64_t containerSize_ = 0;
    std::int64_t containerTime_ = 0;
    std::map<std::string, Entry> entries_;
    std::map<std::string, AndroidSourceProvenance> used_;
    nlohmann::json manifest_;
    std::string error_;
    std::function<void(std::size_t)> progress_;
    std::function<bool()> cancelled_;

    bool indexTar(const std::filesystem::path& tarPath);
    bool loadManifest();
    void recordProvenance(const Entry& entry, const std::string& memberSha256);
};

/// True when the tar member window of `path` carries the ThunderForensic
/// markers (manifest + PhoneData members). Bounded header-only scan.
bool oppoTarLooksLikeThunderForensic(const std::filesystem::path& path);
