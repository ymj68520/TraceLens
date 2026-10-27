// Smart 选文件单独测试台：只执行 LLMAnalysisService::selectImportantFiles，
// 不进入逐文件分析阶段。用于在大镜像文件库上验证"LLM 挑重要文件"是否
// 仍出现只返回个位数可用路径的回退。
// 用法: smart_select_test <files_db> [budget]
#include "HTTPServer/LLMAnalysisService.h"
#include "ConfigManager/ConfigManager.h"
#include <algorithm>
#include <chrono>
#include <iostream>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: smart_select_test <files_db> [budget]\n";
        return 2;
    }
    const std::string dbPath = argv[1];
    const size_t budget = argc > 2 ? static_cast<size_t>(std::stoul(argv[2])) : 1000;

    auto& config = forensics::ConfigManager::instance();
    if (!config.isLoaded() && !config.load(".env")) {
        std::cerr << "FAILED_TO_LOAD_ENV\n";
        return 2;
    }
    std::cout << "model=" << config.getTextModel()
              << " candidate_files=" << config.getLLMSmartCandidateFiles() << "\n";

    forensics::LLMAnalysisService service;
    const auto started = std::chrono::steady_clock::now();
    const auto selected = service.selectImportantFiles(dbPath, budget);
    const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                             std::chrono::steady_clock::now() - started).count();

    std::cout << "SELECTION_RESULT selected=" << selected.size()
              << " budget=" << budget << " elapsed_s=" << elapsed << "\n";
    const size_t shown = std::min<size_t>(selected.size(), 25);
    for (size_t i = 0; i < shown; ++i) {
        std::cout << "  [" << i << "] " << selected[i] << "\n";
    }
    // 与管线一致的可靠性线（LLMAnalysisService.cpp：少于预算 1/4 即回退启发式）。
    const bool okay = selected.size() * 4 >= budget;
    std::cout << (okay ? "SELECTION_OK" : "SELECTION_UNRELIABLE") << "\n";
    return okay ? 0 : 1;
}
