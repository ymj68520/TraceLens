#include "CommandLineParser.h"
#include <iostream>
#include <filesystem>

namespace forensics {

namespace fs = std::filesystem;

void CommandLineParser::printUsage(const char* programName) {
    std::cout << "Forensic Image Analyzer with File Extraction\n\n";
    std::cout << "Usage:\n";
    std::cout << "  Analysis mode:\n";
    std::cout << "    " << programName << " <image_path> [options]\n\n";
    std::cout << "  Extraction mode:\n";
    std::cout << "    " << programName << " --database <db_path> [extraction options]\n\n";
    std::cout << "Analysis options:\n";
    std::cout << "  --xfs-mode <mode>           XFS parsing mode (auto/native/pure)\n";
    std::cout << "  --db-dir <path>             Directory to store databases\n\n";
    std::cout << "Extraction options:\n";
    std::cout << "  --extract-file <pattern>    Extract files by name (wildcards: *, ?)\n";
    std::cout << "  --extract-ext <extensions>  Extract by extension (comma-separated)\n";
    std::cout << "  --extract-all               Extract all files\n";
    std::cout << "  --output-dir <path>         Output directory\n";
    std::cout << "  --include-deleted           Include deleted files\n\n";
    std::cout << "HTTP Server options:\n";
    std::cout << "  --http-server [port]        Start HTTP server (default 8080)\n\n";
    std::cout << "Platform Analysis:\n";
    std::cout << "  --android-analyze           Analyze Android data\n";
    std::cout << "  --windows-analyze           Analyze Windows artifacts\n";
    std::cout << "  --linux-analyze             Analyze Linux artifacts\n\n";
    std::cout << "Full-Text Search:\n";
    std::cout << "  --index <dir>               Index text files\n";
    std::cout << "  --search <query>            Search indexed database\n\n";
    std::cout << "File Carving:\n";
    std::cout << "  --carve                     Recover deleted files\n";
    std::cout << "  --carve-out <dir>           Carving output directory\n";
}

CommandLineArgs CommandLineParser::parse(int argc, char* argv[]) {
    CommandLineArgs args;

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];

        if (arg == "--database" && i + 1 < argc) {
            args.database_path = argv[++i];
        } else if (arg == "--extract-file" && i + 1 < argc) {
            args.extract_pattern = argv[++i];
            args.extract_by_name = true;
        } else if (arg == "--extract-ext" && i + 1 < argc) {
            args.extract_pattern = argv[++i];
            args.extract_by_extension = true;
        } else if (arg == "--extract-all") {
            args.extract_all = true;
        } else if (arg == "--extract-deleted") {
            args.extract_deleted = true;
        } else if (arg == "--output-dir" && i + 1 < argc) {
            args.extract_output_dir = argv[++i];
        } else if (arg == "--db-dir" && i + 1 < argc) {
            args.db_dir = argv[++i];
        } else if (arg == "--overwrite") {
            args.overwrite = true;
        } else if (arg == "--xfs-mode" && i + 1 < argc) {
            std::string mode = argv[++i];
            if (mode == "auto") args.xfs_mode = XFSMode::Auto;
            else if (mode == "native") args.xfs_mode = XFSMode::Native;
            else if (mode == "pure") args.xfs_mode = XFSMode::Pure;
            else {
                std::cerr << "Error: Invalid XFS mode '" << mode << "'" << std::endl;
                std::cerr << "Valid options: auto, native, pure" << std::endl;
            }
        } else if (arg == "--http-server") {
            args.http_port = 8080;
            if (i + 1 < argc && argv[i + 1][0] != '-') {
                args.http_port = std::stoi(argv[++i]);
            }
        } else if (arg == "--android-analyze") {
            args.android_analyze = true;
        } else if (arg == "--windows-analyze") {
            args.windows_analyze = true;
        } else if (arg == "--linux-analyze") {
            args.linux_analyze = true;
        } else if (arg == "--index" && i + 1 < argc) {
            args.index_path = argv[++i];
            args.index_mode = true;
        } else if (arg == "--search" && i + 1 < argc) {
            args.search_keyword = argv[++i];
            args.search_mode = true;
        } else if (arg == "--carve") {
            args.carve = true;
        } else if (arg == "--carve-out" && i + 1 < argc) {
            args.carve_output_dir = argv[++i];
        } else if (arg == "--help" || arg == "-h") {
            args.show_help = true;
        } else if (arg == "--version" || arg == "-v") {
            args.show_version = true;
        } else if (arg[0] != '-') {
            args.image_path = arg;
        }
    }

    return args;
}

} // namespace forensics
