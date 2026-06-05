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

// Scene type for context-aware classification
enum class SceneType {
	NONE,
	ANDROID,
	WINDOWS,
	LINUX,
	SERVER_CLOUD
};

// Scene priority levels for forensic relevance scoring
struct ScenePriority {
	static constexpr int CRITICAL = 100;
	static constexpr int HIGH = 75;
	static constexpr int MEDIUM = 50;
	static constexpr int LOW = 25;
	static constexpr int IRRELEVANT = 0;
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

	// Scene-aware classification interface
	void setSceneType(SceneType scene);
	SceneType getSceneType() const;
	int calculateScenePriority(const std::string& path, const std::string& filename, FileCategory category);
	bool isSceneRelevant(const std::string& path, const std::string& filename);

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

	// Scene-related members
	SceneType sceneType_ = SceneType::NONE;

	bool openDatabases();
	bool createCategoryTables();
	bool classifyFiles();
	std::string getCategoryName(FileCategory category);
	std::string getCategoryTableName(FileCategory category);
	void initializeExtensionMap();
	void closeDatabases();

	// Scene-related methods
	void markSceneFiles();
	void applyAndroidSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
	void applyWindowsSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
	void applyLinuxSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
	void applyServerCloudSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant);
	std::string getSceneTypeName(SceneType scene) const;
	
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
