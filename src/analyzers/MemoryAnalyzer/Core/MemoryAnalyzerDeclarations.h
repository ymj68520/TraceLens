// MemoryAnalyzerDeclarations.h
#pragma once
#include <memory>
#include <string>
class MemoryAnalysisDatabase;
class Volatility3Runner;

class MemoryAnalyzer {
public:
    explicit MemoryAnalyzer(std::string memPath);
    ~MemoryAnalyzer();
    void setOutputDatabasePath(const std::string& p) { outputDbPath_ = p; }
    bool initialize();
    void analyzeMemoryData();
private:
    std::string memPath_;
    std::string outputDbPath_;
    std::unique_ptr<MemoryAnalysisDatabase> db_;
    std::unique_ptr<Volatility3Runner> runner_;
};
