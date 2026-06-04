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
#include "Logger/Logger.h"
#include <libfsntfs.h>
#include <pugixml.hpp>
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
    std::cout << "Analyzing NTFS MFT metadata..." << std::endl;
    AuditLog::instance().log("SYSTEM", "MFT_ANALYSIS_START",
        "Starting NTFS MFT metadata analysis");

    // Query for $MFT file
    std::vector<FileRecord> mftFiles = queryFilesByPattern("$MFT");
    if (mftFiles.empty()) {
        // Try alternative pattern
        mftFiles = queryFilesByPattern("%/$MFT");
    }

    if (mftFiles.empty()) {
        LOG_INFO("MFT分析: 未找到 $MFT 文件，跳过");
        return;
    }

    const auto& mftFile = mftFiles[0];
    std::string extractPath = getExtractPath("mft/$MFT");

    // Extract $MFT file
    if (!extractFileToPath(mftFile.inode, extractPath)) {
        LOG_ERROR("MFT分析: 无法提取 $MFT 文件");
        return;
    }

    LOG_INFO("MFT分析: 成功提取 $MFT 文件，开始解析");

    // Open the MFT file using libfsntfs MFT metadata file API
    libfsntfs_mft_metadata_file_t* mftMetadataFile = nullptr;
    libfsntfs_error_t* error = nullptr;

    if (libfsntfs_mft_metadata_file_initialize(&mftMetadataFile, &error) != 1) {
        LOG_ERROR("MFT分析: 无法初始化 libfsntfs MFT 元数据文件句柄");
        libfsntfs_error_free(&error);
        return;
    }

    if (libfsntfs_mft_metadata_file_open(mftMetadataFile, extractPath.c_str(),
                                          libfsntfs_get_access_flags_read(), &error) != 1) {
        LOG_ERROR("MFT分析: 无法打开 $MFT 文件");
        libfsntfs_mft_metadata_file_free(&mftMetadataFile, nullptr);
        libfsntfs_error_free(&error);
        return;
    }

    // Get number of MFT entries
    uint64_t numberOfEntries = 0;
    if (libfsntfs_mft_metadata_file_get_number_of_file_entries(mftMetadataFile, &numberOfEntries, &error) != 1) {
        LOG_ERROR("MFT分析: 无法获取 MFT 条目数量");
        libfsntfs_mft_metadata_file_close(mftMetadataFile, nullptr);
        libfsntfs_mft_metadata_file_free(&mftMetadataFile, nullptr);
        libfsntfs_error_free(&error);
        return;
    }

    LOG_INFO("MFT分析: 发现 " + std::to_string(numberOfEntries) + " 个 MFT 条目");

    // Limit to prevent excessive memory usage (first 100K entries by default)
    const uint64_t maxEntries = std::min(numberOfEntries, static_cast<uint64_t>(100000));

    windowsDb_->beginTransaction();
    int processedCount = 0;
    int errorCount = 0;

    // Convert FILETIME to Unix timestamp (seconds since 1970-01-01)
    auto filetimeToUnix = [](uint64_t ft) -> int64_t {
        if (ft == 0) return 0;
        // FILETIME epoch is 1601-01-01, Unix epoch is 1970-01-01
        // Difference in 100ns intervals: 116444736000000000
        return static_cast<int64_t>((ft - 116444736000000000ULL) / 10000000ULL);
    };

    for (uint64_t i = 0; i < maxEntries; ++i) {
        libfsntfs_file_entry_t* fileEntry = nullptr;
        if (libfsntfs_mft_metadata_file_get_file_entry_by_index(mftMetadataFile, i, &fileEntry, &error) != 1) {
            errorCount++;
            libfsntfs_error_free(&error);
            error = nullptr;
            continue;
        }

        MftEntryInfo entry;
        entry.entryNumber = static_cast<int64_t>(i);

        // Get file reference (entry number)
        uint64_t fileReference = 0;
        if (libfsntfs_file_entry_get_file_reference(fileEntry, &fileReference, &error) == 1) {
            entry.entryNumber = static_cast<int64_t>(fileReference & 0xFFFFFFFFFFFF);
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // Get file name
        size_t nameSize = 0;
        if (libfsntfs_file_entry_get_utf8_name_size(fileEntry, &nameSize, &error) == 1 && nameSize > 0) {
            std::vector<uint8_t> nameBuffer(nameSize);
            if (libfsntfs_file_entry_get_utf8_name(fileEntry, nameBuffer.data(), nameSize, &error) == 1) {
                entry.fileName = std::string(reinterpret_cast<char*>(nameBuffer.data()));
            }
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // Get parent file reference
        uint64_t parentReference = 0;
        if (libfsntfs_file_entry_get_parent_file_reference(fileEntry, &parentReference, &error) == 1) {
            entry.parentEntry = static_cast<int64_t>(parentReference & 0xFFFFFFFFFFFF);
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // Get timestamps (Windows FILETIME format - 100ns since 1601-01-01)
        uint64_t creationTime = 0, modificationTime = 0, accessTime = 0, entryModTime = 0;
        libfsntfs_file_entry_get_creation_time(fileEntry, &creationTime, &error);
        libfsntfs_error_free(&error); error = nullptr;
        libfsntfs_file_entry_get_modification_time(fileEntry, &modificationTime, &error);
        libfsntfs_error_free(&error); error = nullptr;
        libfsntfs_file_entry_get_access_time(fileEntry, &accessTime, &error);
        libfsntfs_error_free(&error); error = nullptr;
        libfsntfs_file_entry_get_entry_modification_time(fileEntry, &entryModTime, &error);
        libfsntfs_error_free(&error); error = nullptr;

        entry.creationTime = filetimeToUnix(creationTime);
        entry.modificationTime = filetimeToUnix(modificationTime);
        entry.accessTime = filetimeToUnix(accessTime);
        entry.mftModificationTime = filetimeToUnix(entryModTime);

        // Get file size
        size64_t fileSize = 0;
        if (libfsntfs_file_entry_get_size(fileEntry, &fileSize, &error) == 1) {
            entry.logicalSize = static_cast<int64_t>(fileSize);
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // Check if directory
        uint32_t fileAttributeFlags = 0;
        if (libfsntfs_file_entry_get_file_attribute_flags(fileEntry, &fileAttributeFlags, &error) == 1) {
            entry.isDirectory = (fileAttributeFlags & 0x10) != 0; // FILE_ATTRIBUTE_DIRECTORY
            entry.isDeleted = false; // libfsntfs only shows allocated entries
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // Check for alternate data streams
        int numberOfAds = 0;
        if (libfsntfs_file_entry_get_number_of_alternate_data_streams(fileEntry, &numberOfAds, &error) == 1) {
            entry.hasAds = (numberOfAds > 0);
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // Build file path from parent references
        // For simplicity, use path hint if available (attribute_index 0 = first $FILE_NAME)
        size_t pathHintSize = 0;
        if (libfsntfs_file_entry_get_utf8_path_hint_size(fileEntry, 0, &pathHintSize, &error) == 1 && pathHintSize > 0) {
            std::vector<uint8_t> pathBuffer(pathHintSize);
            if (libfsntfs_file_entry_get_utf8_path_hint(fileEntry, 0, pathBuffer.data(), pathHintSize, &error) == 1) {
                entry.filePath = std::string(reinterpret_cast<char*>(pathBuffer.data()));
            }
        }
        libfsntfs_error_free(&error);
        error = nullptr;

        // If no path hint, construct from name
        if (entry.filePath.empty() && !entry.fileName.empty()) {
            entry.filePath = entry.fileName;
        }

        // Insert into database
        if (windowsDb_->insertMftEntry(entry)) {
            processedCount++;
        } else {
            errorCount++;
        }

        // Release file entry
        libfsntfs_file_entry_free(&fileEntry, nullptr);

        // Progress logging every 10000 entries
        if ((i + 1) % 10000 == 0) {
            LOG_INFO("MFT分析: 已处理 " + std::to_string(i + 1) + "/" + std::to_string(maxEntries) + " 条目");
        }
    }

    windowsDb_->commitTransaction();

    // Close MFT metadata file
    libfsntfs_mft_metadata_file_close(mftMetadataFile, nullptr);
    libfsntfs_mft_metadata_file_free(&mftMetadataFile, nullptr);

    LOG_INFO("MFT分析: 完成，成功处理 " + std::to_string(processedCount) + " 条目，"
             + std::to_string(errorCount) + " 个错误");

    AuditLog::instance().log("SYSTEM", "MFT_ANALYSIS_COMPLETE",
        "MFT analysis completed: " + std::to_string(processedCount) + " entries processed");
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
            // Parse XML using pugixml
            pugi::xml_document doc;
            pugi::xml_parse_result result = doc.load_file(extractPath.c_str());

            if (!result) {
                LOG_WARNING("计划任务XML解析失败: " + file.name + " - " + result.description());
                continue;
            }

            ScheduledTaskInfo task;
            task.taskName = file.name;
            task.taskPath = file.path;

            // Get root element (Task)
            pugi::xml_node taskNode = doc.child("Task");
            if (!taskNode) continue;

            // Extract RegistrationInfo
            pugi::xml_node regInfo = taskNode.child("RegistrationInfo");
            if (regInfo) {
                pugi::xml_node authorNode = regInfo.child("Author");
                if (authorNode) task.author = authorNode.text().as_string();

                pugi::xml_node descNode = regInfo.child("Description");
                if (descNode) task.description = descNode.text().as_string();
            }

            // Extract Principals/Principal
            pugi::xml_node principals = taskNode.child("Principals");
            if (principals) {
                pugi::xml_node principal = principals.child("Principal");
                if (principal) {
                    pugi::xml_node userIdNode = principal.child("UserId");
                    if (userIdNode) task.runAs = userIdNode.text().as_string();

                    pugi::xml_node runLevelNode = principal.child("RunLevel");
                    if (runLevelNode) {
                        std::string runLevel = runLevelNode.text().as_string();
                        // Store in description for now
                        if (!task.description.empty()) task.description += " | ";
                        task.description += "RunLevel: " + runLevel;
                    }
                }
            }

            // Extract Settings
            pugi::xml_node settings = taskNode.child("Settings");
            if (settings) {
                pugi::xml_node enabledNode = settings.child("Enabled");
                if (enabledNode) {
                    task.status = enabledNode.text().as_bool(true) ? "Enabled" : "Disabled";
                } else {
                    task.status = "Enabled"; // Default
                }
            } else {
                task.status = "Enabled";
            }

            // Extract Actions
            pugi::xml_node actions = taskNode.child("Actions");
            if (actions) {
                pugi::xml_node exec = actions.child("Exec");
                if (exec) {
                    task.actionType = "Exec";
                    pugi::xml_node cmdNode = exec.child("Command");
                    if (cmdNode) task.actionPath = cmdNode.text().as_string();

                    pugi::xml_node argsNode = exec.child("Arguments");
                    if (argsNode) task.arguments = argsNode.text().as_string();
                }
            }

            // Extract Triggers
            pugi::xml_node triggers = taskNode.child("Triggers");
            if (triggers) {
                // Check for different trigger types
                for (pugi::xml_node trigger = triggers.first_child(); trigger; trigger = trigger.next_sibling()) {
                    std::string triggerName = trigger.name();
                    if (triggerName == "LogonTrigger") {
                        task.triggerType = "Logon";
                    } else if (triggerName == "BootTrigger") {
                        task.triggerType = "Boot";
                    } else if (triggerName == "CalendarTrigger") {
                        task.triggerType = "Calendar";
                        pugi::xml_node startBoundary = trigger.child("StartBoundary");
                        if (startBoundary) {
                            // Parse start boundary time (ISO 8601 format)
                            std::string timeStr = startBoundary.text().as_string();
                            // Store in description for now
                            if (!task.description.empty()) task.description += " | ";
                            task.description += "StartBoundary: " + timeStr;
                        }
                    } else if (triggerName == "TimeTrigger") {
                        task.triggerType = "Time";
                    } else if (triggerName == "IdleTrigger") {
                        task.triggerType = "Idle";
                    } else if (triggerName == "EventTrigger") {
                        task.triggerType = "Event";
                    }

                    if (!task.triggerType.empty()) break; // Use first trigger type found
                }
            }

            // Set last run time from file metadata (use modification time as approximation)
            task.lastRunTime = file.mtime;
            task.nextRunTime = 0; // Would need trigger parsing for accurate value

            // Insert into database
            windowsDb_->insertScheduledTask(task);
            processedCount++;
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
