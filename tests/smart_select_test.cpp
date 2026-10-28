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
#include <cstdlib>

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
    const auto& stats = service.lastSelectionStats();

    std::cout << "SELECTION_RESULT selected=" << selected.size()
              << " budget=" << budget << " elapsed_s=" << elapsed << "\n";
    // Provenance is the point of this bench: a 977-file model selection and a
    // 977-file heuristic fallback are indistinguishable by count alone, and the
    // silent-fallback regressions were exactly that kind of ambiguity.
    std::cout << "SELECTION_SOURCE source=" << stats.source
              << " candidates=" << stats.candidates
              << " listed=" << stats.listed
              << " reply_usable=" << stats.reply_usable << "\n";
    // SMART_SELECT_LIST_ALL=1 prints every selected path. Verifying that a
    // specific artefact was actually chosen needs the whole list: the 25-row
    // preview never included the Quasar controller on PC.E01, so a successful
    // run looked identical to one that had silently dropped it.
    const bool listAll = std::getenv("SMART_SELECT_LIST_ALL") != nullptr;
    const size_t shown = listAll ? selected.size()
                                 : std::min<size_t>(selected.size(), 25);
    for (size_t i = 0; i < shown; ++i) {
        std::cout << "  [" << i << "] " << selected[i] << "\n";
    }
    // The selector's own verdict, not a re-derived one. Judging `selected`
    // against `budget` repeated the bug inside the bench: at budget 4500 the
    // prompt could only list ~979 rows, and 977 correct picks printed
    // SELECTION_UNRELIABLE. Only the rejection/fallback paths are failures here;
    // "heuristic_fits" means the pool was smaller than the budget and needs no
    // model call at all.
    const bool okay = stats.source == "llm" || stats.source == "heuristic_fits";
    std::cout << (okay ? "SELECTION_OK" : "SELECTION_UNRELIABLE") << "\n";
    return okay ? 0 : 1;
}
