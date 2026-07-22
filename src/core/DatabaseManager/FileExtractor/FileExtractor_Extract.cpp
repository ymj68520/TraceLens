#include "FileExtractor.h"
#include "AuditLog/AuditLog.h"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>

#ifdef _WIN32
#include <Windows.h>
#else
#include <unistd.h>
#endif

namespace fs = std::filesystem;

namespace {

std::string columnText(sqlite3_stmt* statement, int column) {
    const auto* value = reinterpret_cast<const char*>(sqlite3_column_text(statement, column));
    return value ? value : "";
}

bool atomicReplace(const fs::path& temporaryPath, const fs::path& finalPath,
                   std::string& error) {
#ifdef _WIN32
    if (MoveFileExW(temporaryPath.wstring().c_str(), finalPath.wstring().c_str(),
                    MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        return true;
    }
    error = "Cannot replace output file: " + std::to_string(GetLastError());
    return false;
#else
    std::error_code ec;
    fs::rename(temporaryPath, finalPath, ec);
    if (!ec) {
        return true;
    }
    error = "Cannot replace output file: " + ec.message();
    return false;
#endif
}

fs::path temporaryPathFor(const fs::path& finalPath, const FileRecord& record) {
    static std::atomic_uint64_t sequence{0};
    const auto nonce = static_cast<uint64_t>(
        std::chrono::steady_clock::now().time_since_epoch().count());
#ifdef _WIN32
    const auto processId = static_cast<uint64_t>(GetCurrentProcessId());
#else
    const auto processId = static_cast<uint64_t>(getpid());
#endif
    return finalPath.parent_path() /
           (".tracelens-textdump-tmp-" + std::to_string(record.partitionNum) + "-" +
            std::to_string(record.inode) + "-" + std::to_string(processId) + "-" +
            std::to_string(nonce) + "-" + std::to_string(sequence.fetch_add(1)));
}

bool inspectOrCreateDirectory(const fs::path& directory, const std::string& context,
                              std::string& error) {
    std::error_code ec;
    const fs::file_status status = fs::symlink_status(directory, ec);
    if (!ec) {
        if (fs::is_symlink(status)) {
            error = context + " is a symlink: " + directory.string();
            return false;
        }
        if (!fs::is_directory(status)) {
            error = context + " is not a directory: " + directory.string();
            return false;
        }
        return true;
    }

    if (ec != std::errc::no_such_file_or_directory) {
        error = "Cannot inspect " + context + " " + directory.string() + ": " +
                ec.message();
        return false;
    }

    ec.clear();
    if (!fs::create_directory(directory, ec)) {
        if (!ec) {
            const fs::file_status createdStatus = fs::symlink_status(directory, ec);
            if (!ec && fs::is_directory(createdStatus) && !fs::is_symlink(createdStatus)) {
                return true;
            }
        }
        error = "Cannot create " + context + " " + directory.string();
        if (ec) {
            error += ": " + ec.message();
        }
        return false;
    }
    return true;
}

bool prepareOutputRoot(const fs::path& outputRoot, std::string* error) {
    std::error_code ec;
    const fs::path absoluteRoot = fs::absolute(outputRoot, ec).lexically_normal();
    if (ec) {
        if (error) {
            *error = "Cannot make output root absolute: " + ec.message();
        }
        return false;
    }

    fs::path current = absoluteRoot.root_path();
    if (current.empty()) {
        if (error) {
            *error = "Output root has no filesystem root: " + outputRoot.string();
        }
        return false;
    }

    std::string localError;
    if (!inspectOrCreateDirectory(current, "Output root component", localError)) {
        if (error) {
            *error = std::move(localError);
        }
        return false;
    }
    for (const auto& component : absoluteRoot.relative_path()) {
        current /= component;
        if (!inspectOrCreateDirectory(current, "Output root component", localError)) {
            if (error) {
                *error = std::move(localError);
            }
            return false;
        }
    }
    return true;
}

bool validateTemporaryExtraction(const fs::path& temporaryPath,
                                 const FileRecord& record,
                                 std::string& error) {
    std::error_code ec;
    const uintmax_t actualBytes = fs::file_size(temporaryPath, ec);
    if (ec) {
        error = "Cannot stat temporary output: " + ec.message();
        return false;
    }
    if (record.size < 0) {
        error = "Temporary output has invalid expected size " +
                std::to_string(record.size) + " (actual " +
                std::to_string(actualBytes) + ")";
        return false;
    }

    const uintmax_t expectedBytes = static_cast<uintmax_t>(record.size);
    if (actualBytes != expectedBytes) {
        error = "Temporary output size mismatch: expected " +
                std::to_string(expectedBytes) + ", actual " +
                std::to_string(actualBytes);
        return false;
    }
    return true;
}

bool prepareOutputParent(const fs::path& outputRoot, const fs::path& finalPath,
                         std::string& error) {
    fs::path current = outputRoot;
    const fs::path relativeParent = finalPath.lexically_relative(outputRoot).parent_path();
    if (relativeParent.empty() || relativeParent == ".") {
        return true;
    }
    for (const auto& component : relativeParent) {
        current /= component;
        if (!inspectOrCreateDirectory(current, "Output path component", error)) {
            return false;
        }
    }
    return true;
}

} // namespace

// File extraction operations. Split from FileExtractor.cpp.

std::vector<FileRecord> FileExtractor::queryRegularFilesOrdered(sqlite3* db,
                                                                 std::string* error) {
    if (error) {
        error->clear();
    }
    if (!db) {
        if (error) {
            *error = "File extractor database is not initialized";
        }
        return {};
    }

    const char* sql = R"SQL(
        SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5,
               COALESCE(partition_num, 0)
        FROM files
        WHERE type = 'REG'
          AND is_deleted = 0
          AND COALESCE(is_allocated, 1) = 1
        ORDER BY path COLLATE BINARY ASC,
                 COALESCE(partition_num, 0) ASC,
                 inode ASC
    )SQL";

    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) != SQLITE_OK) {
        if (error) {
            *error = sqlite3_errmsg(db);
        }
        return {};
    }

    std::vector<FileRecord> records;
    int stepResult = SQLITE_ROW;
    while ((stepResult = sqlite3_step(statement)) == SQLITE_ROW) {
        FileRecord record{};
        record.inode = sqlite3_column_int64(statement, 0);
        record.name = columnText(statement, 1);
        record.path = columnText(statement, 2);
        record.size = sqlite3_column_int64(statement, 3);
        record.mtime = sqlite3_column_int64(statement, 4);
        record.ctime = sqlite3_column_int64(statement, 5);
        record.type = columnText(statement, 6);
        record.isDeleted = sqlite3_column_int(statement, 7);
        record.md5 = columnText(statement, 8);
        record.partitionNum = sqlite3_column_int(statement, 9);
        record.atime = record.mtime;
        record.crtime = record.ctime;
        record.isAllocated = 1;
        record.permissions = "0644";
        record.uid = 0;
        record.gid = 0;
        records.push_back(std::move(record));
    }

    if (stepResult != SQLITE_DONE && error) {
        *error = sqlite3_errmsg(db);
    }
    sqlite3_finalize(statement);
    return records;
}

