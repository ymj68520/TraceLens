// WindowsArtifactsParsers.cpp
// Implementation of various Windows artifact parsers

#include "WindowsFilesAnalyzer.h"
#include "WindowsPrefetchParser.h"
#include "WindowsLnkParser.h"
#include "WindowsAmcacheParser.h"
#include "WindowsSrumParser.h"
#include "WindowsBrowserParser.h"
#include "WindowsJumpListParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <ctime>
#include <filesystem>

namespace fs = std::filesystem;

// --- Prefetch Analysis ---

void WindowsFilesAnalyzer::analyzePrefetchFiles() {
    std::cout << "Analyzing Prefetch files..." << std::endl;
    
    // Prefetch files are in Windows/Prefetch/*.pf
    std::vector<FileRecord> pfFiles = queryFilesByPattern("%/Windows/Prefetch/%.pf");
    
    for (const auto& file : pfFiles) {
        std::string extractPath = getExtractPath("prefetch/" + file.name);
        
        if (extractFileToPath(file.inode, extractPath)) {
            PrefetchInfo info = parsePrefetchFile(extractPath);
            // If parsing failed (empty path), skip
            if (!info.filePath.empty()) {
                info.creationTime = file.crtime;
                windowsDb_->insertPrefetchInfo(info);
            }
        }
    }
}

PrefetchInfo WindowsFilesAnalyzer::parsePrefetchFile(const std::string& prefetchPath) {
    PrefetchInfo info;
    info.filePath = prefetchPath;

    // Use the new PrefetchParser
    PrefetchParser parser(prefetchPath);
    if (!parser.parse()) {
        // Parsing failed, log error and return basic info
        AuditLog::instance().log("WARNING", "PREFETCH_PARSE_FAILED",
            "Failed to parse prefetch file: " + prefetchPath);

        // Extract basic info from filename as fallback
        std::string filename = fs::path(prefetchPath).filename().string();
        size_t dashPos = filename.find_last_of('-');
        if (dashPos != std::string::npos) {
            info.executableName = filename.substr(0, dashPos);
            size_t dotPos = filename.find_last_of('.');
            if (dotPos != std::string::npos && dotPos > dashPos) {
                info.prefetchHash = filename.substr(dashPos + 1, dotPos - dashPos - 1);
            }
        }
        info.runCount = 1;
        info.lastRunTime = std::time(nullptr);
        return info;
    }

    // Extract parsed information
    info.executableName = parser.getExecutableName();
    info.executablePath = parser.getExecutablePath();
    info.prefetchHash = parser.getPrefetchHash();
    info.runCount = static_cast<int>(parser.getRunCount());
    info.lastRunTime = parser.getLastRunTime();
    info.creationTime = parser.getCreationTime();
    info.referencedFiles = parser.getReferencedFiles();
    info.referencedDirectories = parser.getReferencedDirectories();

    return info;
}

// --- LNK Analysis ---

void WindowsFilesAnalyzer::analyzeLnkFiles() {
    std::cout << "Analyzing LNK (Shortcut) files..." << std::endl;
    
    // Search broadly for LNK files in user directories
    std::vector<FileRecord> lnkFiles = queryFilesByPattern("%/Users/%/%.lnk");
    
    for (const auto& file : lnkFiles) {
        std::string extractPath = getExtractPath("shortcuts/" + std::to_string(file.inode) + "_" + file.name);
        
        if (extractFileToPath(file.inode, extractPath)) {
            LnkFileInfo info = parseLnkFile(extractPath);
            if (!info.lnkPath.empty()) {
                info.creationTime = file.crtime;
                info.accessTime = file.atime;
                info.modificationTime = file.mtime;
                windowsDb_->insertLnkFileInfo(info);
            }
        }
    }
}

