#include "CommandLineParser.h"
#include <charconv>
#include <cctype>
#include <filesystem>
#include <iostream>
#include <limits>
#include <optional>

namespace forensics {

namespace fs = std::filesystem;

namespace {

std::optional<uint64_t> parseBinarySize(const std::string& text,
                                        std::string& error) {
    if (text.size() < 2) {
        error = "--dump-text-max-size expects a positive integer followed by K, M, G, or T";
        return std::nullopt;
    }

    const char unit = static_cast<char>(
        std::toupper(static_cast<unsigned char>(text.back())));
    uint64_t multiplier = 0;
    switch (unit) {
        case 'K': multiplier = 1024ULL; break;
        case 'M': multiplier = 1024ULL * 1024ULL; break;
        case 'G': multiplier = 1024ULL * 1024ULL * 1024ULL; break;
        case 'T': multiplier = 1024ULL * 1024ULL * 1024ULL * 1024ULL; break;
        default:
            error = "--dump-text-max-size unit must be one of K, M, G, or T";
            return std::nullopt;
    }

    const std::string digits = text.substr(0, text.size() - 1);
    if (digits.empty()) {
        error = "--dump-text-max-size requires a positive integer before the unit";
        return std::nullopt;
    }
    for (const unsigned char ch : digits) {
        if (!std::isdigit(ch)) {
            error = "--dump-text-max-size does not accept signs or decimals";
            return std::nullopt;
        }
    }

    uint64_t value = 0;
    const auto [end, ec] = std::from_chars(
        digits.data(), digits.data() + digits.size(), value);
    if (ec != std::errc{} || end != digits.data() + digits.size() || value == 0) {
        error = "--dump-text-max-size must contain a positive integer";
        return std::nullopt;
    }
    if (value > std::numeric_limits<uint64_t>::max() / multiplier) {
        error = "--dump-text-max-size exceeds the maximum supported byte count";
        return std::nullopt;
    }
    return value * multiplier;
}

} // namespace

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
    std::cout << "DLL Analysis:\n";
    std::cout << "  --analyze-dlls              Enable DLL analysis\n";
    std::cout << "  --analyze-dlls-only         DLL analysis only (skip other steps)\n";
    std::cout << "  --dll-db <path>             DLL database path (default: <image>_dll.db)\n";
    std::cout << "  --dll-threshold <score>     Threat score threshold (default: 30)\n";
    std::cout << "  --no-verify-signatures      Disable signature verification (faster)\n\n";
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
    std::cout << "  --android-source <mode>     Android data source: tsk (default, disk image),\n";
    std::cout << "                              dir (extracted data/ directory), or zip (Image.zip)\n";
    std::cout << "  --wechat-password <pass>    WeChat SQLCipher decryption password\n";
    std::cout << "  --windows-analyze           Analyze Windows artifacts\n";
    std::cout << "  --linux-analyze             Analyze Linux artifacts\n";
    std::cout << "  --no-ai                     Skip AI/LLM analysis (for offline/no-key environments)\n";
    std::cout << "  --report                    Generate human-readable Markdown report (no AI needed)\n";
    std::cout << "  --report-path <path>        Custom output path for the report\n";
    std::cout << "  --dump-text                 Convert extracted files to text via Python extractors\n";
    std::cout << "                              (requires python_service running; needs --linux/windows-analyze)\n";
    std::cout << "  --dump-text-max-size <SIZE> Limit dump originals + Markdown (e.g. 500M, 2G)\n";
    std::cout << "                              Binary K/M/G/T soft limit; implies --dump-text\n";
    std::cout << "  --memory-analyze            Analyze a RAM memory image (LiME/raw) via Volatility3\n";
    std::cout << "  --vol-symbols-dir <path>    ISF symbol dir for vol3 (else vol3 default search)\n\n";
    std::cout << "File Filter:\n";
    std::cout << "  --filter-profile <name>     Apply filter profile (e.g., telecom_fraud, virus_intrusion)\n";
    std::cout << "                              Profiles are loaded from config/filter_profiles/\n\n";
    std::cout << "Decryption (BitLocker / LUKS / VeraCrypt):\n";
    std::cout << "  --decrypt                   Auto-detect & decrypt encrypted partitions\n";
    std::cout << "  --key-dir <path>            Directory holding sibling .key files (default: image dir)\n";
    std::cout << "  --key-password-stdin        Read password from stdin (no echo when interactive)\n";
    std::cout << "  --key-password <pass>       Deprecated: password in argv (insecure; may be exposed)\n";
    std::cout << "  Password file convention: <imageBase>.part<N>.key (e.g. disk.part2.key)\n";
    std::cout << "                              or <imageBase>.key for whole-image encryption\n\n";
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
        } else if (arg == "--extract-deleted" || arg == "--include-deleted") {
            // Accept both spellings: printUsage documents "--include-deleted".
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
        } else if (arg == "--android-source" && i + 1 < argc) {
            args.android_source = argv[++i];
        } else if (arg == "--wechat-password" && i + 1 < argc) {
            args.wechat_password = argv[++i];
        } else if (arg == "--windows-analyze") {
            args.windows_analyze = true;
        } else if (arg == "--linux-analyze") {
            args.linux_analyze = true;
        } else if (arg == "--no-ai") {
            args.skip_ai = true;
        } else if (arg == "--report") {
            args.generate_report = true;
        } else if (arg == "--report-path" && i + 1 < argc) {
            args.report_path = argv[++i];
            args.generate_report = true;
        } else if (arg == "--dump-text") {
            args.dump_text = true;
        } else if (arg == "--dump-text-max-size") {
            if (i + 1 >= argc) {
                args.parse_error = "Missing value for --dump-text-max-size";
                return args;
            }
            std::string error;
            auto parsed = parseBinarySize(argv[++i], error);
            if (!parsed.has_value()) {
                args.parse_error = error;
                return args;
            }
            args.dump_text_max_bytes = *parsed;
            args.dump_text = true;
        } else if (arg == "--memory-analyze") {
            args.memory_analyze = true;
        } else if (arg == "--vol-symbols-dir" && i + 1 < argc) {
            args.vol_symbols_dir = argv[++i];
        } else if (arg == "--analyze-dlls") {
            args.analyze_dlls = true;
        } else if (arg == "--analyze-dlls-only") {
            args.analyze_dlls_only = true;
            args.analyze_dlls = true;
        } else if (arg == "--dll-db" && i + 1 < argc) {
            args.dll_db = argv[++i];
        } else if (arg == "--dll-threshold" && i + 1 < argc) {
            args.dll_threshold = std::stoi(argv[++i]);
        } else if (arg == "--no-verify-signatures") {
            args.verify_signatures = false;
        } else if (arg == "--index" && i + 1 < argc) {
            args.index_path = argv[++i];
            args.index_mode = true;
        } else if (arg == "--search" && i + 1 < argc) {
            args.search_keyword = argv[++i];
            args.search_mode = true;
        } else if (arg == "--filter-profile" && i + 1 < argc) {
            args.filter_profile = argv[++i];
        } else if (arg == "--decrypt") {
            args.enable_decryption = true;
        } else if (arg == "--key-dir" && i + 1 < argc) {
            args.key_file_dir = argv[++i];
        } else if (arg == "--key-password-stdin") {
            args.decrypt_password_stdin = true;
        } else if (arg == "--key-password" && i + 1 < argc) {
            args.decrypt_password = argv[++i];
            std::cerr << "Security warning: --key-password is deprecated because command-line "
                      << "arguments may be visible to other users. Use --key-password-stdin instead."
                      << std::endl;
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
