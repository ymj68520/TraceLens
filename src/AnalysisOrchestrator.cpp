#include "AnalysisOrchestrator.h"
#include "ImageAnalyzer/ImageAnalyzer.h"
#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "HTTPServer/HTTPserver.h"
#include "AndroidAnalyzer/AndroidAnalyzer.h"
#include "WindowsFilesAnalyzer/WindowsFilesAnalyzer.h"
#include "LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"
#include "DLLAnalyzer/Core/DLLAnalyzer.h"
#include "FullTextSearch/FullTextSearch.h"
#include "FullTextSearch/TextExtractor.h"
#include "FileCarving/FileCarver.h"
#include <iostream>
#include <filesystem>
#include <memory>

namespace forensics {

namespace fs = std::filesystem;

std::string AnalysisOrchestrator::getBaseName(const std::string& path) {
    return fs::path(path).stem().string();
}

std::string AnalysisOrchestrator::getDatabaseDir(const CommandLineArgs& args) {
    return args.db_dir.empty() ? "" : args.db_dir + "/";
}

int AnalysisOrchestrator::runAnalysis(const CommandLineArgs& args) {
    if (args.image_path.empty()) {
        std::cerr << "Error: Image path required" << std::endl;
        return 1;
    }

    if (!fs::exists(args.image_path)) {
        std::cerr << "Error: Image file not found: " << args.image_path << std::endl;
        return 1;
    }

    std::cout << "=== Forensic Image Analyzer ===" << std::endl;
    std::cout << "Image: " << args.image_path << std::endl;
    std::cout << "Using The Sleuth Kit 4.14.0\n" << std::endl;

    std::string baseName = getBaseName(args.image_path);
    std::string prefix = getDatabaseDir(args);
    if (!prefix.empty()) fs::create_directories(args.db_dir);

    std::string rawDbPath = prefix + baseName + "_raw.db";
    std::string eventDbPath = prefix + baseName + "_events.db";
    std::string fileDbPath = prefix + baseName + "_files.db";

    try {
        // Step 1: Analyze image
        std::cout << "[1/3] Analyzing image..." << std::endl;
        auto analyzer = std::make_unique<ImageAnalyzer>(args.image_path);
        analyzer->setXFSMode(args.xfs_mode);

        if (!analyzer->analyze() || !analyzer->extractToDatabase(rawDbPath)) {
            std::cerr << "Error: Failed to analyze image" << std::endl;
            return 1;
        }
        std::cout << "✓ Raw database: " << rawDbPath << "\n" << std::endl;

        // Step 2: Classify files
        std::cout << "[2/3] Classifying files..." << std::endl;
        auto classifier = std::make_unique<FileClassifier>(rawDbPath, fileDbPath);
        if (!classifier->classifyAndExtract()) {
            std::cerr << "Error: Failed to classify files" << std::endl;
            return 1;
        }
        std::cout << "✓ File database: " << fileDbPath << "\n" << std::endl;

        // Step 3: Platform-specific analysis
        if (args.android_analyze) {
            std::cout << "[Android] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(rawDbPath);
            auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(args.image_path, dbMgr.get());
            androidAnalyzer->setOutputDatabasePath(prefix + baseName + "_android.db");
            if (androidAnalyzer->initialize()) {
                androidAnalyzer->analyzeAndroidData();
                std::cout << "✓ Android analysis complete\n" << std::endl;
            }
        }

        if (args.windows_analyze) {
            std::cout << "[Windows] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(rawDbPath);
            auto winAnalyzer = std::make_unique<WindowsFilesAnalyzer>(args.image_path, dbMgr.get());
            winAnalyzer->setOutputDatabasePath(prefix + baseName + "_windows.db");
            if (winAnalyzer->initialize()) {
                winAnalyzer->analyzeWindowsData();
                std::cout << "✓ Windows analysis complete\n" << std::endl;
            }
        }

        if (args.linux_analyze) {
            std::cout << "[Linux] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(rawDbPath);
            auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(args.image_path, dbMgr.get());
            linuxAnalyzer->setOutputDatabasePath(prefix + baseName + "_linux.db");
            if (linuxAnalyzer->initialize()) {
                linuxAnalyzer->analyzeLinuxData();
                std::cout << "✓ Linux analysis complete\n" << std::endl;
            }
        }

        // Step 4: Generate timeline
        std::cout << "[Timeline] Generating..." << std::endl;
        auto eventExtractor = std::make_unique<EventExtractor>(rawDbPath, eventDbPath);
        if (eventExtractor->extractEvents()) {
            if (args.android_analyze && fs::exists(prefix + baseName + "_android.db"))
                eventExtractor->importAndroidArtifacts(prefix + baseName + "_android.db");
            if (args.windows_analyze && fs::exists(prefix + baseName + "_windows.db"))
                eventExtractor->importWindowsArtifacts(prefix + baseName + "_windows.db");
            if (args.linux_analyze && fs::exists(prefix + baseName + "_linux.db"))
                eventExtractor->importLinuxArtifacts(prefix + baseName + "_linux.db");
            std::cout << "✓ Timeline: " << eventDbPath << "\n" << std::endl;
        }

        // Step 4: DLL analysis
        if (args.analyze_dlls) {
            std::cout << "[DLL] Analyzing..." << std::endl;
            std::string dllDbPath = args.dll_db.empty() ? prefix + baseName + "_dll.db" : args.dll_db;
            auto dllAnalyzer = std::make_unique<dll::DLLAnalyzer>(dllDbPath);
            dllAnalyzer->enableAnomalyDetection(true);
            dllAnalyzer->enableSignatureVerification(args.verify_signatures);

            // 关联 Windows 取证数据库（如果 Windows 分析已执行）
            // 注意：Windows DB 只读访问，不会导致写锁竞争
            std::unique_ptr<WindowsAnalysisDatabase> windowsDb;
            if (args.windows_analyze) {
                std::string windowsDbPath = prefix + baseName + "_windows.db";
                if (fs::exists(windowsDbPath)) {
                    std::cout << "Linking Windows forensic database for DLL correlation: " << windowsDbPath << std::endl;
                    // 创建 Windows DB 实例用于只读查询
                    windowsDb = std::make_unique<WindowsAnalysisDatabase>(windowsDbPath);
                    if (windowsDb->initialize()) {
                        dllAnalyzer->setWindowsDatabase(windowsDb.get());
                    } else {
                        std::cerr << "Warning: Failed to initialize Windows DB, skipping forensic correlation" << std::endl;
                        windowsDb.reset();
                    }
                }
            }

            if (dllAnalyzer->initialize()) {
                dllAnalyzer->analyze();
                auto stats = dllAnalyzer->getStats();
                std::cout << "✓ DLL analysis complete (" << stats.totalDLLsAnalyzed
                          << " analyzed, " << stats.suspiciousDLLs << " suspicious)\n" << std::endl;
            }

            // Windows DB 在作用域结束时自动释放（先于 DLL DB）
        }

        std::cout << "=== Analysis Complete ===" << std::endl;
        std::cout << "Databases: " << rawDbPath << ", " << eventDbPath << ", " << fileDbPath << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}

int AnalysisOrchestrator::runExtraction(const CommandLineArgs& args) {
    std::cout << "=== File Extraction Mode ===" << std::endl;

    if (args.database_path.empty()) {
        std::cerr << "Error: --database required" << std::endl;
        return 1;
    }

    std::string dbPath = args.database_path;
    if (dbPath.ends_with("_raw.db")) {
        dbPath = dbPath.substr(0, dbPath.length() - 7) + "_files.db";
        std::cout << "Using: " << dbPath << std::endl;
    }

    if (!fs::exists(dbPath)) {
        std::cerr << "Error: Database not found: " << dbPath << std::endl;
        return 1;
    }

    std::string imagePath;
    std::string dbName = fs::path(dbPath).stem().string();
    if (dbName.ends_with("_files")) dbName = dbName.substr(0, dbName.length() - 6);
    else if (dbName.ends_with("_events")) dbName = dbName.substr(0, dbName.length() - 7);
    else if (dbName.ends_with("_raw")) dbName = dbName.substr(0, dbName.length() - 4);

    for (const auto& ext : {".dd", ".DD", ".001", ".e01", ".E01", ".raw", ".RAW"}) {
        if (fs::exists(dbName + ext)) {
            imagePath = dbName + ext;
            break;
        }
    }

    if (imagePath.empty()) {
        std::cerr << "Error: Cannot find image file" << std::endl;
        return 1;
    }

    try {
        auto extractor = std::make_unique<FileExtractor>(imagePath, dbPath);
        if (!extractor->initialize()) {
            std::cerr << "Error: Failed to initialize extractor" << std::endl;
            return 1;
        }

        int extracted = 0;
        if (args.extract_by_name) {
            extracted = extractor->extractByName(args.extract_pattern, args.extract_output_dir);
        } else if (args.extract_by_extension) {
            extracted = extractor->extractByExtension(args.extract_pattern, args.extract_output_dir);
        } else if (args.extract_all) {
            extracted = extractor->extractAll(args.extract_output_dir, args.extract_deleted);
        } else {
            std::cerr << "Error: No extraction option specified" << std::endl;
            return 1;
        }

        std::cout << "\n=== Extraction Complete ===" << std::endl;
        std::cout << "Files extracted: " << extracted << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}

int AnalysisOrchestrator::runFullTextSearch(const CommandLineArgs& args) {
    std::string indexDbPath = "search_index_xapian";
    if (!args.db_dir.empty()) {
        fs::create_directories(args.db_dir);
        indexDbPath = args.db_dir + "/" + indexDbPath;
    }

    if (!args.index_path.empty()) {
        std::cout << "=== Indexing Directory ===" << std::endl;
        std::cout << "Source: " << args.index_path << std::endl;

        if (!fs::exists(args.index_path)) {
            std::cerr << "Error: Directory not found" << std::endl;
            return 1;
        }

        try {
            forensics::XapianIndexer indexer(indexDbPath);
            int count = 0;
            for (const auto& entry : fs::recursive_directory_iterator(args.index_path)) {
                if (entry.is_regular_file()) {
                    std::string content = forensics::TextExtractor::extract(entry.path().string());
                    if (!content.empty()) {
                        indexer.addDocument(entry.path().string(), content);
                        if (++count % 100 == 0) std::cout << "Indexed " << count << " files..." << std::endl;
                    }
                }
            }
            indexer.commit();
            std::cout << "Complete. Total: " << count << " files" << std::endl;
        } catch (const std::exception& e) {
            std::cerr << "Error: " << e.what() << std::endl;
            return 1;
        }
    }

    if (args.search_mode) {
        std::cout << "\n=== Searching ===" << std::endl;
        std::cout << "Query: " << args.search_keyword << std::endl;

        try {
            forensics::XapianSearcher searcher(indexDbPath);
            auto results = searcher.search(args.search_keyword);
            std::cout << "Found " << results.size() << " results (top 10):" << std::endl;
            for (const auto& res : results) {
                std::cout << "[" << static_cast<int>(res.score) << "%] " << res.path << std::endl;
            }
        } catch (const std::exception& e) {
            std::cerr << "Error: " << e.what() << std::endl;
            return 1;
        }
    }

    return 0;
}

int AnalysisOrchestrator::runFileCarving(const CommandLineArgs& args) {
    std::cout << "=== File Carving Mode ===" << std::endl;
    if (args.image_path.empty()) {
        std::cerr << "Error: Image path required" << std::endl;
        return 1;
    }

    FileCarver carver;
    int recovered = carver.carve(args.image_path, args.carve_output_dir);
    std::cout << "Carving finished. Recovered " << recovered << " files to " << args.carve_output_dir << std::endl;
    return 0;
}

int AnalysisOrchestrator::runHTTPServer(int port) {
    asio::io_context ioc;
    forensics::HTTPServer server(ioc);
    server.run(port);
    return 0;
}

int AnalysisOrchestrator::runDLLAnalysis(const CommandLineArgs& args) {
    if (args.image_path.empty() && args.dll_db.empty()) {
        std::cerr << "Error: Image path or --dll-db required for DLL analysis" << std::endl;
        return 1;
    }

    std::string dllDbPath = args.dll_db;
    if (dllDbPath.empty()) {
        // Use default based on image path
        std::string baseName = getBaseName(args.image_path);
        std::string prefix = getDatabaseDir(args);
        dllDbPath = prefix + baseName + "_dll.db";
    }

    std::cout << "=== DLL Analysis Mode ===" << std::endl;
    std::cout << "DLL Database: " << dllDbPath << std::endl;

    try {
        auto dllAnalyzer = std::make_unique<dll::DLLAnalyzer>(dllDbPath);
        dllAnalyzer->enableAnomalyDetection(true);
        dllAnalyzer->enableSignatureVerification(args.verify_signatures);

        if (!dllAnalyzer->initialize()) {
            std::cerr << "Error: Failed to initialize DLL analyzer" << std::endl;
            return 1;
        }

        dllAnalyzer->analyze();

        auto stats = dllAnalyzer->getStats();
        std::cout << "\nDLL Analysis Complete" << std::endl;
        std::cout << "Total analyzed: " << stats.totalDLLsAnalyzed << std::endl;
        std::cout << "Suspicious DLLs: " << stats.suspiciousDLLs << std::endl;
        std::cout << "Signed DLLs: " << stats.signedDLLs << std::endl;
        std::cout << "Unsigned DLLs: " << stats.unsignedDLLs << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}

} // namespace forensics
