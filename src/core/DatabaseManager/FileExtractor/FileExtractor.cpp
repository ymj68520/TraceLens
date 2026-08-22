#include "FileExtractor.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <fstream>
#include <filesystem>
#include <sstream>
#include <algorithm>
#include <cstring>

#ifdef _WIN32
#include <Windows.h>
#endif

namespace fs = std::filesystem;

FileExtractor::FileExtractor(const std::string& imagePath, const std::string& dbPath)
    : imagePath_(imagePath)
    , dbPath_(dbPath)
    , imgInfo_(nullptr) {
}

FileExtractor::~FileExtractor() {
    closeImage();
}

bool FileExtractor::initialize() {
    std::cout << "Initializing file extractor..." << std::endl;
    std::cout << "  Image: " << imagePath_ << std::endl;
    std::cout << "  Database: " << dbPath_ << std::endl;

    // Open database
    dbManager_ = std::make_unique<DatabaseManager>(dbPath_);
    // Database should already exist, just open it
    if (!dbManager_->initialize()) {
        std::cerr << "Error: Cannot open database: " << dbPath_ << std::endl;
        std::cerr << "Please run analysis first to create the database." << std::endl;
        AuditLog::instance().log("SYSTEM", "EXTRACTOR_INIT_FAILED", "Failed to initialize file extractor: " + dbPath_);
        return false;
    }

    // Open image
    if (!openImage()) {
        std::cerr << "Error: Failed to open image" << std::endl;
        return false;
    }

    // Open filesystem
    if (!openFileSystem()) {
        std::cerr << "Error: Failed to open filesystem" << std::endl;
        return false;
    }

    std::cout << "File extractor initialized successfully" << std::endl;
    AuditLog::instance().log("SYSTEM", "EXTRACTOR_INIT", "File extractor initialized: " + imagePath_);
    return true;
}

bool FileExtractor::openImage() {
    TSK_IMG_TYPE_ENUM imgType = TSK_IMG_TYPE_DETECT;

#ifdef _WIN32
    // Windows: Convert UTF-8 to wide char
    int len = MultiByteToWideChar(CP_UTF8, 0, imagePath_.c_str(), -1, nullptr, 0);
    if (len <= 0) return false;

    TSK_TCHAR* imgPathCstr = new TSK_TCHAR[len];
    if (MultiByteToWideChar(CP_UTF8, 0, imagePath_.c_str(), -1, imgPathCstr, len) == 0) {
        delete[] imgPathCstr;
        return false;
    }

    imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    if (!imgInfo_) {
        imgType = TSK_IMG_TYPE_RAW;
        imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    }
    delete[] imgPathCstr;
#else
    // Linux: Use path directly
    const char* imgPathCstr = imagePath_.c_str();
    imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    if (!imgInfo_) {
        imgType = TSK_IMG_TYPE_RAW;
        imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
    }
#endif

    if (!imgInfo_) {
        std::cerr << "Error opening image: " << tsk_error_get() << std::endl;
        return false;
    }

    return true;
}

bool FileExtractor::openFileSystem() {
    // Open EVERY accessible partition's filesystem, not just the first.
    // Records carry partition_num so extractFile() can route inode reads to the
    // correct handle. Without this, multi-partition images read wrong content.
    TSK_VS_INFO* vsInfo = tsk_vs_open(imgInfo_, 0, TSK_VS_TYPE_DETECT);

    if (vsInfo) {
        for (TSK_PNUM_T i = 0; i < vsInfo->part_count; i++) {
            const TSK_VS_PART_INFO* part = tsk_vs_part_get(vsInfo, i);
            if (!part || !(part->flags & TSK_VS_PART_FLAG_ALLOC)) {
                continue;
            }
            TSK_OFF_T offset = part->start * vsInfo->block_size;
            TSK_FS_INFO* fs = tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT);
            if (fs) {
                fsByPartition_[static_cast<int>(i)] = fs;
            } else {
                // TSK could not open this partition. Record the offset in case it
                // is XFS — we will lazily initialize XFSHelper on first access.
                xfsPartitionOffsets_[static_cast<int>(i)] = static_cast<uint64_t>(offset);
            }
        }
        tsk_vs_close(vsInfo);
    }

    // No partition table (or no openable partition): try the image as a single FS.
    if (fsByPartition_.empty() && xfsPartitionOffsets_.empty()) {
        TSK_FS_INFO* fs = tsk_fs_open_img(imgInfo_, 0, TSK_FS_TYPE_DETECT);
        if (fs) {
            fsByPartition_[0] = fs;
        } else {
            // Try whole-image as XFS
            xfsPartitionOffsets_[0] = 0;
        }
    }

    if (fsByPartition_.empty() && xfsPartitionOffsets_.empty()) {
        std::cerr << "Error opening filesystem: " << tsk_error_get() << std::endl;
        return false;
    }

    // If we have at least one open handle OR one potential XFS partition, succeed.
    // XFS partitions will be lazily opened on first read.
    if (!fsByPartition_.empty()) {
        std::cout << "File extractor: " << fsByPartition_.size()
                  << " TSK filesystem(s) opened";
        if (!xfsPartitionOffsets_.empty()) {
            std::cout << ", " << xfsPartitionOffsets_.size()
                      << " partition(s) deferred to XFS fallback";
        }
        std::cout << std::endl;
    } else {
        std::cout << "File extractor: no TSK filesystems opened, "
                  << xfsPartitionOffsets_.size()
                  << " partition(s) will use XFS fallback" << std::endl;
    }

    return true;
}

