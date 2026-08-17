#include "LLMScratch.h"

#include <filesystem>
#include <system_error>

namespace fs = std::filesystem;

namespace forensics {
namespace llm_scratch {

std::string dirForTask(const std::string& taskId) {
    const std::string segment = taskId.empty() ? "notask" : taskId;
    return (fs::temp_directory_path() / "forensics_llm_extract" / segment).string();
}

void cleanupTask(const std::string& taskId) {
    if (taskId.empty()) {
        return;
    }
    std::error_code ec;
    fs::remove_all(fs::path(dirForTask(taskId)), ec);
}

} // namespace llm_scratch
} // namespace forensics
