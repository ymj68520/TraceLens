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

    /**
     * @brief Analyze a RAM memory image (LiME/raw) via Volatility3, bypassing
     *        the TSK disk-image pipeline. Produces <baseName>_memory.db only.
     *
     * Used when --memory-analyze is set. No _raw.db / events.db / files.db are
     * produced; memory artifacts (processes, network, bash history, boot info)
     * are written into <baseName>_memory.db.
     */
    static int runMemoryAnalysis(const CommandLineArgs& args);
    
private:
    static std::string getBaseName(const std::string& path);
    static std::string getDatabaseDir(const CommandLineArgs& args);

    /**
     * @brief Analyze an Android logical extraction (a `data/` directory or an
     *        Image.zip) directly, bypassing the TSK disk-image pipeline.
     *
     * Used when --android-source is `dir` or `zip`. No _raw.db is produced and
     * no filesystem timeline is generated; only Android artifacts are written
     * into <baseName>_files.db.
     */
    static int runAndroidLogicalAnalysis(const CommandLineArgs& args);
};

} // namespace forensics
