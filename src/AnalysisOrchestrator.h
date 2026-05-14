#pragma once

#include "CommandLineParser.h"
#include <string>

namespace forensics {

/**
 * @brief Orchestrates forensic analysis workflows
 */
class AnalysisOrchestrator {
public:
    static int runAnalysis(const CommandLineArgs& args);
    static int runExtraction(const CommandLineArgs& args);
    static int runFullTextSearch(const CommandLineArgs& args);
    static int runFileCarving(const CommandLineArgs& args);
    static int runHTTPServer(int port);
    static int runDLLAnalysis(const CommandLineArgs& args);
    
private:
    static std::string getBaseName(const std::string& path);
    static std::string getDatabaseDir(const CommandLineArgs& args);
};

} // namespace forensics