void FileExtractor::closeImage() {
    for (auto& kv : fsByPartition_) {
        if (kv.second) {
            tsk_fs_close(kv.second);
            kv.second = nullptr;
        }
    }
    fsByPartition_.clear();
    xfsByPartition_.clear();
    xfsPartitionOffsets_.clear();
    if (imgInfo_) {
        tsk_img_close(imgInfo_);
        imgInfo_ = nullptr;
    }
}

TSK_FS_INFO* FileExtractor::fsForPartition(int partitionNum) const {
    auto it = fsByPartition_.find(partitionNum);
    if (it != fsByPartition_.end() && it->second) {
        return it->second;
    }
    // Fallback: older records (partition_num == 0 from pre-migration DBs) or
    // records whose partition we couldn't open. Use the first available handle.
    for (const auto& kv : fsByPartition_) {
        if (kv.second) return kv.second;
    }
    return nullptr;
}

XFSHelper* FileExtractor::xfsForPartition(int partitionNum) {
    // Already initialized?
    auto it = xfsByPartition_.find(partitionNum);
    if (it != xfsByPartition_.end() && it->second) {
        return it->second.get();
    }

    // Do we have a recorded offset for this partition?
    auto offIt = xfsPartitionOffsets_.find(partitionNum);
    if (offIt == xfsPartitionOffsets_.end()) {
        return nullptr;
    }

    // Lazily initialize XFSHelper for this partition
    auto helper = std::make_unique<XFSHelper>(imgInfo_, offIt->second);
    if (!helper->initialize()) {
        std::cerr << "  XFSHelper failed to initialize for partition " << partitionNum
                  << " at offset " << offIt->second << std::endl;
        // Remove from offsets so we don't keep retrying
        xfsPartitionOffsets_.erase(offIt);
        return nullptr;
    }

    XFSHelper* ptr = helper.get();
    xfsByPartition_[partitionNum] = std::move(helper);
    std::cout << "  XFSHelper initialized for partition " << partitionNum
              << " at offset " << offIt->second << std::endl;
    return ptr;
}

