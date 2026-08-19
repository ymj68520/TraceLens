/**
 * @file main.cpp
 * @brief Main entry point for the Forensics Analyzer application
 * Handles command-line argument parsing and routes to appropriate execution modes.
 */

#include <iostream>
#include <memory>

#ifdef _WIN32
#include <Windows.h>
#include <vector>
#endif

#include "PathManager/PathManager.h"
#include "ConfigManager/ConfigManager.h"
#include "AuditLog/AuditLog.h"
#include "CommandLineParser.h"
#include "AnalysisOrchestrator.h"

/**
 * @brief Convert UTF-8 strings to wide strings for Windows
 */
#ifdef _WIN32
std::vector<wchar_t> getWideArgs(int argc, char* argv[]) {
    int wideArgc = 0;
    wchar_t** wideArgv = CommandLineToArgvW(GetCommandLineW(), &wideArgc);
    std::vector<wchar_t> result;
    for (int i = 0; i < wideArgc; i++) {
        std::wstring arg = wideArgv[i];
        result.insert(result.end(), arg.begin(), arg.end());
        result.push_back(L'\0');
    }
    LocalFree(wideArgv);
    return result;
}
#endif

/**
 * @brief Application entry point
 *
 * Initializes system components and routes to the appropriate execution mode:
 * - HTTP Server mode
 * - Full-text search mode (index or search)
 * - File carving mode
 * - File extraction mode
 * - Analysis mode
 */
int main(int argc, char* argv[]) {
    using namespace forensics;

    // Initialize PathManager first (needed for config path resolution)
    PathManager::instance().initialize(argv[0]);

    // Load configuration from .env file
    ConfigManager::instance().load(".env");

    // Apply storage overrides before any singleton touches task paths.  This
    // keeps DATA_DIR/PROJECT_ROOT effective for isolated acceptance runs.
    auto& pathManager = PathManager::instance();
    const auto configuredProjectRoot = ConfigManager::instance().get("PROJECT_ROOT", "");
    if (!configuredProjectRoot.empty()) {
        pathManager.setProjectRoot(configuredProjectRoot);
    }
    pathManager.setDataDirName(ConfigManager::instance().get("DATA_DIR", "data"));
    pathManager.ensureDirectories();

    // Initialize AuditLog if configured (singleton with config)
    AuditLogConfig auditConfig;
    auditConfig.db_path = ConfigManager::instance().get("AUDIT_LOG_DB", "forensics_audit.db");
    auditConfig.cache_size = static_cast<size_t>(ConfigManager::instance().getInt("AUDIT_LOG_CACHE_SIZE", 100));
    auditConfig.enable_wal = ConfigManager::instance().getBool("AUDIT_LOG_WAL", true);
    // Get singleton instance with config
    AuditLog::instance(auditConfig);

    // Parse command-line arguments
#ifdef _WIN32
    auto wideArgs = getWideArgs(argc, argv);
    // On Windows, we would need wide string parsing
    // For now, use regular parsing
#endif
    auto cmdArgs = CommandLineParser::parse(argc, argv);

    if (!cmdArgs.parse_error.empty()) {
        std::cerr << "Error: " << cmdArgs.parse_error << std::endl;
        return 2;
    }

    // Handle special flags
    if (cmdArgs.show_help) {
        CommandLineParser::printUsage(argv[0]);
        return 0;
    }

    if (cmdArgs.show_version) {
        std::cout << "Forensic Image Analyzer v1.0" << std::endl;
        std::cout << "Using The Sleuth Kit 4.14.0" << std::endl;
        return 0;
    }

    // Route to appropriate execution mode
    if (cmdArgs.http_port > 0) {
        return AnalysisOrchestrator::runHTTPServer(cmdArgs.http_port);
    }

    if (cmdArgs.index_mode || cmdArgs.search_mode) {
        return AnalysisOrchestrator::runFullTextSearch(cmdArgs);
    }

    if (cmdArgs.carve) {
        return AnalysisOrchestrator::runFileCarving(cmdArgs);
    }

    if (cmdArgs.extract_all || cmdArgs.extract_by_name || cmdArgs.extract_by_extension) {
        return AnalysisOrchestrator::runExtraction(cmdArgs);
    }

    if (cmdArgs.analyze_dlls_only) {
        return AnalysisOrchestrator::runDLLAnalysis(cmdArgs);
    }

    // Default: analysis mode
    return AnalysisOrchestrator::runAnalysis(cmdArgs);
}

#ifdef _WIN32
/**
 * @brief Windows wide-character entry point
 */
int wmain(int argc, wchar_t* argv[]) {
    // Convert wide strings to UTF-8
    std::vector<std::string> utf8Args;
    for (int i = 0; i < argc; i++) {
        int size = WideCharToMultiByte(CP_UTF8, 0, argv[i], -1, nullptr, 0, nullptr, nullptr);
        std::string arg(size - 1, 0);
        WideCharToMultiByte(CP_UTF8, 0, argv[i], -1, &arg[0], size, nullptr, nullptr);
        utf8Args.push_back(arg);
    }

    // Convert to char* array for main()
    std::vector<char*> charArgs;
    for (auto& arg : utf8Args) {
        charArgs.push_back(const_cast<char*>(arg.c_str()));
    }

    return main(argc, charArgs.data());
}
#endif
