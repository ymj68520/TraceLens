// FileClassifier.cpp
// Implementation of file classification and category extraction.
//
// This file holds construction, the classify pipeline, database setup,
// category determination, and path/filename helpers. Scene-type detection
// and per-OS scene rules live in FileClassifier_SceneRules.cpp.
// (Extension/filename-pattern initializers already live in
// FileClassifierMappings.cpp / FileClassifierPatterns.cpp.)

#include "FileClassifier.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include "AuditLog/AuditLog.h"
#include "EncryptionUtils.h"
#include "ConfigManager/ConfigManager.h"
#include <iostream>
#include <sstream>
#include <iomanip>
#include <sqlite3.h>
#include <algorithm>
#include <cctype>

FileClassifier::FileClassifier(const std::string& sourceDbPath,
	const std::string& fileDbPath)
	: sourceDbPath_(sourceDbPath), fileDbPath_(fileDbPath),
	sourceDb_(nullptr), fileDb_(nullptr) {
	initializeExtensionMap();
	initializePathPatterns();
	initializeFilenamePatterns();
	initializeExtendedExtensionMap();
}

FileClassifier::~FileClassifier() {
	closeDatabases();
}

bool FileClassifier::classifyAndExtract() {
	AuditLog::instance().log("SYSTEM", "CLASSIFICATION_START", "Starting file classification from: " + sourceDbPath_);

	if (!openDatabases()) {
		return false;
	}

	if (!createCategoryTables()) {
		return false;
	}

	if (!classifyFiles()) {
		return false;
	}

	std::cout << "Files classified successfully" << std::endl;
	AuditLog::instance().log("SYSTEM", "CLASSIFICATION_COMPLETE", "File classification completed to: " + fileDbPath_);

	return true;
}

bool FileClassifier::openDatabases() {
	int rc = sqlite3_open(sourceDbPath_.c_str(), &sourceDb_);
	if (rc != SQLITE_OK) {
		std::cerr << "Cannot open source database: " << sqlite3_errmsg(sourceDb_) << std::endl;
		return false;
	}

	rc = sqlite3_open(fileDbPath_.c_str(), &fileDb_);
	if (rc != SQLITE_OK) {
		std::cerr << "Cannot open file database: " << sqlite3_errmsg(fileDb_) << std::endl;
		return false;
	}

	// Apply write-performance pragmas to the output database. Without these,
	// SQLite defaults to journal_mode=DELETE + synchronous=FULL, which forces
	// an fsync (jbd2_log_wait_commit) on every transaction commit. On a real
	// disk this manifests as the classifier stalling for minutes in D state;
	// tmpfs hides it because tmpfs has no journal to wait on.
	// Match the settings DatabaseManager applies: WAL + relaxed sync.
	sqlite3_exec(fileDb_, "PRAGMA journal_mode=WAL;", nullptr, nullptr, nullptr);
	sqlite3_exec(fileDb_, "PRAGMA synchronous=NORMAL;", nullptr, nullptr, nullptr);
	sqlite3_busy_timeout(fileDb_, 5000);

	return true;
}

