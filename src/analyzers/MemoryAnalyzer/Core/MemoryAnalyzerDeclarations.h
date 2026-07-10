// MemoryAnalyzerDeclarations.h
#pragma once
#include <memory>
#include <string>
class MemoryAnalysisDatabase;
class Volatility3Runner;

// The kind of memory image being analyzed. Detected from the file magic:
// LiME dumps begin with the "EMiL" magic (little-endian 0x454d694c), Windows
// kernel/full dumps begin with "PAGEDU64". Used to select the vol3 plugin set
// and the matching parsers.
enum class MemImageType { UNKNOWN, LINUX_LIME, WINDOWS_DUMP };

class MemoryAnalyzer {
public:
    explicit MemoryAnalyzer(std::string memPath);
    ~MemoryAnalyzer();
    void setOutputDatabasePath(const std::string& p) { outputDbPath_ = p; }
    // Extra ISF symbol directory forwarded to vol3 via `-s` (Linux only).
    void setSymbolDir(const std::string& d) { symbolDir_ = d; }
    bool initialize();
    void analyzeMemoryData();
    // Detect the image type from the file magic. Reads only the first 64 bytes.
    static MemImageType detectImageType(const std::string& memPath);
private:
    std::string memPath_;
    std::string outputDbPath_;
    std::string symbolDir_;
    MemImageType imageType_ = MemImageType::UNKNOWN;
    std::unique_ptr<MemoryAnalysisDatabase> db_;
    std::unique_ptr<Volatility3Runner> runner_;
};
