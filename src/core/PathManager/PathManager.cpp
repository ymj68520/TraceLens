#include "PathManager.h"
#include <iostream>
#include <unistd.h>

namespace forensics {

PathManager& PathManager::instance() {
    static PathManager inst;
    return inst;
}

void PathManager::initialize(const std::string& executablePath) {
    namespace fs = std::filesystem;

    try {
        // Resolve symlinks and get absolute path of the executable
        fs::path exePath;
        
        // Try /proc/self/exe first (Linux-specific, most reliable)
#ifdef __linux__
        if (fs::exists("/proc/self/exe")) {
            exePath = fs::canonical("/proc/self/exe");
        } else
#endif
        {
            exePath = fs::canonical(executablePath);
        }
        
        exeDir_ = exePath.parent_path();
    } catch (const fs::filesystem_error&) {
        // Fallback: use current directory
        exeDir_ = fs::current_path();
        std::cerr << "[PathManager] Warning: could not resolve executable path, "
                     "falling back to CWD: " << exeDir_ << std::endl;
    }

    // Default projectRoot_ to exeDir_ (overridden later if PROJECT_ROOT is set)
    projectRoot_ = exeDir_;
    initialized_ = true;
}

void PathManager::ensureDirectories() const {
    namespace fs = std::filesystem;
    fs::create_directories(getDataDir());
    fs::create_directories(getDataDir() / "tasks");
    fs::create_directories(getAuditDir());
    fs::create_directories(getLogsDir());
}

// --- root paths ---

std::filesystem::path PathManager::getExeDir() const {
    return exeDir_;
}

std::filesystem::path PathManager::getProjectRoot() const {
    return projectRoot_;
}

std::filesystem::path PathManager::getDataDir() const {
    const std::filesystem::path configured(dataDirName_);
    if (configured.is_absolute()) {
        return configured;
    }
    return projectRoot_ / configured;
}

// --- sub-directories ---

std::filesystem::path PathManager::getTaskDir(const std::string& taskId) const {
    return getDataDir() / "tasks" / taskId;
}

std::filesystem::path PathManager::getAuditDir() const {
    return getDataDir() / "audit";
}

std::filesystem::path PathManager::getLogsDir() const {
    return getDataDir() / "logs";
}

// --- specific file paths ---

std::filesystem::path PathManager::getTasksJsonPath() const {
    return getDataDir() / "tasks.json";
}

std::filesystem::path PathManager::getAuditDbPath() const {
    return getAuditDir() / "forensics_audit.db";
}

std::filesystem::path PathManager::getLogFilePath() const {
    return getLogsDir() / "forensics.log";
}

std::filesystem::path PathManager::getDebugLogPath() const {
    return getLogsDir() / "debug.log";
}

// --- per-task database paths ---

PathManager::TaskDbPaths PathManager::getTaskDbPaths(
        const std::string& taskId,
        const std::string& /*imageName*/) const {
    auto dir = getTaskDir(taskId);
    return {
        dir / "raw.db",
        dir / "events.db",
        dir / "files.db",
        dir / "android.db",
        dir / "oss.db",
        dir / "windows.db",
        dir / "linux.db"
    };
}

// --- configuration helpers ---

void PathManager::setDataDirName(const std::string& name) {
    if (!name.empty()) {
        dataDirName_ = name;
    }
}

void PathManager::setProjectRoot(const std::string& root) {
    if (!root.empty()) {
        projectRoot_ = root;
    }
}

// --- temporary directory ---

std::filesystem::path PathManager::getTempDir() const {
    return std::filesystem::temp_directory_path();
}

std::string PathManager::makeTempPath(const std::string& prefix,
                                       const std::string& suffix) const {
    static std::atomic<uint64_t> counter{0};
    auto tid = std::hash<std::thread::id>{}(std::this_thread::get_id());
    auto name = prefix + std::to_string(getpid()) + "_" +
                std::to_string(tid) + "_" +
                std::to_string(counter.fetch_add(1)) + suffix;
    return (getTempDir() / name).string();
}

} // namespace forensics