LnkFileInfo WindowsFilesAnalyzer::parseLnkFile(const std::string& lnkPath) {
    LnkFileInfo info;
    info.lnkPath = lnkPath;

    // Use the new LnkParser
    LnkParser parser(lnkPath);
    if (!parser.parse()) {
        // Parsing failed, log error
        AuditLog::instance().log("WARNING", "LNK_PARSE_FAILED",
            "Failed to parse LNK file: " + lnkPath + " - " + parser.getLastError());
        return info; // Return empty info
    }

    // Extract all parsed information
    info.targetPath = parser.getTargetPath();
    info.workingDirectory = parser.getWorkingDirectory();
    info.arguments = parser.getArguments();
    info.iconLocation = parser.getIconLocation();
    info.description = parser.getDescription();
    info.relativePath = parser.getRelativePath();

    info.creationTime = parser.getCreationTime();
    info.accessTime = parser.getAccessTime();
    info.modificationTime = parser.getWriteTime();

    info.targetSize = parser.getFileSize();
    info.driveType = parser.getDriveType();
    info.volumeSerial = parser.getVolumeSerial();
    info.netBiosName = parser.getNetBiosName();

    return info;
}

// --- Jump List Analysis ---

void WindowsFilesAnalyzer::analyzeJumpLists() {
    std::cout << "Analyzing Jump Lists..." << std::endl;
    AuditLog::instance().log("SYSTEM", "JUMPLIST_ANALYSIS_START",
        "Starting Jump List analysis");
    
    int processedFiles = 0;
    int totalEntries = 0;
    
    // AutomaticDestinations (Recent/Frequent items - OLE format)
    std::vector<FileRecord> autoDest = queryFilesByPattern("%/AutomaticDestinations/%.automaticDestinations-ms");
    
    for (const auto& file : autoDest) {
        std::string extractPath = getExtractPath("jumplists/auto/" + file.name);
        
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseJumpListFile(extractPath);
            
            if (!entries.empty()) {
                for (const auto& entry : entries) {
                    windowsDb_->insertJumpListEntry(entry);
                }
                processedFiles++;
                totalEntries += entries.size();
                
                std::cout << "  Processed AutoDest: " << file.name 
                         << " (" << entries.size() << " entries)" << std::endl;
            }
        }
    }
    
    // CustomDestinations (Pinned items)
    std::vector<FileRecord> customDest = queryFilesByPattern("%/CustomDestinations/%.customDestinations-ms");
    
    for (const auto& file : customDest) {
        std::string extractPath = getExtractPath("jumplists/custom/" + file.name);
        
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseJumpListFile(extractPath);
            
            if (!entries.empty()) {
                for (const auto& entry : entries) {
                    windowsDb_->insertJumpListEntry(entry);
                }
                processedFiles++;
                totalEntries += entries.size();
                
                std::cout << "  Processed CustomDest: " << file.name 
                         << " (" << entries.size() << " entries)" << std::endl;
            }
        }
    }
    
    std::cout << "  Processed " << processedFiles << " Jump List files"
             << " with " << totalEntries << " total entries." << std::endl;
    
    AuditLog::instance().log("SYSTEM", "JUMPLIST_ANALYSIS_COMPLETE",
        "Jump List analysis completed: " + std::to_string(processedFiles) + 
        " files, " + std::to_string(totalEntries) + " entries");
}

std::vector<JumpListEntry> WindowsFilesAnalyzer::parseJumpListFile(const std::string& jumpListPath) {
    // Use the new JumpListParser with libolecf support
    JumpListParser parser(jumpListPath);
    
    if (!parser.parse()) {
        AuditLog::instance().log("WARNING", "JUMPLIST_PARSE_FAILED",
            "Failed to parse Jump List: " + jumpListPath + " - " + parser.getLastError());
        return {};
    }
    
    return parser.getEntries();
}

// --- Recycle Bin Analysis ---

void WindowsFilesAnalyzer::analyzeRecycleBin() {
    std::cout << "Analyzing Recycle Bin..." << std::endl;
    
    // Search for $I files (index files) in $Recycle.Bin
    std::vector<FileRecord> iFiles = queryFilesByPattern("%/$Recycle.Bin/%/$I%");
    
    for (const auto& file : iFiles) {
        std::string extractPath = getExtractPath("recyclebin/" + file.name);
        
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseRecycleBin(extractPath);
            for (const auto& entry : entries) {
                windowsDb_->insertRecycleBinEntry(entry);
            }
        }
    }
}