std::vector<FileRecord> FileExtractor::searchFiles(const std::string& whereClause) {
    std::vector<FileRecord> results;

    // Include partition_num so extractFile() can route inode reads to the
    // correct filesystem handle (inodes are per-partition and collide across
    // partitions in a multi-partition image).
    std::string sql = "SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5, "
                      "COALESCE(partition_num, 0) "
                      "FROM files WHERE " + whereClause;

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDb(), sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(dbManager_->getDb()) << std::endl;
        return results;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord record;
        record.inode = sqlite3_column_int64(stmt, 0);
        record.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.size = sqlite3_column_int64(stmt, 3);
        record.mtime = sqlite3_column_int64(stmt, 4);
        record.ctime = sqlite3_column_int64(stmt, 5);
        record.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        record.isDeleted = sqlite3_column_int(stmt, 7);
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));
        record.md5 = md5Ptr ? md5Ptr : "";
        record.partitionNum = sqlite3_column_int(stmt, 9);

        // Set defaults for missing fields
        record.atime = record.mtime;
        record.crtime = record.ctime;
        record.isAllocated = 1;
        record.permissions = "0644";
        record.uid = 0;
        record.gid = 0;

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<FileRecord> FileExtractor::searchFilesInTable(const std::string& tableName, const std::string& whereClause) {
    std::vector<FileRecord> results;

    std::string sql = "SELECT inode, name, path, size, mtime, ctime, is_deleted, md5 "
                      "FROM " + tableName + " WHERE " + whereClause;

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDb(), sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(dbManager_->getDb()) << std::endl;
        return results;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord record;
        record.inode = sqlite3_column_int64(stmt, 0);
        record.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.size = sqlite3_column_int64(stmt, 3);
        record.mtime = sqlite3_column_int64(stmt, 4);
        record.ctime = sqlite3_column_int64(stmt, 5);
        record.isDeleted = sqlite3_column_int(stmt, 6);
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        record.md5 = md5Ptr ? md5Ptr : "";
        record.type = "REG";  // Assume regular file
        record.isAllocated = 1;  // Assume allocated

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

bool FileExtractor::matchWildcard(const std::string& filename, const std::string& pattern) {
    // Simple wildcard matching (* and ?)
    size_t fpos = 0, ppos = 0;
    size_t flen = filename.length(), plen = pattern.length();
    size_t starPos = std::string::npos, matchPos = 0;

    while (fpos < flen) {
        if (ppos < plen && (pattern[ppos] == '?' || pattern[ppos] == filename[fpos])) {
            fpos++;
            ppos++;
        } else if (ppos < plen && pattern[ppos] == '*') {
            starPos = ppos++;
            matchPos = fpos;
        } else if (starPos != std::string::npos) {
            ppos = starPos + 1;
            fpos = ++matchPos;
        } else {
            return false;
        }
    }

    while (ppos < plen && pattern[ppos] == '*') {
        ppos++;
    }

    return ppos == plen;
}


// extract* operations live in FileExtractor_Extract.cpp

ssize_t FileExtractor::readFileContent(int64_t inode, char* buffer, size_t size, int partitionNum) {
    TSK_FS_INFO* fs = fsForPartition(partitionNum);
    if (fs) {
        TSK_FS_FILE* fsFile = tsk_fs_file_open_meta(fs, nullptr, inode);
        if (!fsFile) {
            return -1;
        }

        ssize_t bytesRead = tsk_fs_file_read(fsFile, 0, buffer, size,
                                             TSK_FS_FILE_READ_FLAG_NONE);
        tsk_fs_file_close(fsFile);

        return bytesRead;
    }

    // XFS fallback
    XFSHelper* xfs = xfsForPartition(partitionNum);
    if (!xfs) {
        return -1;
    }

    std::vector<uint8_t> fileData;
    if (!xfs->readFileByInode(static_cast<uint64_t>(inode), fileData)) {
        return -1;
    }

    size_t toCopy = (size < fileData.size()) ? size : fileData.size();
    memcpy(buffer, fileData.data(), toCopy);
    return static_cast<ssize_t>(toCopy);
}

bool FileExtractor::createDirectories(const std::string& path) {
    try {
        fs::path p(path);
        fs::path dir = p.parent_path();

        if (!dir.empty() && !fs::exists(dir)) {
            fs::create_directories(dir);
        }
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Error creating directories: " << e.what() << std::endl;
        return false;
    }
}

std::string FileExtractor::generateOutputPath(const std::string& outputDir, const FileRecord& record) {
    std::string safeError;
    auto safePath = FileExtractor::resolveSafeOutputPath(
        fs::path(outputDir), record.path, &safeError);
    if (!safePath) {
        return {};
    }
    fs::path outPath = *safePath;

    std::string pathStr = outPath.string();
    
    // Only resolve conflicts for deleted files map to same path (since inodes differ but path persists)
    // For allocated files, we assume path uniqueness (or we want to update the file at that path)
    if (record.isDeleted && fs::exists(pathStr)) {
        // Append inode to make unique
        fs::path p(pathStr);
        std::string stem = p.stem().string();
        std::string ext = p.extension().string();
        p.replace_filename(stem + "_" + std::to_string(record.inode) + ext);
        pathStr = p.string();
    }

    return pathStr;
}
