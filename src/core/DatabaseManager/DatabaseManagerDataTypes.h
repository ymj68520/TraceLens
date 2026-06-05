#pragma once
#ifndef DATABASE_MANAGER_DATA_TYPES_H
#define DATABASE_MANAGER_DATA_TYPES_H

#include <string>
#include <cstdint>

/**
 * @brief File record structure
 * 
 * Represents a single file record extracted from filesystem.
 */
struct FileRecord {
	int id = 0;
	int64_t inode;
	std::string name;
	std::string path;
	int64_t size;
	std::string extension;
	std::string category;
	int64_t atime;
	int64_t mtime;
	int64_t ctime;
	int64_t crtime;
	std::string type;
	std::string md5;
	int isDeleted;
	int isAllocated;
	std::string permissions;
	int uid;
	int gid;

	// Scene-aware classification fields
	std::string sceneType;
	int scenePriority = 0;
	int sceneRelevant = 0;
};

/**
 * @brief Event record structure
 * 
 * Represents a forensic event associated with files.
 */
struct EventRecord {
	int64_t timestamp;
	std::string eventType;
	std::string filePath;
	int64_t inode;
	std::string description;
};

#endif // DATABASE_MANAGER_DATA_TYPES_H
