#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>
#include "ImageAnalyzer/ImageAnalyzer.h"

namespace forensics {

struct CommandLineArgs {
    std::string image_path;
    std::string database_path;
    std::string output_dir;
    std::string db_dir;
    std::string extract_pattern;
    std::string extract_output_dir = "extracted_files";
    std::string search_keyword;
    std::string index_path;
    std::string carve_output_dir = "carved_files";
    std::string dll_db; // DLL分析数据库路径
    std::string filter_profile; // File filter profile name (e.g., "telecom_fraud", "virus_intrusion")
    XFSMode xfs_mode = XFSMode::Auto;
    int http_port = 0;
    int dll_threshold = 30; // DLL威胁评分阈值
    bool extract_all = false;
    bool extract_by_extension = false;
    bool extract_by_name = false;
    bool extract_deleted = false;
    bool overwrite = false;
    bool android_analyze = false;
    std::string wechat_password;
    std::string android_source;  // "tsk" (default), "dir", or "zip"
    bool windows_analyze = false;
    bool linux_analyze = false;
    bool memory_analyze = false;
    std::string vol_symbols_dir;  // ISF symbol dir passed to vol3 via -s
    bool analyze_dlls = false; // 启用DLL分析
    bool analyze_dlls_only = false; // 仅DLL分析
    bool verify_signatures = true; // 验证数字签名
    bool carve = false;
    bool show_help = false;
    bool show_version = false;
    bool index_mode = false;
    bool search_mode = false;
    bool skip_ai = false;  // 跳过 AI/LLM 分析（现场无网/无 key 时使用）
    bool generate_report = false;  // 生成人类可读 Markdown 报告
    std::string report_path;  // 自定义报告路径（可选）
    bool dump_text = false;  // 导出提取文件的文本版本（需 python_service 运行）
    std::optional<uint64_t> dump_text_max_bytes;
    std::string parse_error;

    // Decryption options (encrypted partitions are auto-detected and unlocked
    // using a sibling .key file when --decrypt is given).
    bool enable_decryption = false;      // --decrypt
    std::string key_file_dir;            // --key-dir <dir>: override .key search dir
    std::string decrypt_password;        // --key-password <pass>: deprecated explicit password
    bool decrypt_password_stdin = false; // --key-password-stdin: read password without argv exposure
};

class CommandLineParser {
public:
    static void printUsage(const char* programName);
    static CommandLineArgs parse(int argc, char* argv[]);
};

} // namespace forensics
