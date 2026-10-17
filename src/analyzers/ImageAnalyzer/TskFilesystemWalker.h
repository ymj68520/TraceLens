#pragma once

#include <cstdint>
#include <list>
#include <string>
#include <functional>
#include <unordered_map>
#include <tsk/libtsk.h>
#include "ImageAnalyzerDataTypes.h"

// Content MD5 is computed during the walk, while the filesystem handle is
// still open. Files larger than this are left with an empty md5: hashing a
// multi-GB file inline would dominate the extraction window the throughput
// metric is measured on, and duplicates of that size are rare evidence.
inline constexpr int64_t kContentHashMaxBytes = 32LL * 1024 * 1024;

// Callback function type for file processing
// Returns true to continue walking, false to stop
using TskFileCallback = std::function<bool(const FileRecord&)>;

class TskFilesystemWalker {
public:
    TskFilesystemWalker(TSK_IMG_INFO* imgInfo, uint64_t offset);
    ~TskFilesystemWalker();

    // Open filesystem at the specified offset
    bool open();

    // Walk traversable files and invoke callback
    bool walk(TskFileCallback callback);

    // Close filesystem (if opened by this class)
    void close();

    std::string getFsType() const;

private:
    static TSK_WALK_RET_ENUM dirWalkCallback(TSK_FS_FILE* fsFile, const char* path, void* ptr);
    void processFile(TSK_FS_FILE* fsFile, const std::string& path);
    // Lowercase hex MD5 of the whole file, or "" when the read is incomplete.
    std::string hashFileContent(TSK_FS_FILE* fsFile);
    // Whether the file survives the lightweight filter and is worth hashing.
    static bool worthHashing(const std::string& path);

    // Block cache for content hashing. tsk_fs_file_read goes to the image per
    // call, and hashing file-by-file re-reads the same block group once per
    // inode — on a spinning disk that seek cost, not the hash, dominates the
    // lightweight-filter window. Reads within one walk share this cache.
    ssize_t readCached(TSK_FS_FILE* fsFile, int64_t offset, char* dst, size_t len);
    bool loadBlock(TSK_DADDR_T addr);

    TSK_IMG_INFO* imgInfo_;
    TSK_FS_INFO* fsInfo_;
    uint64_t offset_;
    TskFileCallback currentCallback_;

    static constexpr size_t kBlockCacheEntries = 1024;  // 4MB at a 4KB block size
    std::unordered_map<TSK_DADDR_T, std::vector<char>> blockCache_;
    std::list<TSK_DADDR_T> blockCacheOrder_;
};