std::vector<FileRecord> FileExtractor::listRegularFilesOrdered(std::string* error) {
    if (!dbManager_ || !dbManager_->getDb()) {
        if (error) {
            *error = "File extractor database is not initialized";
        }
        return {};
    }
    return queryRegularFilesOrdered(dbManager_->getDb(), error);
}

std::optional<fs::path> FileExtractor::resolveSafeOutputPath(
        const fs::path& outputRoot, const std::string& imagePath,
        std::string* error) {
    if (error) {
        error->clear();
    }

    if (!prepareOutputRoot(outputRoot, error)) {
        return std::nullopt;
    }

    fs::path relative = fs::path(imagePath).relative_path().lexically_normal();
    if (relative.empty() || relative == ".") {
        if (error) {
            *error = "Image path does not identify a file";
        }
        return std::nullopt;
    }
    for (const auto& component : relative) {
        if (component == "..") {
            if (error) {
                *error = "Image path escapes the output root: " + imagePath;
            }
            return std::nullopt;
        }
    }

    std::error_code ec;
    fs::path current = outputRoot;
    for (const auto& component : relative.parent_path()) {
        current /= component;
        const auto status = fs::symlink_status(current, ec);
        if (!ec && fs::is_symlink(status)) {
            if (error) {
                *error = "Output path contains a symlink: " + current.string();
            }
            return std::nullopt;
        }
        if (!ec && !fs::is_directory(status)) {
            if (error) {
                *error = "Output path component is not a directory: " + current.string();
            }
            return std::nullopt;
        }
        if (ec && ec != std::errc::no_such_file_or_directory) {
            if (error) {
                *error = "Cannot inspect output path component " + current.string() +
                         ": " + ec.message();
            }
            return std::nullopt;
        }
        ec.clear();
    }
    const fs::path result = outputRoot / relative;
    const auto finalStatus = fs::symlink_status(result, ec);
    if (!ec && fs::is_symlink(finalStatus)) {
        if (error) {
            *error = "Output file is a symlink: " + result.string();
        }
        return std::nullopt;
    }
    if (ec && ec != std::errc::no_such_file_or_directory) {
        if (error) {
            *error = "Cannot inspect output file " + result.string() + ": " +
                     ec.message();
        }
        return std::nullopt;
    }
    return result;
}