std::vector<RecycleBinEntry> WindowsFilesAnalyzer::parseRecycleBin(const std::string& recycleBinPath) {
    std::vector<RecycleBinEntry> entries;
    
    std::ifstream file(recycleBinPath, std::ios::binary);
    if (!file) return entries;
    
    // Get file size
    file.seekg(0, std::ios::end);
    size_t fileSize = file.tellg();
    file.seekg(0, std::ios::beg);
    
    if (fileSize < 24) return entries; // Minimum header size
    
    // $I file format:
    // Version 1 (Win Vista/7/8): Header(8), Size(8), DeletedTime(8), Path(520 bytes UTF-16LE, fixed)
    // Version 2 (Win 10+): Header(8), Size(8), DeletedTime(8), PathLen(4), Path(variable UTF-16LE)
    
    uint64_t version = 0;
    file.read(reinterpret_cast<char*>(&version), 8);
    
    RecycleBinEntry entry;
    entry.recycleFilePath = recycleBinPath;
    
    // Extract user SID from parent directory path
    // Path format: .../$Recycle.Bin/S-1-5-21-xxx-xxx-xxx-xxxx/$Ixxxxxx
    fs::path recyclePath(recycleBinPath);
    fs::path parent = recyclePath.parent_path();
    if (!parent.empty()) {
        std::string sidDir = parent.filename().string();
        if (sidDir.substr(0, 4) == "S-1-") {
            entry.userSid = sidDir;
        }
    }
    
    // Extract original filename hint from $I filename
    // $I filename format: $Ixxxxxx where xxxxxx matches $Rxxxxxx (actual deleted file)
    std::string iFileName = recyclePath.filename().string();
    if (iFileName.length() > 2 && iFileName.substr(0, 2) == "$I") {
        entry.fileName = "$R" + iFileName.substr(2); // Corresponding $R file
    }
    
    if (version == 1) {
        // Version 1: Fixed 520-byte path (260 UTF-16LE chars)
        uint64_t size;
        file.read(reinterpret_cast<char*>(&size), 8);
        entry.originalSize = size;
        
        uint64_t deletedTime;
        file.read(reinterpret_cast<char*>(&deletedTime), 8);
        entry.deletionTime = filetimeToUnixTime(deletedTime);
        
        // Read fixed 520-byte UTF-16LE path
        char pathBuffer[520];
        file.read(pathBuffer, 520);
        entry.originalPath = readUTF16LEString(pathBuffer, 520);
        
        entries.push_back(entry);
        
    } else if (version == 2) {
        // Version 2: Variable length path
        uint64_t size;
        file.read(reinterpret_cast<char*>(&size), 8);
        entry.originalSize = size;
        
        uint64_t deletedTime;
        file.read(reinterpret_cast<char*>(&deletedTime), 8);
        entry.deletionTime = filetimeToUnixTime(deletedTime);
        
        // Read path length (in bytes, including null terminator)
        uint32_t pathLen;
        file.read(reinterpret_cast<char*>(&pathLen), 4);
        
        if (pathLen > 0 && pathLen < 65536) { // Sanity check
            std::vector<char> pathBuffer(pathLen);
            file.read(pathBuffer.data(), pathLen);
            entry.originalPath = readUTF16LEString(pathBuffer.data(), pathLen);
        }
        
        entries.push_back(entry);
    }
    
    return entries;
}

// --- Other Analyzers ---

void WindowsFilesAnalyzer::analyzeNTFSMetadata() {
    // Requires extraction of $MFT, which can be large.
    // For now we skip or implement basic checking.
}

void WindowsFilesAnalyzer::analyzeUserProfiles() {
    // Handled mainly via Registry (NTUSER.DAT)
}

