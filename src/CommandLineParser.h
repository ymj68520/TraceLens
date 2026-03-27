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
    XFSMode xfs_mode = XFSMode::Auto;
    int http_port = 0;
    bool extract_all = false;
    bool extract_by_extension = false;
    bool extract_by_name = false;
    bool extract_deleted = false;
    bool overwrite = false;
    bool android_analyze = false;
    bool windows_analyze = false;
    bool linux_analyze = false;
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