FileExtractor::AtomicExtractionResult FileExtractor::extractRecordAtomically(
        const FileRecord& record, const fs::path& outputRoot) {
    AtomicExtractionResult result;
    auto finalPath = resolveSafeOutputPath(outputRoot, record.path, &result.error);
    if (!finalPath) {
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }
    result.output_path = *finalPath;

    std::error_code ec;
    const auto finalStatus = fs::symlink_status(*finalPath, ec);
    if (!ec && fs::is_regular_file(finalStatus)) {
        result.previous_bytes = fs::file_size(*finalPath, ec);
        if (!ec && record.size >= 0 &&
            result.previous_bytes == static_cast<uintmax_t>(record.size)) {
            result.status = AtomicExtractionStatus::Reused;
            result.output_bytes = result.previous_bytes;
            return result;
        }
    }
    ec.clear();

    if (!prepareOutputParent(outputRoot, *finalPath, result.error)) {
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }

    const fs::path temporaryPath = temporaryPathFor(*finalPath, record);
    if (!extractFile(record, temporaryPath.string(), true, nullptr)) {
        fs::remove(temporaryPath, ec);
        result.status = AtomicExtractionStatus::Failed;
        result.error = "Failed to extract " + record.path;
        return result;
    }
    if (!validateTemporaryExtraction(temporaryPath, record, result.error)) {
        fs::remove(temporaryPath, ec);
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }
    if (!atomicReplace(temporaryPath, *finalPath, result.error)) {
        fs::remove(temporaryPath, ec);
        result.status = AtomicExtractionStatus::Failed;
        return result;
    }
    result.status = AtomicExtractionStatus::Extracted;
    result.output_bytes = fs::file_size(*finalPath, ec);
    if (ec) {
        result.status = AtomicExtractionStatus::Failed;
        result.error = "Cannot stat extracted file: " + ec.message();
    }
    return result;
}

int FileExtractor::extractByName(const std::string& pattern, const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Searching files matching patterns: " << pattern << std::endl;

    // Parse patterns (comma-separated)
    std::vector<std::string> patterns;
    std::stringstream ss(pattern);
    std::string item;
    while (std::getline(ss, item, ',')) {
        // Trim whitespace
        item.erase(0, item.find_first_not_of(" \t"));
        item.erase(item.find_last_not_of(" \t") + 1);
        if (!item.empty()) {
            patterns.push_back(item);
        }
    }

    if (patterns.empty()) {
        return 0;
    }

    // Get all files from database
    auto files = searchFiles("type='REG' AND is_allocated=1");

    std::vector<FileRecord> matches;
    for (const auto& file : files) {
        bool matched = false;
        for (const auto& p : patterns) {
            // Check if it's an exact path match or a wildcard filename match
            if (file.path == p || matchWildcard(file.name, p)) {
                matched = true;
                break;
            }
        }
        if (matched) {
            matches.push_back(file);
        }
    }

    std::cout << "Found " << matches.size() << " matching files" << std::endl;

    if (matches.empty()) {
        return 0;
    }

    // Extract each file
    int extracted = 0;
    for (const auto& file : matches) {
        std::string outputPath = generateOutputPath(outputDir, file);
        std::cout << "Extracting: " << file.path << " -> " << outputPath << std::endl;

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        } else {
            std::cerr << "  Failed to extract: " << file.path << std::endl;
        }
    }

    return extracted;
}

