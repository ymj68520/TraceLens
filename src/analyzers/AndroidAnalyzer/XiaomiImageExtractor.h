#pragma once
#include "IndexedMobileSource.h"
#include <filesystem>

class XiaomiImageExtractor final : public IndexedMobileSource {
public:
    explicit XiaomiImageExtractor(std::string image);
    static bool recognizes(const std::string& image);
    bool initialize() override;
    bool loadIndex(sqlite3*) override;
    bool saveIndex(sqlite3*) const override;
    bool verifyIntegrity() override;
    bool extractFileByPath(const std::string&, const std::string&) override;
    bool readRange(const std::string&,std::uint64_t,std::size_t,std::string&,std::string&) override;
    std::vector<std::string> findPathsByFilename(const std::string&, std::size_t = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;
    const std::map<std::string, Entry>& entries() const override { return entries_; }
    const nlohmann::json& manifest() const override { return manifest_; }
    const nlohmann::json& coverage() const override { return coverage_; }
    const std::string& error() const override { return error_; }
    void setProgress(std::function<void(std::size_t)>, std::function<bool()> = {}) override;
private:
    std::filesystem::path image_;
    std::map<std::string, Entry> entries_;
    std::map<std::string, nlohmann::json> locations_;
    std::map<std::string, AndroidSourceProvenance> used_;
    nlohmann::json manifest_, coverage_ = nlohmann::json::array();
    std::string error_;
    std::int64_t sourceTime_ = 0;
    std::function<void(std::size_t)> progress_;
    std::function<bool()> cancelled_;
    bool add(const nlohmann::json&);
    bool sameSource() const;
    std::string sourceHash();
};
