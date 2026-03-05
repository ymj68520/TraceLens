/**
 * @file main.cpp
 * @brief Main entry point for the Forensics Analyzer application
 * Handles command-line argument parsing and initializes analysis modes.
 */

#include <iostream>
#include <string>
#include <filesystem>
#include <memory>
#include <map>
#include <vector>

#ifdef _WIN32
#include <Windows.h>
#endif

#include "ImageAnalyzer/ImageAnalyzer.h"
#include "DatabaseManager/EventExtractor/EventExtractor.h"
#include "DatabaseManager/FileClassifier/FileClassifier.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "HTTPServer/HTTPserver.h"
#include "AndroidAnalyzer/AndroidAnalyzer.h"
#include "WindowsFilesAnalyzer/WindowsFilesAnalyzer.h"
#include "LinuxFilesAnalyzer/LinuxFilesAnalyzer.h"
#include "FullTextSearch/FullTextSearch.h"
#include "FullTextSearch/TextExtractor.h"
#include "FileCarving/FileCarver.h"
#include "PathManager/PathManager.h"
#include "LLMIntegration/ConfigManager.h"
#include "AuditLog/AuditLog.h"


namespace fs = std::filesystem;

struct CommandLineArgs {
	std::string imagePath;
	std::string databasePath;
	std::string extractFile;
	std::string extractExt;
	std::string outputDir = "extracted_files";
	std::string dbOutputDir = "";
	XFSMode xfsMode = XFSMode::Auto;
	bool extractAll = false;
	bool includeDeleted = false;
	bool extractMode = false;
	bool httpServer = false;
	int httpPort = 8080;
	bool androidAnalyze = false;
	bool windowsAnalyze = false;
	bool linuxAnalyze = false;
	// Full Text Search options
	std::string indexDir;
	bool searchMode = false;
	std::string searchQuery;
	
	// File Carving options
	bool carveMode = false;
    std::string carveOutputDir = "carved_files";
    // Metadata Recovery options
    bool recoverDeletedMode = false;
    std::string recoverOutputDir = "recovered_files";
};