int FileExtractor::extractByExtension(const std::string& extensions, const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Searching files with extensions: " << extensions << std::endl;

    // Parse extensions
    std::vector<std::string> extList;
    std::stringstream ss(extensions);
    std::string ext;
    while (std::getline(ss, ext, ',')) {
        // Trim whitespace
        ext.erase(0, ext.find_first_not_of(" \t"));
        ext.erase(ext.find_last_not_of(" \t") + 1);
        // Ensure leading dot
        if (!ext.empty() && ext[0] != '.') {
            ext = "." + ext;
        }
        extList.push_back(ext);
    }

    // Build SQL WHERE clause
    std::stringstream whereClause;
    whereClause << "type='REG' AND is_allocated=1 AND (";
    for (size_t i = 0; i < extList.size(); i++) {
        if (i > 0) whereClause << " OR ";
        whereClause << "name LIKE '%" << extList[i] << "'";
    }
    whereClause << ")";

    auto files = searchFiles(whereClause.str());
    std::cout << "Found " << files.size() << " matching files" << std::endl;

    if (files.empty()) {
        return 0;
    }

    // Extract each file
    int extracted = 0;
    for (const auto& file : files) {
        std::string outputPath = generateOutputPath(outputDir, file);
        std::cout << "Extracting: " << file.path << " -> " << outputPath << std::endl;

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        } else {
            std::cerr << "  Failed to extract: " << file.path << std::endl;
        }
    }

    return extracted;
}

int FileExtractor::extractAll(const std::string& outputDir, bool includeDeleted, bool overwrite, int* skippedCount) {
    std::cout << "Extracting all files..." << std::endl;

    // Extract from main files table
    std::string whereClause = "type = 'REG'";
    if (!includeDeleted) {
        whereClause += " AND is_deleted=0";
    }

    auto files = searchFiles(whereClause);
    std::cout << "Found " << files.size() << " files to extract" << std::endl;

    if (files.empty()) {
        return 0;
    }

    // Extract each file
    int extracted = 0;
    for (size_t i = 0; i < files.size(); i++) {
        const auto& file = files[i];
        std::string outputPath = generateOutputPath(outputDir, file);

        if (i < 10 || i % 50 == 0) {
            std::cout << "Extracting [" << (i + 1) << "/" << files.size() << "]: "
                      << file.path << std::endl;
        }

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        }
    }

    return extracted;
}

int FileExtractor::extractDeleted(const std::string& outputDir, bool overwrite, int* skippedCount) {
    std::cout << "Extracting deleted files (Metadata Recovery)..." << std::endl;

    // files where is_deleted = 1
    std::string whereClause = "is_deleted=1";

    auto files = searchFiles(whereClause);
    std::cout << "Found " << files.size() << " deleted files to recover" << std::endl;

    if (files.empty()) {
        return 0;
    }

    int extracted = 0;
    for (size_t i = 0; i < files.size(); i++) {
        const auto& file = files[i];
        std::string outputPath = generateOutputPath(outputDir, file);
        
        // Add "recovered_" prefix or similar if needed? 
        // No, keep original name structure, but maybe ensure outputDir is distinct.
        
        if (i < 10 || i % 50 == 0) {
            std::cout << "Recovering [" << (i + 1) << "/" << files.size() << "]: " 
                      << file.path << std::endl;
        }

        if (extractFile(file, outputPath, overwrite, skippedCount)) {
            extracted++;
        } else {
             std::cerr << "  Failed to recover: " << file.path << " (Content might be overwritten)" << std::endl;
        }
    }

    return extracted;
}

