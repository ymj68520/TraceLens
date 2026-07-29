// TarIndex.h
#pragma once
#include <string>
#include <cstdint>
#include <unordered_map>
#include <vector>
#include <cstdio>

struct TarEntry {
    uint64_t dataOffset;   // absolute byte offset in the underlying file
    uint64_t size;
};
class TarIndex {
public:
    ~TarIndex();
    TarIndex() = default;
    TarIndex(const TarIndex&) = delete;
    TarIndex& operator=(const TarIndex&) = delete;
    TarIndex(TarIndex&&) = delete;
    TarIndex& operator=(TarIndex&&) = delete;
    // Index a tar payload located at [payloadOffset, end-of-file) of `bakPath`.
    // If inflate=true, the payload is zlib-deflated and is inflated into a temp
    // file first (offsets then refer to the temp file).
    bool build(const std::string& bakPath, uint64_t payloadOffset, bool inflate);
    // Look up an entry by its tar member name (e.g. "apps/com.foo/db/x.db").
    bool find(const std::string& memberName, TarEntry& out) const;
    // Read entry bytes into outPath.
    bool readEntry(const TarEntry& e, const std::string& outPath) const;
    const std::unordered_map<std::string, TarEntry>& entries() const { return entries_; }
    const std::string& dataFile() const { return dataFile_; }
private:
    std::unordered_map<std::string, TarEntry> entries_;
    std::string dataFile_;   // bakPath, or the temp inflated file
    bool ownsTemp_ = false;
};
