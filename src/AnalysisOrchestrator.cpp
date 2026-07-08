#include "AnalysisOrchestrator.h"
#include "ImageAnalyzer/ImageAnalyzer.h"
#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "FileFilter/FileFilter.h"
#include "HTTPServer/HTTPserver.h"
#include "AndroidAnalyzer/AndroidAnalyzer.h"
#include "WindowsFilesAnalyzer/WindowsFilesAnalyzer.h"
#include "LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"
#include "MemoryAnalyzer/MemoryAnalyzer.h"
#include "DLLAnalyzer/Core/DLLAnalyzer.h"
#include "FullTextSearch/FullTextSearch.h"
#include "FullTextSearch/TextExtractor.h"
#include "FileCarving/FileCarver.h"
#include "report/ReportGenerator.h"
#include "LLMIntegration/MarkitdownProxy.h"
#include <iostream>
#include <filesystem>
#include <memory>

namespace forensics {

namespace fs = std::filesystem;

std::string AnalysisOrchestrator::getBaseName(const std::string& path) {
    return fs::path(path).stem().string();
}

std::string AnalysisOrchestrator::getDatabaseDir(const CommandLineArgs& args) {
    if (args.db_dir.empty()) return "";
    // Strip trailing slashes so prefix + name never produces a double slash
    // (e.g. --db-dir ./out/ -> "./out" not "./out/"). Double slashes confuse
    // some downstream HTTP path handlers (Python Path normalization).
    std::string dir = args.db_dir;
    while (!dir.empty() && dir.back() == '/') {
        dir.pop_back();
    }
    return dir + "/";
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

    // Android logical extraction (directory or zip) does not need — and cannot
    // use — the TSK disk-image pipeline. Route it to a dedicated path that
    // runs only the Android analyzer against the data source directly.
    if (args.android_analyze &&
        (args.android_source == "dir" || args.android_source == "zip")) {
        return runAndroidLogicalAnalysis(args);
    }

    // Memory (RAM) image analysis also bypasses the TSK disk-image pipeline:
    // a raw RAM dump is not a filesystem image. Route to a dedicated path that
    // runs Volatility3 and writes <baseName>_memory.db only.
    if (args.memory_analyze) {
        return runMemoryAnalysis(args);
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
        std::cout << "[1/4] Analyzing image..." << std::endl;
        auto analyzer = std::make_unique<ImageAnalyzer>(args.image_path);
        analyzer->setXFSMode(args.xfs_mode);

        if (!analyzer->analyze() || !analyzer->extractToDatabase(rawDbPath)) {
            std::cerr << "Error: Failed to analyze image" << std::endl;
            return 1;
        }
        std::cout << "✓ Raw database: " << rawDbPath << "\n" << std::endl;

        // Step 2: Apply file filter (if profile specified)
        // The filtered database is used by all downstream processors
        std::string effectiveRawDb = rawDbPath;

        if (!args.filter_profile.empty()) {
            std::cout << "[2/4] Applying file filter: " << args.filter_profile << "..." << std::endl;
            std::string filteredDbPath = prefix + baseName + "_filtered.db";

            try {
                FileFilter filter;
                auto stats = filter.applyFilterByName(rawDbPath, filteredDbPath, args.filter_profile);

                if (stats.included_files > 0) {
                    effectiveRawDb = filteredDbPath;
                    std::cout << "✓ Filtered database: " << filteredDbPath
                              << " (" << stats.included_files << "/" << stats.total_files
                              << " files)\n" << std::endl;
                } else {
                    std::cerr << "Warning: Filter excluded all files. Using unfiltered data." << std::endl;
                }
            } catch (const std::exception& e) {
                std::cerr << "Warning: Filter failed: " << e.what() << std::endl;
                std::cerr << "Continuing with unfiltered data." << std::endl;
            }
        } else {
            std::cout << "[2/4] File filter: skipped (no profile specified)\n" << std::endl;
        }

        // Step 3: Classify files with scene-aware context
        std::cout << "[3/4] Classifying files..." << std::endl;
        auto classifier = std::make_unique<FileClassifier>(effectiveRawDb, fileDbPath);

        // Determine scene type from analysis flags
        SceneType sceneType = SceneType::NONE;
        if (args.android_analyze) sceneType = SceneType::ANDROID;
        else if (args.windows_analyze) sceneType = SceneType::WINDOWS;
        else if (args.linux_analyze) sceneType = SceneType::LINUX;

        if (sceneType != SceneType::NONE) {
            classifier->setSceneType(sceneType);
            std::cout << "  Scene type: "
                      << (sceneType == SceneType::ANDROID ? "Android" :
                          sceneType == SceneType::WINDOWS ? "Windows" :
                          sceneType == SceneType::LINUX ? "Linux" : "None")
                      << std::endl;
        }

        if (!classifier->classifyAndExtract()) {
            std::cerr << "Error: Failed to classify files" << std::endl;
            return 1;
        }
        std::cout << "✓ File database: " << fileDbPath << "\n" << std::endl;

        // Release classifier's database lock before platform analyzers write to files.db
        classifier.reset();

        // Step 4: Scene-specific analysis (writes artifacts into files.db)
        if (args.android_analyze) {
            std::cout << "[Android] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(effectiveRawDb);
            if (!dbMgr->initialize()) {
                std::cerr << "Error: Failed to initialize DatabaseManager for Android analysis" << std::endl;
            } else {
                auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(args.image_path, dbMgr.get());
                if (!args.wechat_password.empty()) {
                    androidAnalyzer->setWeChatPassword(args.wechat_password);
                }
                // Write Android artifacts into files.db for unified scene database
                androidAnalyzer->setOutputDatabasePath(fileDbPath);
                if (androidAnalyzer->initialize()) {
                    androidAnalyzer->analyzeAndroidData();
                    std::cout << "✓ Android analysis complete\n" << std::endl;
                }
            }
        }

        if (args.windows_analyze) {
            std::cout << "[Windows] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(effectiveRawDb);
            if (!dbMgr->initialize()) {
                std::cerr << "Error: Failed to initialize DatabaseManager for Windows analysis" << std::endl;
            } else {
                auto winAnalyzer = std::make_unique<WindowsFilesAnalyzer>(args.image_path, dbMgr.get());
                // Write Windows artifacts into files.db for unified scene database
                winAnalyzer->setOutputDatabasePath(fileDbPath);
                winAnalyzer->setSkipAI(args.skip_ai);
                if (winAnalyzer->initialize()) {
                    winAnalyzer->analyzeWindowsData();
                    std::cout << "✓ Windows analysis complete\n" << std::endl;
                }
            }
        }

        if (args.linux_analyze) {
            std::cout << "[Linux] Analyzing..." << std::endl;
            auto dbMgr = std::make_unique<DatabaseManager>(effectiveRawDb);
            if (!dbMgr->initialize()) {
                std::cerr << "Error: Failed to initialize DatabaseManager for Linux analysis" << std::endl;
            } else {
                auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(args.image_path, dbMgr.get());
                // Write Linux artifacts into files.db for unified scene database
                linuxAnalyzer->setOutputDatabasePath(fileDbPath);
                linuxAnalyzer->setSkipAI(args.skip_ai);
                if (linuxAnalyzer->initialize()) {
                    linuxAnalyzer->analyzeLinuxData();
                    std::cout << "✓ Linux analysis complete\n" << std::endl;
                }
            }
        }

        // Step 5: Generate timeline (uses effective raw db)
        std::cout << "[4/4] Generating timeline..." << std::endl;
        auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
        if (eventExtractor->extractEvents()) {
            // Import scene artifacts from files.db (where platform analyzers wrote)
            if (args.android_analyze && fs::exists(fileDbPath))
                eventExtractor->importAndroidArtifacts(fileDbPath);
            if (args.windows_analyze && fs::exists(fileDbPath))
                eventExtractor->importWindowsArtifacts(fileDbPath);
            if (args.linux_analyze && fs::exists(fileDbPath))
                eventExtractor->importLinuxArtifacts(fileDbPath);
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
            // Windows artifacts are now in files.db (unified scene database)
            // 注意：Windows DB 只读访问，不会导致写锁竞争
            std::unique_ptr<WindowsAnalysisDatabase> windowsDb;
            if (args.windows_analyze) {
                if (fs::exists(fileDbPath)) {
                    std::cout << "Linking Windows forensic database for DLL correlation: " << fileDbPath << std::endl;
                    // 创建 Windows DB 实例用于只读查询
                    windowsDb = std::make_unique<WindowsAnalysisDatabase>(fileDbPath);
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

        // Step 6 (optional): Generate human-readable Markdown report
        if (args.generate_report) {
            std::string reportPath = args.report_path.empty()
                ? prefix + baseName + "_report.md"
                : args.report_path;
            ReportGenerator gen(fileDbPath, eventDbPath);
            if (gen.writeMarkdown(args.image_path, reportPath)) {
                std::cout << "✓ Report: " << reportPath << std::endl;
            } else {
                std::cerr << "Warning: Failed to generate report" << std::endl;
            }
            std::cout << std::endl;
        }

        // Step 7 (optional): Dump extracted files as text via Python extractors.
        // Converts every file in the image to a human-readable .md, mirroring the
        // directory structure. Requires python_service running.
        //
        // Unlike the platform analyzers (which only extract system files they
        // recognize), this step extracts ALL regular files from the image via
        // FileExtractor, so that ordinary documents (pdf/jpg/zip/docx/...) are
        // also converted — not just /etc/passwd-style system artifacts.
        if (args.dump_text) {
            std::string allExtractDir = prefix + baseName + "_extracted_files";
            std::string textDir = prefix + baseName + "_extracted_text";

            auto& markitdown = forensics::llm::MarkitdownProxy::instance();
            if (!markitdown.isServiceAvailable()) {
                std::cerr << "Warning: --dump-text requires python_service running. "
                          << "Start it with: ./scripts/start_python_service.sh"
                          << std::endl;
            } else {
                // Extract ALL regular files from the raw DB into allExtractDir.
                // Re-extract to guarantee completeness: the platform analyzers only
                // pull the subset they parse (system files), but --dump-text should
                // cover ordinary documents too. extractFile() skips files that are
                // already present with matching size, so re-extraction is cheap if
                // the analyzers already extracted some.
                std::cout << "Extracting all files for text dump..." << std::endl;
                {
                    FileExtractor allExtractor(args.image_path, effectiveRawDb);
                    if (allExtractor.initialize()) {
                        int n = allExtractor.extractAll(allExtractDir);
                        std::cout << "  Extracted " << n << " files to "
                                  << allExtractDir << std::endl;
                    } else {
                        std::cerr << "Warning: Failed to initialize extractor for --dump-text"
                                  << std::endl;
                    }
                }

                if (!fs::exists(allExtractDir) || fs::is_empty(allExtractDir)) {
                    std::cerr << "Warning: --dump-text found no extractable files in "
                              << args.image_path << std::endl;
                } else {
                    // Convert to absolute paths before sending to python_service.
                    // The Python process may have a different CWD than this C++
                    // process, so relative paths like ./build/output/... would
                    // fail with HTTP 400 "Input directory not found".
                    std::string absExtractDir = fs::absolute(allExtractDir).string();
                    std::string absTextDir = fs::absolute(textDir).string();

                    std::cout << "Dumping extracted files as text..." << std::endl;
                    auto result = markitdown.batchConvertToMarkdown(absExtractDir, absTextDir);
                    if (result.ok) {
                        std::cout << "✓ Text dump: " << result.converted << "/"
                                  << result.total << " files converted"
                                  << " (" << result.skipped << " skipped, "
                                  << result.failed << " failed) -> "
                                  << textDir << std::endl;
                    } else {
                        std::cerr << "Warning: Text dump failed: " << result.error << std::endl;
                    }
                }
            }
            std::cout << std::endl;
        }

        std::cout << "=== Analysis Complete ===" << std::endl;
        std::cout << "Databases: " << rawDbPath << ", " << eventDbPath << ", " << fileDbPath << std::endl;

    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}

int AnalysisOrchestrator::runAndroidLogicalAnalysis(const CommandLineArgs& args) {
    std::cout << "=== Android Logical Extraction Analyzer ===" << std::endl;
    std::cout << "Source: " << args.image_path << std::endl;
    std::cout << "Mode:   " << args.android_source
              << " (no TSK / no _raw.db)" << std::endl;

    if (!args.android_analyze) {
        std::cerr << "Error: --android-analyze is required for logical mode" << std::endl;
        return 1;
    }

    std::string baseName = getBaseName(args.image_path);
    std::string prefix = getDatabaseDir(args);
    if (!prefix.empty()) fs::create_directories(args.db_dir);

    // Android artifacts are written into <baseName>_files.db, mirroring the
    // integrated-scene convention used by the TSK pipeline.
    std::string fileDbPath = prefix + baseName + "_files.db";

    try {
        auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(args.image_path, nullptr);
        // Select the non-TSK backend before initialize().
        androidAnalyzer->setSourceMode(
            args.android_source == "zip" ? AndroidSourceMode::Zip
                                         : AndroidSourceMode::LogicalDir);
        if (!args.wechat_password.empty()) {
            androidAnalyzer->setWeChatPassword(args.wechat_password);
        }
        androidAnalyzer->setOutputDatabasePath(fileDbPath);

        std::cout << "[Android] Analyzing logical extraction..." << std::endl;
        if (!androidAnalyzer->initialize()) {
            std::cerr << "Error: Failed to initialize Android analyzer" << std::endl;
            return 1;
        }
        androidAnalyzer->analyzeAndroidData();
        std::cout << "✓ Android analysis complete" << std::endl;
        std::cout << "✓ Artifact database: " << fileDbPath << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "=== Analysis Complete ===" << std::endl;
    return 0;
}

int AnalysisOrchestrator::runMemoryAnalysis(const CommandLineArgs& args) {
    std::cout << "=== Memory Forensics Analyzer ===" << std::endl;
    std::cout << "Source: " << args.image_path << std::endl;
    std::cout << "Mode:   LiME/raw RAM image (no TSK / no _raw.db)" << std::endl;

    std::string baseName = getBaseName(args.image_path);
    std::string prefix = getDatabaseDir(args);
    if (!prefix.empty()) fs::create_directories(args.db_dir);

    std::string memDbPath = prefix + baseName + "_memory.db";

    try {
        auto analyzer = std::make_unique<MemoryAnalyzer>(args.image_path);
        analyzer->setOutputDatabasePath(memDbPath);
        std::cout << "[Memory] Initializing..." << std::endl;
        if (!analyzer->initialize()) {
            std::cerr << "Error: Failed to initialize memory analyzer" << std::endl;
            return 1;
        }
        analyzer->analyzeMemoryData();
        std::cout << "✓ Memory analysis complete" << std::endl;
        std::cout << "✓ Database: " << memDbPath << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }
    std::cout << "=== Analysis Complete ===" << std::endl;
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
