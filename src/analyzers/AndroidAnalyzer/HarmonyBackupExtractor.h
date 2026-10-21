#pragma once

#include "IFileExtractor.h"
#include <nlohmann/json.hpp>
#include <sqlite3.h>
#include <filesystem>
#include <functional>
#include <map>

// Already-decrypted HarmonyOS backup. Paths are scoped by bundle and appIndex;
// the numeric IDs exported to the common files table are logical IDs, not inodes.
class HarmonyBackupExtractor final : public IFileExtractor {
public:
    struct Entry {
        std::string path, bundle, originalPath, container;
        std::uint64_t offset = 0, size = 0;
        std::int64_t modified = 0, containerSize = 0, containerTime = 0;
        int appIndex = 0;
    };
    explicit HarmonyBackupExtractor(std::string root);
    static bool recognizes(const std::string& root);
    static std::string scopedPath(const std::string& bundle, int appIndex,
                                  const std::string& original);
    bool initialize() override;
    bool loadIndex(sqlite3* database);
    bool saveIndex(sqlite3* database) const;
    bool verifyIntegrity();
    bool extractFileByPath(const std::string&, const std::string&) override;
    std::vector<std::string> findPathsByFilename(const std::string&, std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;
    const std::map<std::string, Entry>& entries() const { return entries_; }
    const nlohmann::json& manifest() const { return manifest_; }
    const nlohmann::json& coverage() const { return coverage_; }
    const std::string& error() const { return error_; }
    void setProgress(std::function<void(std::size_t)> progress,
                     std::function<bool()> cancelled = {});
    static std::string sha256(const std::filesystem::path& path);

private:
    std::filesystem::path root_;
    std::map<std::string, Entry> entries_;
    std::map<std::string, AndroidSourceProvenance> used_;
    std::map<std::string, std::string> hashes_;
    nlohmann::json manifest_, coverage_ = nlohmann::json::array();
    std::string error_;
    std::function<void(std::size_t)> progress_;
    std::function<bool()> cancelled_;
    std::map<std::string, bool> ambiguous_;
    bool indexTar(const std::filesystem::path&, const std::string&, int);
    bool addEntry(Entry entry);
    bool safeFile(const std::filesystem::path&) const;
    void record(const std::string& path, const std::string& status, const std::string& detail);
};