bool FileExtractor::extractFileByInode(int64_t inode, const std::string& outputPath, int partitionNum) {
    auto files = searchFiles("inode=" + std::to_string(inode));
    if (files.empty()) {
        std::cerr << "Error: File with inode " << inode << " not found" << std::endl;
        return false;
    }

    // When the caller supplies a valid partitionNum, pick the matching record
    // directly — this avoids the ambiguity of inode collisions across partitions.
    const FileRecord* chosen = nullptr;
    if (partitionNum >= 0) {
        for (const auto& f : files) {
            if (f.partitionNum == partitionNum) {
                chosen = &f;
                break;
            }
        }
    }

    // Fallback: heuristic — pick the record whose partition we actually have
    // an open handle for (avoids reading the wrong partition's content).
    if (!chosen) {
        for (const auto& f : files) {
            if (fsByPartition_.find(f.partitionNum) != fsByPartition_.end()) {
                chosen = &f;
                break;
            }
        }
    }
    if (!chosen) {
        chosen = &files[0];  // last fallback: best-effort with first record
    }

    // Single file extraction implies overwrite intent usually
    return extractFile(*chosen, outputPath, true, nullptr);
}

bool FileExtractor::extractFileByPath(const std::string& filePath, const std::string& outputPath) {
    // Use parameterized query to prevent SQL injection
    std::vector<FileRecord> results;

    std::string sql = "SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5, "
                      "COALESCE(partition_num, 0) "
                      "FROM files WHERE path = ?";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(dbManager_->getDb(), sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(dbManager_->getDb()) << std::endl;
        return false;
    }

    sqlite3_bind_text(stmt, 1, filePath.c_str(), -1, SQLITE_STATIC);

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

    if (results.empty()) {
        std::cerr << "Error: File with path " << filePath << " not found" << std::endl;
        return false;
    }

    return extractFile(results[0], outputPath, true, nullptr);
}

