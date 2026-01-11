#pragma once
#ifndef FILE_CLASSIFIER_H
#define FILE_CLASSIFIER_H

#include <string>
#include <sqlite3.h>
#include <unordered_map>
#include <vector>
#include <set>

enum class FileCategory {
	IMAGE,
	VIDEO,
	AUDIO,
	DOCUMENT,
	ARCHIVE,
	EXECUTABLE,
	DATABASE,
	SOURCE_CODE,
	WEB,
	EMAIL,
	SYSTEM,
	ENCRYPTED,
	
	// Operating System specific files
	OS_CONFIG,      // OS configuration files (/etc/passwd, /etc/fstab)
	OS_BOOT,        // Boot and kernel files (vmlinuz, initrd, grub.cfg)
	OS_LIBRARY,     // System libraries (.so, .dylib, .a)
	
	// Filesystem specific files
	FS_JOURNAL,     // Filesystem journal files
	FS_METADATA,    // Filesystem metadata
	
	// Refined general categories
	LOG_FILE,       // Log files
	CACHE,          // Cache files
	TEMP,           // Temporary files
	BACKUP,         // Backup files
	FONT,           // Font files
	CERTIFICATE,    // Certificates and keys
	
	UNKNOWN
};

class FileClassifier {
public:
	explicit FileClassifier(const std::string& sourceDbPath,
		const std::string& fileDbPath);
	~FileClassifier();

	bool classifyAndExtract();
	
	// File classification method (public for testing)
	FileCategory determineCategory(const std::string& filename,
		const std::string& path);

private:
	std::string sourceDbPath_;
	std::string fileDbPath_;
	sqlite3* sourceDb_;
	sqlite3* fileDb_;

	std::unordered_map<std::string, FileCategory> extensionMap_;
	
	// Advanced classification data structures
	std::vector<std::string> osConfigPaths_;
	std::vector<std::string> bootPaths_;
	std::vector<std::string> libraryPaths_;
	std::vector<std::string> logPaths_;
	std::vector<std::string> cachePaths_;
	std::vector<std::string> tempPaths_;
	std::vector<std::string> systemConfigFiles_;
	std::vector<std::string> bootFiles_;
	std::unordered_map<std::string, FileCategory> extendedExtensionMap_;

	bool openDatabases();
	bool createCategoryTables();
	bool classifyFiles();
	std::string getCategoryName(FileCategory category);
	std::string getCategoryTableName(FileCategory category);
	void initializeExtensionMap();
	void closeDatabases();
	
	// Advanced classification helper methods
	bool isOSConfigPath(const std::string& path);
	bool isBootPath(const std::string& path);
	bool isLibraryPath(const std::string& path);
	bool isLogPath(const std::string& path);
	bool isCachePath(const std::string& path);
	bool isTempPath(const std::string& path);
	bool isSystemConfigFile(const std::string& filename);
	bool isBootFile(const std::string& filename);
	bool isLogFile(const std::string& filename);
	bool isBackupFile(const std::string& filename);
	void initializePathPatterns();
	void initializeFilenamePatterns();
	void initializeExtendedExtensionMap();
	bool pathContains(const std::string& path, const std::vector<std::string>& patterns);
	bool filenameMatches(const std::string& filename, const std::vector<std::string>& patterns);
};

#endif // FILE_CLASSIFIER_H
