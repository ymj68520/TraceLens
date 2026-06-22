#pragma once

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
    bool analyze_dlls = false; // 启用DLL分析
    bool analyze_dlls_only = false; // 仅DLL分析
    bool verify_signatures = true; // 验证数字签名
    bool carve = false;
    bool show_help = false;
    bool show_version = false;
    bool index_mode = false;
    bool search_mode = false;
};

class CommandLineParser {
public:
    static void printUsage(const char* programName);
    static CommandLineArgs parse(int argc, char* argv[]);
};

} // namespace forensics
