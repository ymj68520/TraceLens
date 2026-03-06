#pragma once
#ifndef PATH_MANAGER_H
#define PATH_MANAGER_H

#include <string>
#include <filesystem>

namespace forensics {

/**
 * @brief Centralized path management for the ForensicsProject.
 *
 * All runtime data files (databases, logs, audit, task state) are anchored
 * relative to the executable's directory, under a configurable `data/`
 * subdirectory.  This avoids CWD-dependence and keeps task artifacts isolated.
 *
 * Usage:
 *   PathManager::instance().initialize(argv[0]);
 *   PathManager::instance().ensureDirectories();
 *   auto dbPaths = PathManager::instance().getTaskDbPaths(taskId, imageName);
 */
class PathManager {
public:
    static PathManager& instance();

    // ---- initialisation ------------------------------------------------

    /**
     * @brief Must be called once at startup (before any path queries).
     * @param executablePath  argv[0] — used to derive the executable directory
     */
    void initialize(const std::string& executablePath);

    /**
     * @brief Call after initialize() to create the directory tree.
     *
     * Creates:  data/, data/tasks/, data/audit/, data/logs/
     */
    void ensureDirectories() const;

    bool isInitialized() const { return initialized_; }

    // ---- root paths ----------------------------------------------------

    /** Directory that contains the executable (absolute). */
    std::filesystem::path getExeDir() const;

    /** PROJECT_ROOT from .env, or exeDir if not set. */
    std::filesystem::path getProjectRoot() const;

    /** data/ directory (absolute). */
    std::filesystem::path getDataDir() const;

    // ---- sub-directories -----------------------------------------------

    /** data/tasks/<taskId>/ — created on demand by ensureTaskDir(). */
    std::filesystem::path getTaskDir(const std::string& taskId) const;

    /** data/audit/ */
    std::filesystem::path getAuditDir() const;

    /** data/logs/ */
    std::filesystem::path getLogsDir() const;

    // ---- specific file paths -------------------------------------------

    /** data/tasks.json */
    std::filesystem::path getTasksJsonPath() const;

    /** data/audit/forensics_audit.db */
    std::filesystem::path getAuditDbPath() const;

    /** data/logs/forensics.log */
    std::filesystem::path getLogFilePath() const;

    /** data/logs/debug.log */
    std::filesystem::path getDebugLogPath() const;

    // ---- per-task database paths ---------------------------------------

    struct TaskDbPaths {
        std::filesystem::path rawDb;
        std::filesystem::path eventsDb;
        std::filesystem::path filesDb;
        std::filesystem::path androidDb;
        std::filesystem::path ossDb;
        std::filesystem::path windowsDb;
        std::filesystem::path linuxDb;
    };

    /**
     * @brief Generate all database paths for a given task.
     *
     * The databases live in data/tasks/<taskId>/ and are named simply
     * raw.db, events.db, etc.
     *
     * @param taskId    UUID of the task
     * @param imageName (unused — kept for future reference; filenames are fixed)
     */
    TaskDbPaths getTaskDbPaths(const std::string& taskId,
                               const std::string& imageName = "") const;

    /**
     * @brief Ensure a specific task directory exists
     * @param taskId The task UUID
     */
    void ensureTaskDir(const std::string& taskId) const {
        auto taskDir = getTaskDir(taskId);
        std::filesystem::create_directories(taskDir);
    }

    /**
     * @brief Get the extraction output directory for a specific task
     * @param taskId The task UUID
     * @return Path like <exe_dir>/data/tasks/<taskId>/extracted_files/
     */
    std::filesystem::path getTaskExtractDir(const std::string& taskId) const {
        return getTaskDir(taskId) / "extracted_files";
    }

    // ---- configuration helpers -----------------------------------------

    /**
     * @brief Override the data directory name.
     * Called after loading .env if DATA_DIR is set.
     */
    void setDataDirName(const std::string& name);

    /**
     * @brief Set project root explicitly (from .env PROJECT_ROOT).
     */
    void setProjectRoot(const std::string& root);

    // Disable copy / move
    PathManager(const PathManager&) = delete;
    PathManager& operator=(const PathManager&) = delete;
    PathManager(PathManager&&) = delete;
    PathManager& operator=(PathManager&&) = delete;

private:
    PathManager() = default;

    bool initialized_ = false;
    std::filesystem::path exeDir_;
    std::filesystem::path projectRoot_;
    std::string dataDirName_ = "data";   // default, overridable via DATA_DIR
};

} // namespace forensics

#endif // PATH_MANAGER_H