bool FileExtractor::extractFile(const FileRecord& record, const std::string& outputPath, bool overwrite, int* skippedCount) {
    // Skip directories
    if (record.type == "DIR") {
        return false;
    }
    
    // Check if file exists
    if (fs::exists(outputPath)) {
        if (!overwrite) {
            // Check if size matches
            try {
                if (fs::file_size(outputPath) == static_cast<uintmax_t>(record.size)) {
                    // File exists and size matches - skip
                    if (skippedCount) {
                        (*skippedCount)++;
                    }
                    return true; // Treat as success
                }
            } catch (const std::exception& e) {
                // If checking size fails, proceed to overwrite attempt
            }
        }
    }

    // Skip empty files (create empty file)
    if (record.size == 0) {
        if (!createDirectories(outputPath)) {
            return false;
        }
        std::ofstream ofs(outputPath, std::ios::binary);
        ofs.flush();
        return ofs.good();
    }

    // Read file content using TSK. Route to the filesystem handle for this
    // file's partition so inode reads don't hit the wrong partition.
    TSK_FS_INFO* fs = fsForPartition(record.partitionNum);

    if (fs) {
        // --- TSK path (ext4, NTFS, FAT, etc.) ---
        TSK_FS_FILE* fsFile = tsk_fs_file_open_meta(fs, nullptr, record.inode);
        if (!fsFile) {
            std::cerr << "Error: Cannot open file inode " << record.inode
                      << " (part " << record.partitionNum << ", fs "
                      << tsk_fs_type_toname(fs->ftype) << "): " << tsk_error_get() << std::endl;
            return false;
        }

        // Create output directory
        if (!createDirectories(outputPath)) {
            tsk_fs_file_close(fsFile);
            return false;
        }

        // Build atomic temp output path first so partial writes do not
        // leave corrupt final files around extraction directories.
        std::error_code ec;
        const auto finalPath = std::filesystem::path(outputPath);
        const auto tempPath = temporaryPathFor(finalPath, record);

        // Read and write file content atomically.
        std::ofstream ofs(tempPath, std::ios::binary);
        if (!ofs) {
            std::cerr << "Error: Cannot create temporary output: " << tempPath << std::endl;
            tsk_fs_file_close(fsFile);
            return false;
        }

        const size_t BUFFER_SIZE = 1024 * 1024; // 1MB buffer
        std::unique_ptr<char[]> buffer(new char[BUFFER_SIZE]);
        TSK_OFF_T offset = 0;
        TSK_OFF_T remaining = record.size;
        bool readBySizeFailed = false;

        while (remaining > 0) {
            size_t toRead = static_cast<size_t>((remaining > BUFFER_SIZE) ? BUFFER_SIZE : remaining);
            ssize_t bytesRead = 0;
            if (!readBySizeFailed) {
                bytesRead = tsk_fs_file_read(fsFile, offset, buffer.get(), toRead,
                                             TSK_FS_FILE_READ_FLAG_NONE);
            }
            if (bytesRead < 0) {
                std::cerr << "Warning: file read by size failed at offset " << offset
                          << " for " << outputPath << ", switching to 1MB chunk fallback" << std::endl;
                readBySizeFailed = true;
                remaining = record.size;
                offset = 0;
                continue;
            }
            if (bytesRead == 0) {
                if (readBySizeFailed) {
                    break;
                }
                std::cerr << "Warning: unexpected EOF at offset " << offset
                          << " for " << outputPath << std::endl;
                break;
            }

            uint64_t outLenU64 = static_cast<uint64_t>(bytesRead);
            size_t outLen = readBySizeFailed
                ? (outLenU64 < static_cast<uint64_t>(BUFFER_SIZE)
                   ? static_cast<size_t>(bytesRead) : BUFFER_SIZE)
                : static_cast<size_t>(bytesRead);
            std::streamsize writeLen = static_cast<std::streamsize>(outLen);
            if (static_cast<uint64_t>(outLen) != outLenU64) {
                std::cerr << "Error: write length overflow for " << outputPath << std::endl;
                break;
            }

            ofs.write(buffer.get(), writeLen);
            if (!ofs) {
                std::cerr << "Error writing temporary output: " << tempPath << std::endl;
                break;
            }
            if (!readBySizeFailed) {
                offset += writeLen;
                remaining -= writeLen;
            } else {
                remaining = record.size;
                offset = 0;
            }
        }

        ofs.flush();
        const bool writeSucceeded = ofs.good();
        ofs.close();
        tsk_fs_file_close(fsFile);

        if (!writeSucceeded || remaining != 0) {
            std::error_code rmEc;
            std::filesystem::remove(tempPath, rmEc);
            return false;
        }

        std::string replaceError;
        if (!atomicReplace(tempPath, finalPath, replaceError)) {
            std::cerr << "Error: cannot finalize extracted file " << outputPath
                      << ": " << replaceError << std::endl;
            std::error_code rmEc;
            std::filesystem::remove(tempPath, rmEc);
            return false;
        }

        return true;

    } else {
        // --- XFS fallback path (TSK cannot parse XFS) ---
        XFSHelper* xfs = xfsForPartition(record.partitionNum);
        if (!xfs) {
            std::cerr << "Error: No TSK or XFS handle for partition " << record.partitionNum
                      << " (inode " << record.inode << ")" << std::endl;
            return false;
        }

        std::vector<uint8_t> fileData;
        if (!xfs->readFileByInode(static_cast<uint64_t>(record.inode), fileData)) {
            std::cerr << "Error: XFS readFileByInode failed for inode " << record.inode
                      << " (partition " << record.partitionNum << ")" << std::endl;
            return false;
        }

        const auto finalXfsPath = std::filesystem::path(outputPath);
        const auto tempXfsPath = temporaryPathFor(finalXfsPath, record);
        if (!createDirectories(outputPath)) {
            return false;
        }

        std::ofstream ofs(tempXfsPath, std::ios::binary);
        if (!ofs) {
            std::cerr << "Error: Cannot create temporary output: " << tempXfsPath << std::endl;
            return false;
        }

        ofs.write(reinterpret_cast<const char*>(fileData.data()), fileData.size());
        ofs.flush();
        const bool writeSucceeded = ofs.good();
        ofs.close();

        if (!writeSucceeded) {
            std::error_code rmEc;
            std::filesystem::remove(tempXfsPath, rmEc);
            return false;
        }

        std::string replaceError;
        if (!atomicReplace(tempXfsPath, finalXfsPath, replaceError)) {
            std::cerr << "Error: cannot finalize XFS extracted file " << outputPath
                      << ": " << replaceError << std::endl;
            std::error_code rmEc;
            std::filesystem::remove(tempXfsPath, rmEc);
            return false;
        }

        return true;
    }
}
