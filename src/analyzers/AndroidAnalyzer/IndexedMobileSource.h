#pragma once
#include "IFileExtractor.h"
#include <nlohmann/json.hpp>
#include <sqlite3.h>
#include <functional>
#include <map>

// Shared contract for mobile evidence entering the ordinary files/events pipeline.
// Entry IDs belong to the exported source, not necessarily the original handset.
class IndexedMobileSource : public IFileExtractor {
public:
    struct Entry {
        std::string path, bundle, originalPath, container;
        std::uint64_t offset = 0, size = 0;
        std::int64_t modified = 0, containerSize = 0, containerTime = 0;
        int appIndex = 0;
    };
    virtual bool loadIndex(sqlite3*) = 0;
    virtual bool saveIndex(sqlite3*) const = 0;
    virtual bool verifyIntegrity() = 0;
    virtual bool readRange(const std::string&, std::uint64_t, std::size_t,
                           std::string&, std::string& error) { error="RANGE_READER_UNAVAILABLE";return false; }
    virtual const std::map<std::string, Entry>& entries() const = 0;
    virtual const nlohmann::json& manifest() const = 0;
    virtual const nlohmann::json& coverage() const = 0;
    virtual const std::string& error() const = 0;
    virtual void setProgress(std::function<void(std::size_t)>, std::function<bool()> = {}) = 0;
};