void WindowsFilesAnalyzer::analyzeWindowsServices() {
    // Extracted from SYSTEM registry hive (already handled in analyzeRegistryHives)
}

void WindowsFilesAnalyzer::analyzeScheduledTasks() {
    std::cout << "Analyzing Scheduled Tasks..." << std::endl;
    AuditLog::instance().log("SYSTEM", "SCHEDULED_TASKS_START",
        "Starting scheduled tasks analysis");

    // Query for task XML files in Windows/System32/Tasks
    std::vector<FileRecord> taskFiles = queryFilesByPattern("%/Windows/System32/Tasks/%");

    int processedCount = 0;
    
    for (const auto& file : taskFiles) {
        // Skip directories and non-XML files (Tasks folder contains both XML files and subdirectories)
        if (file.size == 0) continue;

        std::string extractPath = getExtractPath("tasks/" + std::to_string(file.inode) + "_" + file.name);

        if (extractFileToPath(file.inode, extractPath)) {
            // Read file content for basic XML parsing
            std::ifstream taskFile(extractPath);
            if (taskFile) {
                std::stringstream buffer;
                buffer << taskFile.rdbuf();
                std::string content = buffer.str();

                // Basic XML parsing using regex (for simplicity)
                // Note: For production, consider using a proper XML parser like pugixml
                ScheduledTaskInfo task;
                task.taskName = file.name;
                task.taskPath = file.path;

                // Extract Command/Exec path
                std::regex commandRegex("<Command>([^<]+)</Command>");
                std::smatch commandMatch;
                if (std::regex_search(content, commandMatch, commandRegex)) {
                    task.actionPath = commandMatch[1].str();
                    task.actionType = "Exec";
                }

                // Extract Arguments
                std::regex argsRegex("<Arguments>([^<]*)</Arguments>");
                std::smatch argsMatch;
                if (std::regex_search(content, argsMatch, argsRegex)) {
                    task.arguments = argsMatch[1].str();
                }

                // Extract Enabled state
                std::regex enabledRegex("<Enabled>(true|false)</Enabled>");
                std::smatch enabledMatch;
                if (std::regex_search(content, enabledMatch, enabledRegex)) {
                    task.status = (enabledMatch[1].str() == "true") ? "Enabled" : "Disabled";
                } else {
                    task.status = "Enabled"; // Default to enabled if not specified
                }

                // Extract Author
                std::regex authorRegex("<Author>([^<]*)</Author>");
                std::smatch authorMatch;
                if (std::regex_search(content, authorMatch, authorRegex)) {
                    task.author = authorMatch[1].str();
                }

                // Extract Description
                std::regex descRegex("<Description>([^<]*)</Description>");
                std::smatch descMatch;
                if (std::regex_search(content, descMatch, descRegex)) {
                    task.description = descMatch[1].str();
                }

                // Extract UserId (RunAs account)
                std::regex userIdRegex("<UserId>([^<]*)</UserId>");
                std::smatch userIdMatch;
                if (std::regex_search(content, userIdMatch, userIdRegex)) {
                    task.runAs = userIdMatch[1].str();
                }

                // Set last run time from file metadata (use modification time as approximation)
                task.lastRunTime = file.mtime;
                task.nextRunTime = 0;  // Unknown without parsing trigger details

                // Insert into database
                windowsDb_->insertScheduledTask(task);
                processedCount++;
            }
        }
    }

    std::cout << "  Processed " << processedCount << " scheduled task files." << std::endl;
    AuditLog::instance().log("SYSTEM", "SCHEDULED_TASKS_COMPLETE",
        "Scheduled tasks analysis completed: " + std::to_string(processedCount) + " tasks");
}