void printUsage(const char* programName) {
	std::cout << "Forensic Image Analyzer with File Extraction\n\n";
	std::cout << "Usage:\n";
	std::cout << "  Analysis mode:\n";
	std::cout << "    " << programName << " <image_path> [options]\n\n";
	std::cout << "  Extraction mode:\n";
	std::cout << "    " << programName << " --database <db_path> [extraction options]\n\n";
	std::cout << "Analysis options:\n";
	std::cout << "  --xfs-mode <mode>           XFS parsing mode for XFS filesystems:\n";
	std::cout << "                              - auto: Auto-detect (default)\n";
	std::cout << "                                Linux: native mount (full support, requires sudo)\n";
	std::cout << "                                Windows: pure parser (limited support)\n";
	std::cout << "                              - native: Force Linux native mount (Linux only)\n";
	std::cout << "                              - pure: Force pure XFS parser (cross-platform)\n";
	std::cout << "  --db-dir <path>             Directory to store generated databases (default: current directory)\n\n";
	std::cout << "Extraction options:\n";
	std::cout << "  --extract-file <pattern>    Extract files by name (supports wildcards: *, ?)\n";
	std::cout << "                              Example: --extract-file \"vmlinuz*\"\n";
	std::cout << "  --extract-ext <extensions>  Extract files by extension (comma-separated)\n";
	std::cout << "                              Example: --extract-ext \".log,.conf\"\n";
	std::cout << "  --extract-all               Extract all files\n";
	std::cout << "  --output-dir <path>         Output directory (default: extracted_files)\n";
	std::cout << "  --include-deleted           Include deleted files in extraction\n\n";
	std::cout << "HTTP Server options:\n";
	std::cout << "  --http-server [port]        Start HTTP server (default port 8080)\n\n";
	std::cout << "Android Analysis options:\n";
	std::cout << "  --android-analyze           Analyze Android application data (SMS, contacts, etc.)\n\n";
	std::cout << "Windows Analysis options:\n";
	std::cout << "  --windows-analyze           Analyze Windows artifacts (Registry, Event Logs, etc.)\n\n";
	std::cout << "Linux Analysis options:\n";
	std::cout << "  --linux-analyze             Analyze Linux artifacts (logs, user data, etc.)\n\n";
	std::cout << "  --linux-analyze             Analyze Linux artifacts (logs, user data, etc.)\n\n";
	std::cout << "Full-Text Search options:\n";
	std::cout << "  --index <dir>               Index all text files in directory\n";
	std::cout << "  --search <query>            Search indexed database (requires --index or uses default)\n\n";
	std::cout << "File Carving options:\n";
	std::cout << "  --carve                     Scan and recover deleted files from unallocated space\n";
	std::cout << "  --carve-out <dir>           Output directory for carved files (default: carved_files)\n\n";
	std::cout << "Examples:\n";
	std::cout << "  # Analyze image (auto-detect XFS mode)\n";
	std::cout << "  " << programName << " image.dd\n\n";
	std::cout << "  # Analyze XFS image with native mount (Linux, requires sudo)\n";
	std::cout << "  sudo " << programName << " Server.dd --xfs-mode native\n\n";
	std::cout << "  # Analyze XFS image with pure parser (Windows or Linux)\n";
	std::cout << "  " << programName << " Server.dd --xfs-mode pure\n\n";
	std::cout << "  # Extract kernel files\n";
	std::cout << "  " << programName << " --database image_raw.db --extract-file \"vmlinuz*\" --output-dir kernels\n\n";
	std::cout << "  # Extract log and config files\n";
	std::cout << "  " << programName << " --database Server_raw.db --extract-ext \".log,.conf\" --output-dir configs\n\n";
	std::cout << "  # Extract all files\n";
	std::cout << "  " << programName << " --database image_raw.db --extract-all\n";
}

CommandLineArgs parseArgs(int argc, char* argv[]) {
	CommandLineArgs args;

	for (int i = 1; i < argc; i++) {
		std::string arg = argv[i];

		if (arg == "--database" && i + 1 < argc) {
			args.databasePath = argv[++i];
			args.extractMode = true;
		} else if (arg == "--extract-file" && i + 1 < argc) {
			args.extractFile = argv[++i];
		} else if (arg == "--extract-ext" && i + 1 < argc) {
			args.extractExt = argv[++i];
		} else if (arg == "--extract-all") {
			args.extractAll = true;
		} else if (arg == "--output-dir" && i + 1 < argc) {
			args.outputDir = argv[++i];
		} else if (arg == "--include-deleted") {
			args.includeDeleted = true;
		} else if (arg == "--db-dir" && i + 1 < argc) {
			args.dbOutputDir = argv[++i];
		} else if (arg == "--xfs-mode" && i + 1 < argc) {
			std::string mode = argv[++i];
			if (mode == "auto") {
				args.xfsMode = XFSMode::Auto;
			} else if (mode == "native") {
				args.xfsMode = XFSMode::Native;
			} else if (mode == "pure") {
				args.xfsMode = XFSMode::Pure;
			} else {
				std::cerr << "Error: Invalid XFS mode '" << mode << "'" << std::endl;
				std::cerr << "Valid options: auto, native, pure" << std::endl;
			}
		} else if (arg == "--http-server") {
			args.httpServer = true;
			if (i + 1 < argc && argv[i + 1][0] != '-') {
				args.httpPort = std::stoi(argv[++i]);
			}
		} else if (arg == "--android-analyze") {
			args.androidAnalyze = true;
		} else if (arg == "--windows-analyze") {
			args.windowsAnalyze = true;
		} else if (arg == "--linux-analyze") {
			args.linuxAnalyze = true;
		} else if (arg == "--index" && i + 1 < argc) {
			args.indexDir = argv[++i];
		} else if (arg == "--search" && i + 1 < argc) {
			args.searchMode = true;
			// Join remaining args as query if multiple words provided without quotes?
			// For simplicity, assume quoted query for now.
			args.searchQuery = argv[++i];
		} else if (arg == "--carve") {
			args.carveMode = true;
		} else if (arg == "--carve-out" && i + 1 < argc) {
			args.carveOutputDir = argv[++i];
		} else if (arg == "--recover-deleted") {
			args.recoverDeletedMode = true;
			if (i + 1 < argc && argv[i + 1][0] != '-') {
				 args.recoverOutputDir = argv[++i];
			}
		} else if (arg[0] != '-') {
			// Assume it's image path if no leading dash
			args.imagePath = arg;
		}
	}

	return args;
}

