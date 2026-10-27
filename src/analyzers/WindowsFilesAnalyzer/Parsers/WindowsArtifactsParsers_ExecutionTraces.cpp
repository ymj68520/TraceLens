#include "../Common/WindowsArtifactDecoding.h"
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
// Execution-trace parsers: prefetch / lnk / jumplist / recycle-bin.
// Split from WindowsArtifactsParsers.cpp. Methods belong to
// WindowsFilesAnalyzer (WindowsFilesAnalyzer.h).

void WindowsFilesAnalyzer::analyzePrefetchFiles() {
    std::cout << "Analyzing Prefetch files..." << std::endl;
    
    // Prefetch files are in Windows/Prefetch/*.pf
    std::vector<FileRecord> pfFiles = queryFilesByPattern("%/Windows/Prefetch/%.pf");
    
    for (const auto& file : pfFiles) {
        std::string extractPath = getExtractPath("prefetch/" + std::to_string(file.partitionNum) + "_" + std::to_string(file.inode) + "_" + file.name);
        
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            PrefetchInfo info = parsePrefetchFile(extractPath);
            info.filePath = file.path; // Evidence path, never the temporary extraction name.
            // Keep an explicit outcome even when execution facts are unknown.
            if (!info.filePath.empty()) {
                if (file.crtime != 0) info.creationTime = file.crtime;
                if (!windowsDb_->insertPrefetchInfo(info)) throw std::runtime_error("PREFETCH_DATABASE_WRITE_FAILED");
                if (!windowsDb_->recordParserOutcome(file.path,"libscca",info.parseStatus,info.parseError,
                    info.runCount.has_value()?std::optional<int64_t>(1):std::nullopt))
                    throw std::runtime_error("PREFETCH_OUTCOME_WRITE_FAILED");
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

        info.parseStatus = parser.getStatus();
        info.parseError = parser.getLastError();
        info.parserVersion = parser.getParserVersion();
        return info;
    }

    // Extract parsed information
    info.executableName = parser.getExecutableName();
    info.executablePath = parser.getExecutablePath();
    info.prefetchHash = parser.getPrefetchHash();
    info.runCount = parser.getRunCount();
    info.allRunTimes = parser.getAllRunTimes();
    info.rawRunTimes = parser.getRawRunTimes();
    if (parser.hasLastRunTime()) info.lastRunTime = parser.getLastRunTime();
    info.parseStatus = parser.getStatus();
    info.parseError = parser.getLastError();
    info.parserVersion = parser.getParserVersion();
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
        
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
    // Only successful parsing establishes an artifact row.

    // Use the new LnkParser
    LnkParser parser(lnkPath);
    if (!parser.parse()) {
        // Parsing failed, log error
        AuditLog::instance().log("WARNING", "LNK_PARSE_FAILED",
            "Failed to parse LNK file: " + lnkPath + " - " + parser.getLastError());
        if (windowsDb_) windowsDb_->recordParserOutcome(lnkPath,"lnk","error","LNK_PARSE_FAILED");
        return info; // Unknown fields are not persisted as an artifact.
    }

    // Extract all parsed information
    info.lnkPath = lnkPath;
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
        
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            auto entries = parseRecycleBin(extractPath);
            windowsDb_->recordParserOutcome(file.path,"recyclebin:v2",entries.empty()?"error":"ok",entries.empty()?"RECYCLE_RECORD_INVALID":"",entries.size());
            for (auto entry : entries) {
                entry.recycleFilePath=file.path;
                const auto parent=fs::path(file.path).parent_path().filename().string();
                if(parent.rfind("S-1-",0)==0)entry.userSid=parent;
                windowsDb_->insertRecycleBinEntry(entry);
            }
        }
    }
}

std::vector<RecycleBinEntry> WindowsFilesAnalyzer::parseRecycleBin(const std::string& recycleBinPath) {
    std::ifstream file(recycleBinPath,std::ios::binary);
    if(!file)return {};
    file.seekg(0,std::ios::end);const auto length=file.tellg();file.seekg(0);
    if(length<24 || length>65564)return {};
    std::vector<char> bytes(static_cast<size_t>(length));
    if(!file.read(bytes.data(),bytes.size()))return {};
    try{return {forensics::windows_decoding::recycle(bytes,recycleBinPath)};}
    catch(const std::invalid_argument& error){
        std::cerr<<"回收站记录无法完整解析："<<error.what()<<std::endl;return {};
    }
}

// --- Other Analyzers ---