void WindowsFilesAnalyzer::analyzeAmcache() {
    std::cout << "Analyzing Amcache (Application Compatibility)..." << std::endl;
    AuditLog::instance().log("SYSTEM", "AMCACHE_ANALYSIS_START",
        "Starting Amcache.hve analysis");

    // Search for Amcache.hve in Windows/AppCompat/Programs/
    std::vector<FileRecord> amcacheFiles = queryFilesByPattern("%/Windows/AppCompat/Programs/Amcache.hve");

    int processedCount = 0;
    int totalEntries = 0;

    for (const auto& file : amcacheFiles) {
        std::string extractPath = getExtractPath("amcache/" + std::to_string(file.inode) + "_Amcache.hve");

        if (extractFileToPath(file.inode, extractPath)) {
            AmcacheParser parser(extractPath);
            if (parser.parse()) {
                std::vector<AmcacheEntry> entries = parser.getEntries();

                if (!entries.empty()) {
                    // Insert all entries into database
                    for (const auto& entry : entries) {
                        windowsDb_->insertAmcacheEntry(entry);
                    }

                    processedCount++;
                    totalEntries += entries.size();

                    std::cout << "  Processed: Amcache.hve (" << entries.size()
                             << " application entries)" << std::endl;
                }
            } else {
                AuditLog::instance().log("WARNING", "AMCACHE_PARSE_FAILED",
                    "Failed to parse Amcache.hve: " + extractPath);
            }
        }
    }

    std::cout << "  Processed " << processedCount << " Amcache files"
             << " with " << totalEntries << " total entries." << std::endl;

    AuditLog::instance().log("SYSTEM", "AMCACHE_ANALYSIS_COMPLETE",
        "Completed Amcache analysis: " + std::to_string(processedCount) +
        " files, " + std::to_string(totalEntries) + " entries");
}

void WindowsFilesAnalyzer::analyzeSRUM() {
    std::cout << "Analyzing SRUM (System Resource Usage Monitor)..." << std::endl;
    AuditLog::instance().log("SYSTEM", "SRUM_ANALYSIS_START",
        "Starting SRUDB.dat analysis");

    // SRUM database is located at Windows/System32/sru/SRUDB.dat
    std::vector<FileRecord> srumFiles = queryFilesByPattern("%/Windows/System32/sru/SRUDB.dat");

    int processedCount = 0;
    int totalEntries = 0;

    for (const auto& file : srumFiles) {
        std::string extractPath = getExtractPath("srum/" + std::to_string(file.inode) + "_SRUDB.dat");

        if (extractFileToPath(file.inode, extractPath)) {
            SrumParser parser(extractPath);
            if (parser.parse()) {
                std::vector<SrumEntry> entries = parser.getEntries();

                if (!entries.empty()) {
                    // Begin transaction for batch insert
                    windowsDb_->beginTransaction();

                    // Insert all entries into database
                    for (const auto& entry : entries) {
                        windowsDb_->insertSrumEntry(entry);
                    }

                    windowsDb_->commitTransaction();

                    processedCount++;
                    totalEntries += entries.size();

                    std::cout << "  Processed: SRUDB.dat (" << entries.size()
                             << " resource usage entries)" << std::endl;

                    // Log some statistics
                    int networkEntries = 0;
                    int cpuEntries = 0;
                    for (const auto& entry : entries) {
                        if (entry.bytesReceived > 0 || entry.bytesSent > 0) {
                            networkEntries++;
                        }
                        if (entry.cpuTimeMs > 0 || entry.foregroundDuration > 0) {
                            cpuEntries++;
                        }
                    }

                    std::cout << "    - Network usage entries: " << networkEntries << std::endl;
                    std::cout << "    - CPU/application usage entries: " << cpuEntries << std::endl;
                }
            } else {
                AuditLog::instance().log("WARNING", "SRUM_PARSE_FAILED",
                    "Failed to parse SRUDB.dat: " + extractPath +
                    " - " + parser.getLastError());
            }
        }
    }

    std::cout << "  Processed " << processedCount << " SRUM database(s)"
             << " with " << totalEntries << " total entries." << std::endl;

    AuditLog::instance().log("SYSTEM", "SRUM_ANALYSIS_COMPLETE",
        "Completed SRUM analysis: " + std::to_string(processedCount) +
        " databases, " + std::to_string(totalEntries) + " entries");
}