std::string getBaseName(const std::string& path) {
	fs::path p(path);
	return p.stem().string();
}

#ifdef _WIN32
// Windows version with wide character support for Unicode paths
int wmain(int argc, wchar_t* wargv[]) {
	// Convert wide args to UTF-8
	std::vector<std::string> args;
	std::vector<char*> argv;

	for (int i = 0; i < argc; i++) {
		int size = WideCharToMultiByte(CP_UTF8, 0, wargv[i], -1, nullptr, 0, nullptr, nullptr);
		std::string arg(size - 1, 0);
		WideCharToMultiByte(CP_UTF8, 0, wargv[i], -1, &arg[0], size, nullptr, nullptr);
		args.push_back(arg);
	}

	for (auto& arg : args) {
		argv.push_back(&arg[0]);
	}
#else
// Linux/Unix version - UTF-8 is default
int main(int argc, char* argv[]) {
#endif

	// Parse command line arguments
	if (argc < 2) {
#ifdef _WIN32
		printUsage(argv.data()[0]);
#else
		printUsage(argv[0]);
#endif
		return 1;
	}

#ifdef _WIN32
	CommandLineArgs cmdArgs = parseArgs(argc, argv.data());
#else
	CommandLineArgs cmdArgs = parseArgs(argc, argv);
#endif

	// Initialize PathManager with executable path
	forensics::PathManager::instance().initialize(argv[0]);

	if (cmdArgs.httpServer) {
		std::cout << "Starting HTTP Server on port " << cmdArgs.httpPort << std::endl;

		// Apply .env settings to PathManager (PROJECT_ROOT, DATA_DIR)
		auto& configMgr = forensics::llm::ConfigManager::instance();
		if (configMgr.load(".env")) {
			auto& pm = forensics::PathManager::instance();
			std::string projectRoot = configMgr.get("PROJECT_ROOT", "");
			std::string dataDir = configMgr.get("DATA_DIR", "data");
			pm.setProjectRoot(projectRoot);
			pm.setDataDirName(dataDir);
			pm.ensureDirectories();
		} else {
			// Even without .env, ensure directories with defaults
			forensics::PathManager::instance().ensureDirectories();
		}

		// Initialize AuditLog with PathManager-derived path
		AuditLogConfig auditConfig;
		auditConfig.db_path = forensics::PathManager::instance().getAuditDbPath().string();
		AuditLog::instance(auditConfig);

		asio::io_context ioc;
		forensics::HTTPServer server(ioc);
		server.run(cmdArgs.httpPort);
		return 0;
	}

	// ========== FULL-TEXT SEARCH MODE ==========
	if (!cmdArgs.indexDir.empty() || cmdArgs.searchMode) {
		std::string indexDbPath = "search_index_xapian";
		if (!cmdArgs.dbOutputDir.empty()) {
			fs::create_directories(cmdArgs.dbOutputDir);
			indexDbPath = cmdArgs.dbOutputDir + "/" + indexDbPath;
		}

		if (!cmdArgs.indexDir.empty()) {
			std::cout << "=== Indexing Directory ===" << std::endl;
			std::cout << "Source: " << cmdArgs.indexDir << std::endl;
			std::cout << "Index DB: " << indexDbPath << std::endl;
			
			if (!fs::exists(cmdArgs.indexDir)) {
				std::cerr << "Error: Directory not found: " << cmdArgs.indexDir << std::endl;
				return 1;
			}

			try {
				forensics::XapianIndexer indexer(indexDbPath);
				
				int count = 0;
				for (const auto& entry : fs::recursive_directory_iterator(cmdArgs.indexDir)) {
					if (entry.is_regular_file()) {
						std::string path = entry.path().string();
						std::string content = forensics::TextExtractor::extract(path);
						
						if (!content.empty()) {
							indexer.addDocument(path, content);
							count++;
							if (count % 100 == 0) std::cout << "Indexed " << count << " files..." << std::endl;
						}
					}
				}
				indexer.commit();
				std::cout << "Indexing complete. Total files: " << count << std::endl;
			} catch (const std::exception& e) {
				std::cerr << "Indexing Error: " << e.what() << std::endl;
				return 1;
			}
		}

		if (cmdArgs.searchMode) {
			std::cout << "\n=== Searching ===" << std::endl;
			std::cout << "Query: " << cmdArgs.searchQuery << std::endl;
			std::cout << "Index DB: " << indexDbPath << std::endl;

			try {
				forensics::XapianSearcher searcher(indexDbPath);
				auto results = searcher.search(cmdArgs.searchQuery);
				
				std::cout << "Found " << results.size() << " results (showing top 10):" << std::endl;
				for (const auto& res : results) {
					std::cout << "[" << static_cast<int>(res.score) << "%] " << res.path << std::endl;
				}
			} catch (const std::exception& e) {
				std::cerr << "Search Error: " << e.what() << std::endl;
				return 1;
			}
		}

		return 0;
	}

	// ========== FILE CARVING MODE ==========
	if (cmdArgs.carveMode) {
		std::cout << "=== File Carving Mode ===" << std::endl;
		if (cmdArgs.imagePath.empty()) {
			std::cerr << "Error: Image path is required for carving." << std::endl;
			return 1;
		}

		FileCarver carver;
		// Default offset 0, ideally we should allow --offset
		// Assuming partition offset might be detected or passed via future args.
		
		int recovered = carver.carve(cmdArgs.imagePath, cmdArgs.carveOutputDir);
		std::cout << "Carving finished. recovered " << recovered << " files to " << cmdArgs.carveOutputDir << std::endl;
		return 0;
	}

    // Metadata Recovery
    if (cmdArgs.recoverDeletedMode) {
        std::cout << "\n=== Starting Metadata Recovery ===" << std::endl;
        
        // Use raw db path convention
        std::string baseName = getBaseName(cmdArgs.imagePath);
		std::string outPrefix = "";
		if (!cmdArgs.dbOutputDir.empty()) {
			outPrefix = cmdArgs.dbOutputDir + "/";
		}
		std::string rawDbPath = outPrefix + baseName + "_raw.db";

        // Check if DB exists, if not, warn user they should run analysis first
        if (!fs::exists(rawDbPath)) {
            std::cout << "Warning: Analysis database " << rawDbPath << " not found." << std::endl;
            std::cout << "Running analysis first..." << std::endl;
            // Fallthrough to analysis mode? 
            // Better to instantiate ImageAnalyzer and run analysis here if needed, 
            // OR just error out for now to keep it simple, OR proceed with analysis flow but add recovery step.
            // Let's rely on the user running analysis, or we just proceed to analysis mode?
            // Actually, if we are in this block, we assume we want to do recovery.
            // Let's modify the flow: If recoverDeletedMode is ON, we do the recovery AFTER analysis (if analysis happens)
            // or we try to open existing DB.
        }

        // Logic: If DB exists, use it. If not, we might need to run analysis. 
        // But for simplicity, let's assume we run analysis if we fall through.
        // So, let's put this Check inside the "Analysis Mode" block or make it a separate step at the end of Analysis Mode.
        // Actually, the main structure is:
        // if (extractMode) { ... } else { Analysis Mode ... }
        // We should add Recovery as a step in Analysis Mode, or a standalone mode that *uses* Analysis results.
        
        // Let's put it at the END of Analysis Mode loop (around line 533), 
        // OR here if we want to run it standalone.
        // If we put it here, we duplicate DB path logic.
        // Let's put it inside the "Analysis Mode" block (lines 403+), as Step 7.
    } 

	// Determine mode: extraction or analysis
	if (cmdArgs.extractMode) {
		// ========== EXTRACTION MODE ==========
		std::cout << "=== File Extraction Mode ===" << std::endl;

		// Validate arguments
		if (cmdArgs.databasePath.empty()) {
			std::cerr << "Error: --database is required for extraction mode" << std::endl;
			printUsage(argv[0]);
			return 1;
		}

		// If raw database is specified, use files database instead
		std::string dbPath = cmdArgs.databasePath;
		if (dbPath.length() > 7 && dbPath.substr(dbPath.length() - 7) == "_raw.db") {
			dbPath = dbPath.substr(0, dbPath.length() - 7) + "_files.db";
			std::cout << "Note: Using classified files database: " << dbPath << std::endl;
		}

		if (!fs::exists(dbPath)) {
			std::cerr << "Error: Database file not found: " << dbPath << std::endl;
			return 1;
		}

		// Determine image path from database name
		std::string imagePath;
		std::string dbName = fs::path(dbPath).stem().string();
		// Remove database type suffixes if present
		if (dbName.length() > 6 && dbName.substr(dbName.length() - 6) == "_files") {
			dbName = dbName.substr(0, dbName.length() - 6);
		} else if (dbName.length() > 7 && dbName.substr(dbName.length() - 7) == "_events") {
			dbName = dbName.substr(0, dbName.length() - 7);
		} else if (dbName.length() > 4 && dbName.substr(dbName.length() - 4) == "_raw") {
			dbName = dbName.substr(0, dbName.length() - 4);
		}

		// Try common extensions
		std::vector<std::string> extensions = {".dd", ".DD", ".001", ".e01", ".E01", ".raw", ".RAW"};
		for (const auto& ext : extensions) {
			std::string testPath = dbName + ext;
			if (fs::exists(testPath)) {
				imagePath = testPath;
				break;
			}
		}

		if (imagePath.empty()) {
			std::cerr << "Error: Cannot find image file (tried: " << dbName << ".dd, etc.)" << std::endl;
			std::cerr << "Please ensure the image file is in the current directory." << std::endl;
			return 1;
		}

		std::cout << "Database: " << cmdArgs.databasePath << std::endl;
		std::cout << "Image: " << imagePath << std::endl;
		std::cout << "Output: " << cmdArgs.outputDir << std::endl;
		std::cout << std::endl;

		try {
			auto extractor = std::make_unique<FileExtractor>(imagePath, dbPath);

			if (!extractor->initialize()) {
				std::cerr << "Error: Failed to initialize file extractor" << std::endl;
				return 1;
			}

			int extracted = 0;

			// Perform extraction based on options
			if (!cmdArgs.extractFile.empty()) {
				std::cout << "Extracting files matching: " << cmdArgs.extractFile << std::endl;
				extracted = extractor->extractByName(cmdArgs.extractFile, cmdArgs.outputDir);
			} else if (!cmdArgs.extractExt.empty()) {
				std::cout << "Extracting files with extensions: " << cmdArgs.extractExt << std::endl;
				extracted = extractor->extractByExtension(cmdArgs.extractExt, cmdArgs.outputDir);
			} else if (cmdArgs.extractAll) {
				std::cout << "Extracting all files" << std::endl;
				extracted = extractor->extractAll(cmdArgs.outputDir, cmdArgs.includeDeleted);
			} else {
				std::cerr << "Error: No extraction option specified" << std::endl;
				std::cerr << "Use --extract-file, --extract-ext, or --extract-all" << std::endl;
				return 1;
			}

			std::cout << "\n=== Extraction Complete ===" << std::endl;
			std::cout << "Files extracted: " << extracted << std::endl;
			std::cout << "Output directory: " << cmdArgs.outputDir << std::endl;

		} catch (const std::exception& e) {
			std::cerr << "Fatal error: " << e.what() << std::endl;
			return 1;
		}

	} else {
		// ========== ANALYSIS MODE ==========
		if (cmdArgs.imagePath.empty()) {
			std::cerr << "Error: Image path required" << std::endl;
			printUsage(argv[0]);
			return 1;
		}

		std::string imagePath = cmdArgs.imagePath;

		// Check if image exists
		if (!fs::exists(imagePath)) {
			std::cerr << "Error: Image file not found: " << imagePath << std::endl;
			return 1;
		}

		std::cout << "=== Forensic Image Analyzer ===" << std::endl;
		std::cout << "Image: " << imagePath << std::endl;
		std::cout << "Using The Sleuth Kit 4.14.0" << std::endl;
		std::cout << std::endl;

		// Generate database names
		std::string baseName = getBaseName(imagePath);
		std::string outPrefix = "";
		if (!cmdArgs.dbOutputDir.empty()) {
			fs::create_directories(cmdArgs.dbOutputDir);
			outPrefix = cmdArgs.dbOutputDir + "/";
		}
		std::string rawDbPath = outPrefix + baseName + "_raw.db";
		std::string eventDbPath = outPrefix + baseName + "_events.db";
		std::string fileDbPath = outPrefix + baseName + "_files.db";

		try {
			// Step 1: Analyze image and create raw database
			std::cout << "[1/3] Analyzing image and extracting raw data..." << std::endl;
			auto analyzer = std::make_unique<ImageAnalyzer>(imagePath);

			// Set XFS mode based on user selection
			analyzer->setXFSMode(cmdArgs.xfsMode);

			if (!analyzer->analyze()) {
				std::cerr << "Error: Failed to analyze image" << std::endl;
				return 1;
			}

			if (!analyzer->extractToDatabase(rawDbPath)) {
				std::cerr << "Error: Failed to extract data to database" << std::endl;
				return 1;
			}
			std::cout << "✓ Raw database created: " << rawDbPath << std::endl;
			std::cout << std::endl;

			// Step 2: Classify files by type
			std::cout << "[2/3] Classifying files by type..." << std::endl;
			auto fileClassifier = std::make_unique<FileClassifier>(rawDbPath, fileDbPath);

			if (!fileClassifier->classifyAndExtract()) {
				std::cerr << "Error: Failed to classify files" << std::endl;
				return 1;
			}
			std::cout << "✓ File database created: " << fileDbPath << std::endl;
			std::cout << std::endl;

			// Step 4: Analyze Android data if requested
			if (cmdArgs.androidAnalyze) {
				std::cout << "[4/4] Analyzing Android application data..." << std::endl;
				auto dbManager = std::make_unique<DatabaseManager>(rawDbPath);
				auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(imagePath, dbManager.get());
				
				std::string androidDbPath = outPrefix + baseName + "_android.db";
				androidAnalyzer->setOutputDatabasePath(androidDbPath);

				if (!androidAnalyzer->initialize()) {
					std::cerr << "Error: Failed to initialize Android analyzer" << std::endl;
					return 1;
				}

				androidAnalyzer->analyzeAndroidData();
				std::cout << "✓ Android data analysis completed" << std::endl;
				std::cout << std::endl;
			}

			// Step 5: Analyze Windows data if requested
			if (cmdArgs.windowsAnalyze) {
				std::cout << "[5/6] Analyzing Windows artifacts..." << std::endl;
				auto dbManager = std::make_unique<DatabaseManager>(rawDbPath);
				auto windowsAnalyzer = std::make_unique<WindowsFilesAnalyzer>(imagePath, dbManager.get());

				std::string windowsDbPath = outPrefix + baseName + "_windows.db";
				windowsAnalyzer->setOutputDatabasePath(windowsDbPath);

				if (!windowsAnalyzer->initialize()) {
					std::cerr << "Error: Failed to initialize Windows analyzer" << std::endl;
					return 1;
				}

				windowsAnalyzer->analyzeWindowsData();
				std::cout << "✓ Windows artifacts analysis completed" << std::endl;
				std::cout << std::endl;
			}

			// Step 6: Analyze Linux data if requested
			std::string linuxDbPath = outPrefix + baseName + "_linux.db";
			if (cmdArgs.linuxAnalyze) {
				std::cout << "[Analyzing Linux artifacts...]" << std::endl;
				auto dbManager = std::make_unique<DatabaseManager>(rawDbPath);
				auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());

				linuxAnalyzer->setOutputDatabasePath(linuxDbPath);

				if (!linuxAnalyzer->initialize()) {
					std::cerr << "Error: Failed to initialize Linux analyzer" << std::endl;
					return 1;
				}

				linuxAnalyzer->analyzeLinuxData();
				std::cout << "✓ Linux artifacts analysis completed" << std::endl;
				std::cout << std::endl;
			}

            // Step 7: Super Timeline Generation (Event Extractor)
            std::cout << "[Generating Super Timeline...]" << std::endl;
            auto eventExtractor = std::make_unique<EventExtractor>(rawDbPath, eventDbPath);
            if (eventExtractor->extractEvents()) {
                // Import optional artifacts
                if (cmdArgs.windowsAnalyze && fs::exists(outPrefix + baseName + "_windows.db")) {
                    eventExtractor->importWindowsArtifacts(outPrefix + baseName + "_windows.db");
                }
                if (cmdArgs.linuxAnalyze && fs::exists(linuxDbPath)) {
                    eventExtractor->importLinuxArtifacts(linuxDbPath);
                }
                std::cout << "✓ Super Timeline created: " << eventDbPath << std::endl;
            } else {
                 std::cerr << "Error: Failed to generate timeline" << std::endl;
            }
            std::cout << std::endl;

            // Step 8: Metadata Recovery
            if (cmdArgs.recoverDeletedMode) {
                std::cout << "[7/7] Recovering deleted files (Metadata)..." << std::endl;
                FileExtractor extractor(imagePath, rawDbPath);
                if (extractor.initialize()) {
                    int count = extractor.extractDeleted(cmdArgs.recoverOutputDir);
                    std::cout << "✓ Metadata Verification/Recovery Complete. Recovered " << count << " files to " << cmdArgs.recoverOutputDir << std::endl;
                } else {
                     std::cerr << "Failed to initialize Metadata Recovery." << std::endl;
                }
                std::cout << std::endl;
            }

			// Summary
			std::cout << "=== Analysis Complete ===" << std::endl;
			std::cout << "Generated databases:" << std::endl;
			std::cout << "  1. " << rawDbPath << " (Raw TSK data)" << std::endl;
			std::cout << "  2. " << eventDbPath << " (Filesystem events)" << std::endl;
			std::cout << "  3. " << fileDbPath << " (Classified files)" << std::endl;
			std::cout << "\nTip: Use --database to extract files from the image" << std::endl;
		}
		catch (const std::exception& e) {
			std::cerr << "Fatal error: " << e.what() << std::endl;
			return 1;
		}
	}

	return 0;
}