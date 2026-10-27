#pragma once
#include <string>
#include <vector>
#include <cstdint>
#include <optional>

enum class PrefetchVersion : uint32_t { VERSION_17=17, VERSION_23=23, VERSION_26=26,
    VERSION_30=30, VERSION_31=31, UNKNOWN=0 };

namespace PrefetchHelpers {
PrefetchVersion detectVersion(const char* header);
int64_t filetimeToUnixTime(uint64_t value);
uint16_t readUInt16LE(const char* data);
uint32_t readUInt32LE(const char* data);
uint64_t readUInt64LE(const char* data);
std::string extractExecutableNameFromFilename(const std::string& filename);
std::string extractHashFromFilename(const std::string& filename);
bool isValidPrefetchFile(const std::string& filepath);
}

class PrefetchParser {
public:
    explicit PrefetchParser(const std::string& filepath) : filepath_(filepath) {}
    bool parse();
    static std::string libraryVersion();
    PrefetchVersion getVersion() const { return version_; }
    uint32_t getRunCount() const { return runCount_; }
    int64_t getLastRunTime() const { return lastRunTime_.value_or(0); }
    bool hasLastRunTime() const { return lastRunTime_.has_value(); }
    int64_t getCreationTime() const { return 0; } // Not stored in the Prefetch payload.
    std::string getExecutableName() const { return executableName_; }
    std::string getExecutablePath() const { return {}; } // Never infer a path from the name.
    std::string getPrefetchHash() const { return prefetchHash_; }
    std::vector<int64_t> getAllRunTimes() const { return allRunTimes_; }
    std::vector<uint64_t> getRawRunTimes() const { return rawRunTimes_; }
    std::vector<std::string> getReferencedFiles() const { return referencedFiles_; }
    std::vector<std::string> getReferencedDirectories() const { return {}; }
    std::string getLastError() const { return lastError_; }
    std::string getStatus() const { return status_; }
    std::string getParserVersion() const { return parserVersion_; }
    bool isValid() const { return valid_; }
private:
    std::string filepath_, lastError_, status_="error", parserVersion_="unavailable";
    bool valid_=false;
    PrefetchVersion version_=PrefetchVersion::UNKNOWN;
    uint32_t runCount_=0;
    std::optional<int64_t> lastRunTime_;
    std::string executableName_, prefetchHash_;
    std::vector<int64_t> allRunTimes_;
    std::vector<uint64_t> rawRunTimes_;
    std::vector<std::string> referencedFiles_;
};