bool FileClassifier::createCategoryTables() {
    using namespace FileClassifierSQL;

    //  CREATE main files table
    char* errMsg = nullptr;
    int rc = sqlite3_exec(fileDb_, CREATE_MAIN_FILES_TABLE, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create files table: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }

    // Create indices for files table
    sqlite3_exec(fileDb_, CREATE_MAIN_FILES_INDICES, nullptr, nullptr, nullptr);

    // Create table for each category
    std::vector<FileCategory> categories = {
        FileCategory::IMAGE,
        FileCategory::VIDEO,
        FileCategory::AUDIO,
        FileCategory::DOCUMENT,
        FileCategory::ARCHIVE,
        FileCategory::EXECUTABLE,
        FileCategory::DATABASE,
        FileCategory::SOURCE_CODE,
        FileCategory::WEB,
        FileCategory::EMAIL,
        FileCategory::SYSTEM,
        FileCategory::ENCRYPTED,
        FileCategory::OS_CONFIG,
        FileCategory::OS_BOOT,
        FileCategory::OS_LIBRARY,
        FileCategory::FS_JOURNAL,
        FileCategory::FS_METADATA,
        FileCategory::LOG_FILE,
        FileCategory::CACHE,
        FileCategory::TEMP,
        FileCategory::BACKUP,
        FileCategory::FONT,
        FileCategory::CERTIFICATE,
        FileCategory::UNKNOWN
    };

    for (const auto& category : categories) {
        std::string tableName = getCategoryTableName(category);

        // Create table using template
        std::string createTableSql = std::string(CREATE_CATEGORY_TABLE_TEMPLATE);
        // Replace %TABLE_NAME% with actual table name
        size_t pos = 0;
        while ((pos = createTableSql.find("%TABLE_NAME%", pos)) != std::string::npos) {
            createTableSql.replace(pos, 12, tableName);
            pos += tableName.length();
        }

        char* errMsg = nullptr;
        int rc = sqlite3_exec(fileDb_, createTableSql.c_str(), nullptr, nullptr, &errMsg);

        if (rc != SQLITE_OK) {
            std::cerr << "Failed to create table " << tableName << ": " << errMsg << std::endl;
            sqlite3_free(errMsg);
            return false;
        }

        // Create indices using templates
        std::string indexSql = std::string(CREATE_CATEGORY_INDEX_PATH_TEMPLATE);
        pos = 0;
        while ((pos = indexSql.find("%TABLE_NAME%", pos)) != std::string::npos) {
            indexSql.replace(pos, 12, tableName);
            pos += tableName.length();
        }
        sqlite3_exec(fileDb_, indexSql.c_str(), nullptr, nullptr, nullptr);

        indexSql = std::string(CREATE_CATEGORY_INDEX_EXTENSION_TEMPLATE);
        pos = 0;
        while ((pos = indexSql.find("%TABLE_NAME%", pos)) != std::string::npos) {
            indexSql.replace(pos, 12, tableName);
            pos += tableName.length();
        }
        sqlite3_exec(fileDb_, indexSql.c_str(), nullptr, nullptr, nullptr);

        indexSql = std::string(CREATE_CATEGORY_INDEX_SIZE_TEMPLATE);
        pos = 0;
        while ((pos = indexSql.find("%TABLE_NAME%", pos)) != std::string::npos) {
            indexSql.replace(pos, 12, tableName);
            pos += tableName.length();
        }
        sqlite3_exec(fileDb_, indexSql.c_str(), nullptr, nullptr, nullptr);
    }

    // Create views
    sqlite3_exec(fileDb_, CREATE_FILE_SUMMARY_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(fileDb_, CREATE_EXTENSION_STATISTICS_VIEW, nullptr, nullptr, nullptr);
    sqlite3_exec(fileDb_, CREATE_DELETED_FILES_VIEW, nullptr, nullptr, nullptr);

    return true;
}

bool FileClassifier::classifyFiles() {
	const char* query = R"(
        SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5
        FROM files
        WHERE type = 'REG';
    )";

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(sourceDb_, query, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		std::cerr << "Failed to prepare query: " << sqlite3_errmsg(sourceDb_) << std::endl;
		return false;
	}

	std::unordered_map<FileCategory, int> categoryCounts;

	// Begin transaction for better performance
	sqlite3_exec(fileDb_, "BEGIN TRANSACTION;", nullptr, nullptr, nullptr);

	while (sqlite3_step(stmt) == SQLITE_ROW) {
		int64_t inode = sqlite3_column_int64(stmt, 0);
		std::string name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
		std::string path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
		int64_t size = sqlite3_column_int64(stmt, 3);
		int64_t mtime = sqlite3_column_int64(stmt, 4);
		int64_t ctime = sqlite3_column_int64(stmt, 5);
		std::string type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
		int isDeleted = sqlite3_column_int(stmt, 7);
		const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
		std::string md5 = md5Ptr ? md5Ptr : "";

		// Determine category using integrated classification logic
		FileCategory category = determineCategory(name, path);

		categoryCounts[category]++;

		// Get extension
		std::string extension;
		size_t dotPos = name.find_last_of('.');
		if (dotPos != std::string::npos) {
			extension = name.substr(dotPos + 1);
			std::transform(extension.begin(), extension.end(), extension.begin(), ::tolower);
		}

		// Insert into appropriate table
		std::string tableName = getCategoryTableName(category);
		std::string insertSql = "INSERT INTO " + tableName +
			" (inode, name, path, size, extension, mtime, ctime, is_deleted, md5) "
			"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

		sqlite3_stmt* insertStmt;
		sqlite3_prepare_v2(fileDb_, insertSql.c_str(), -1, &insertStmt, nullptr);

		sqlite3_bind_int64(insertStmt, 1, inode);
		sqlite3_bind_text(insertStmt, 2, name.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_text(insertStmt, 3, path.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_int64(insertStmt, 4, size);
		sqlite3_bind_text(insertStmt, 5, extension.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_int64(insertStmt, 6, mtime);
		sqlite3_bind_int64(insertStmt, 7, ctime);
		sqlite3_bind_int(insertStmt, 8, isDeleted);
		sqlite3_bind_text(insertStmt, 9, md5.c_str(), -1, SQLITE_TRANSIENT);

		sqlite3_step(insertStmt);
		sqlite3_finalize(insertStmt);

		// Compute scene information
		std::string sceneTypeStr = (sceneType_ != SceneType::NONE) ? getSceneTypeName(sceneType_) : "";
		int priority = (sceneType_ != SceneType::NONE) ? calculateScenePriority(path, name, category) : 0;
		bool relevant = (sceneType_ != SceneType::NONE) ? isSceneRelevant(path, name) : false;

		// Also insert into main files table
		std::string categoryName = getCategoryName(category);
		std::string filesInsertSql = "INSERT INTO files "
			"(inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant) "
			"VALUES (?, ?, ?, ?, ?, ?, 'REG', ?, ?, ?, ?, ?, ?, ?);";

		sqlite3_prepare_v2(fileDb_, filesInsertSql.c_str(), -1, &insertStmt, nullptr);

		sqlite3_bind_int64(insertStmt, 1, inode);
		sqlite3_bind_text(insertStmt, 2, name.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_text(insertStmt, 3, path.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_int64(insertStmt, 4, size);
		sqlite3_bind_text(insertStmt, 5, extension.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_text(insertStmt, 6, categoryName.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_int64(insertStmt, 7, mtime);
		sqlite3_bind_int64(insertStmt, 8, ctime);
		sqlite3_bind_int(insertStmt, 9, isDeleted);
		sqlite3_bind_text(insertStmt, 10, md5.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_text(insertStmt, 11, sceneTypeStr.c_str(), -1, SQLITE_TRANSIENT);
		sqlite3_bind_int(insertStmt, 12, priority);
		sqlite3_bind_int(insertStmt, 13, relevant ? 1 : 0);

		sqlite3_step(insertStmt);
		sqlite3_finalize(insertStmt);
	}

	sqlite3_finalize(stmt);

	// Commit transaction
	sqlite3_exec(fileDb_, "COMMIT;", nullptr, nullptr, nullptr);

	// Print statistics
	std::cout << "  File classification statistics:" << std::endl;
	for (const auto& [category, count] : categoryCounts) {
		if (count > 0) {
			std::cout << "    - " << getCategoryName(category) << ": " << count << " files" << std::endl;
		}
	}

	return true;
}

FileCategory FileClassifier::determineCategory(const std::string& filename,
	const std::string& path) {
	// 1. Extract extension for basic classification
	std::string extension;
	size_t dotPos = filename.find_last_of('.');
	if (dotPos != std::string::npos) {
		extension = filename.substr(dotPos + 1);
		std::transform(extension.begin(), extension.end(), extension.begin(), ::tolower);
	}

	// 2. Basic extension-based classification
	FileCategory category = FileCategory::UNKNOWN;
	auto it = extensionMap_.find(extension);
	if (it != extensionMap_.end()) {
		category = it->second;
	}

	// 3. Enhanced Classification Logic

	// Priority 0: Check for encryption (Magic Bytes & High Entropy)
	// This overrides extension based check if meaningful encryption is detected
	if (EncryptionUtils::isEncrypted(path)) {
		return FileCategory::ENCRYPTED;
	}

	// Priority 1: Check filename patterns for known system files
	if (isSystemConfigFile(filename)) {
		return FileCategory::OS_CONFIG;
	}

	if (isBootFile(filename)) {
		return FileCategory::OS_BOOT;
	}

	if (isLogFile(filename)) {
		return FileCategory::LOG_FILE;
	}

	// Check for NTFS Metadata files
	if (filename.size() > 0 && filename[0] == '$') {
		// Journal files
		if (filename == "$LogFile" || filename.find("$TxfLog") != std::string::npos ||
		    filename == "$Tops") {
			return FileCategory::FS_JOURNAL;
		}
		// Metadata files
		if (filename == "$MFT" || filename == "$MFTMirr" || filename == "$Bitmap" ||
			filename == "$Boot" || filename == "$Volume" || filename == "$AttrDef" ||
			filename == "$BadClus" || filename == "$Secure" || filename == "$UpCase" ||
			filename == "$Extend" || filename == "$ObjId" || filename == "$Quota" ||
			filename == "$Reparse" || filename == "$RmMetadata" || filename == "$I30" ||
			filename == "$Repair") {
			return FileCategory::FS_METADATA;
		}
	}

	// Check for ext4/Linux filesystem metadata
	if (filename == "lost+found" || filename == ".journal" ||
	    filename.find("journal") == 0) {
		return FileCategory::FS_METADATA;
	}

	// Check for additional boot files
	if (filename == "BOOTNXT" || filename == "bootnxt") {
		return FileCategory::OS_BOOT;
	}

	if (isBackupFile(filename)) {
		return FileCategory::BACKUP;
	}

	// Priority 2: Check path patterns
	if (isOSConfigPath(path)) {
		return FileCategory::OS_CONFIG;
	}

	if (isBootPath(path)) {
		return FileCategory::OS_BOOT;
	}

	if (isLibraryPath(path)) {
		return FileCategory::OS_LIBRARY;
	}

	if (isLogPath(path)) {
		return FileCategory::LOG_FILE;
	}

	if (isCachePath(path)) {
		return FileCategory::CACHE;
	}

	if (isTempPath(path)) {
		return FileCategory::TEMP;
	}

	// Priority 3: Check extended extension map
	auto extendedIt = extendedExtensionMap_.find(extension);
	if (extendedIt != extendedExtensionMap_.end()) {
		return extendedIt->second;
	}

	// Priority 4: Return basic category
	return category;
}

std::string FileClassifier::getCategoryName(FileCategory category) {
	switch (category) {
	case FileCategory::IMAGE: return "Images";
	case FileCategory::VIDEO: return "Videos";
	case FileCategory::AUDIO: return "Audio Files";
	case FileCategory::DOCUMENT: return "Documents";
	case FileCategory::ARCHIVE: return "Archives";
	case FileCategory::EXECUTABLE: return "Executables";
	case FileCategory::DATABASE: return "Databases";
	case FileCategory::SOURCE_CODE: return "Source Code";
	case FileCategory::WEB: return "Web Files";
	case FileCategory::EMAIL: return "Email Files";
	case FileCategory::SYSTEM: return "System Files";
	case FileCategory::ENCRYPTED: return "Encrypted Files";
	case FileCategory::OS_CONFIG: return "OS Config Files";
	case FileCategory::OS_BOOT: return "OS Boot Files";
	case FileCategory::OS_LIBRARY: return "OS Libraries";
	case FileCategory::FS_JOURNAL: return "FS Journal Files";
	case FileCategory::FS_METADATA: return "FS Metadata";
	case FileCategory::LOG_FILE: return "Log Files";
	case FileCategory::CACHE: return "Cache Files";
	case FileCategory::TEMP: return "Temp Files";
	case FileCategory::BACKUP: return "Backup Files";
	case FileCategory::FONT: return "Font Files";
	case FileCategory::CERTIFICATE: return "Certificates";
	case FileCategory::UNKNOWN: return "Unknown Files";
	default: return "Unknown";
	}
}

std::string FileClassifier::getCategoryTableName(FileCategory category) {
	switch (category) {
	case FileCategory::IMAGE: return "images";
	case FileCategory::VIDEO: return "videos";
	case FileCategory::AUDIO: return "audio_files";
	case FileCategory::DOCUMENT: return "documents";
	case FileCategory::ARCHIVE: return "archives";
	case FileCategory::EXECUTABLE: return "executables";
	case FileCategory::DATABASE: return "databases";
	case FileCategory::SOURCE_CODE: return "source_code";
	case FileCategory::WEB: return "web_files";
	case FileCategory::EMAIL: return "email_files";
	case FileCategory::SYSTEM: return "system_files";
	case FileCategory::ENCRYPTED: return "encrypted_files";
	case FileCategory::OS_CONFIG: return "os_config_files";
	case FileCategory::OS_BOOT: return "os_boot_files";
	case FileCategory::OS_LIBRARY: return "os_libraries";
	case FileCategory::FS_JOURNAL: return "fs_journal";
	case FileCategory::FS_METADATA: return "fs_metadata";
	case FileCategory::LOG_FILE: return "log_files";
	case FileCategory::CACHE: return "cache_files";
	case FileCategory::TEMP: return "temp_files";
	case FileCategory::BACKUP: return "backup_files";
	case FileCategory::FONT: return "font_files";
	case FileCategory::CERTIFICATE: return "certificates";
	case FileCategory::UNKNOWN: return "unknown_files";
	default: return "unknown_files";
	}
}

void FileClassifier::closeDatabases() {
	if (sourceDb_) {
		sqlite3_close(sourceDb_);
		sourceDb_ = nullptr;
	}
	if (fileDb_) {
		sqlite3_close(fileDb_);
		fileDb_ = nullptr;
	}
}

// Helper methods for classification

bool FileClassifier::isOSConfigPath(const std::string& path) {
    return pathContains(path, osConfigPaths_);
}

bool FileClassifier::isBootPath(const std::string& path) {
    return pathContains(path, bootPaths_);
}

bool FileClassifier::isLibraryPath(const std::string& path) {
    return pathContains(path, libraryPaths_);
}

bool FileClassifier::isLogPath(const std::string& path) {
    return pathContains(path, logPaths_);
}

bool FileClassifier::isCachePath(const std::string& path) {
    return pathContains(path, cachePaths_);
}

bool FileClassifier::isTempPath(const std::string& path) {
    return pathContains(path, tempPaths_);
}

bool FileClassifier::isSystemConfigFile(const std::string& filename) {
    return filenameMatches(filename, systemConfigFiles_);
}

bool FileClassifier::isBootFile(const std::string& filename) {
    return filenameMatches(filename, bootFiles_);
}

bool FileClassifier::isLogFile(const std::string& filename) {
    std::string lower = filename;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // Check if ends with .log
    if (lower.size() > 4 && lower.substr(lower.size() - 4) == ".log") {
        return true;
    }

    // Check common log file names
    std::vector<std::string> logPatterns = {
        "syslog", "messages", "dmesg", "kern.log", "auth.log",
        "debug", "error", "access", "audit"
    };

    for (const auto& pattern : logPatterns) {
        if (lower.find(pattern) != std::string::npos) {
            return true;
        }
    }

    return false;
}

bool FileClassifier::isBackupFile(const std::string& filename) {
    std::string lower = filename;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    // Check backup patterns
    if (lower.find("backup") != std::string::npos) return true;
    if (lower.find(".bak") != std::string::npos) return true;
    if (lower.find(".old") != std::string::npos) return true;
    if (lower.find(".orig") != std::string::npos) return true;
    if (!filename.empty() && filename.back() == '~') return true;

    return false;
}

bool FileClassifier::pathContains(const std::string& path,
                                  const std::vector<std::string>& patterns) {
    std::string lowerPath = path;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);

    for (const auto& pattern : patterns) {
        std::string lowerPattern = pattern;
        std::transform(lowerPattern.begin(), lowerPattern.end(), lowerPattern.begin(), ::tolower);

        if (lowerPath.find(lowerPattern) != std::string::npos) {
            return true;
        }
    }
    return false;
}

bool FileClassifier::filenameMatches(const std::string& filename,
                                     const std::vector<std::string>& patterns) {
    std::string lowerFilename = filename;
    std::transform(lowerFilename.begin(), lowerFilename.end(), lowerFilename.begin(), ::tolower);

    for (const auto& pattern : patterns) {
        std::string lowerPattern = pattern;
        std::transform(lowerPattern.begin(), lowerPattern.end(), lowerPattern.begin(), ::tolower);

        // Check exact match
        if (lowerFilename == lowerPattern) {
            return true;
        }

        // Check if filename starts with pattern
        if (lowerFilename.find(lowerPattern) == 0) {
            return true;
        }

        // Check if filename contains pattern
        if (lowerFilename.find(lowerPattern) != std::string::npos) {
            return true;
        }
    }
    return false;
}

// ============================================================================
// Scene-Aware Classification Methods
// ============================================================================

