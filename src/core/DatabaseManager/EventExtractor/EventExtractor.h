#pragma once
#ifndef EVENT_EXTRACTOR_H
#define EVENT_EXTRACTOR_H

#include <string>
#include <sqlite3.h>
#include <memory>
#include <vector>

struct TimelineEvent {
	int64_t timestamp;
	std::string eventType;  // CREATED, MODIFIED, ACCESSED, CHANGED
	std::string filePath;
	int64_t inode;
	std::string description;
};

class EventExtractor {
public:
	explicit EventExtractor(const std::string& sourceDbPath,
		const std::string& eventDbPath);
	~EventExtractor();

	bool extractEvents();

    bool importWindowsArtifacts(const std::string& windowsDbPath);
    bool importLinuxArtifacts(const std::string& linuxDbPath);

private:
	std::string sourceDbPath_;
	std::string eventDbPath_;
	sqlite3* sourceDb_;
	sqlite3* eventDb_;

	bool openDatabases();
	bool createEventTables();
	bool extractFileSystemEvents();
	bool insertEvent(const TimelineEvent& event);
	void closeDatabases();
};

#endif // EVENT_EXTRACTOR_H
