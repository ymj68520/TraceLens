#include "TskFilesystemWalker.h"
#include <openssl/md5.h>
#include <algorithm>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>

TskFilesystemWalker::TskFilesystemWalker(TSK_IMG_INFO* imgInfo, uint64_t offset)
    : imgInfo_(imgInfo), fsInfo_(nullptr), offset_(offset) {
}

TskFilesystemWalker::~TskFilesystemWalker() {
    close();
}

bool TskFilesystemWalker::open() {
    if (!imgInfo_) return false;

    // Open filesystem
    fsInfo_ = tsk_fs_open_img(imgInfo_, offset_, TSK_FS_TYPE_DETECT);
    if (!fsInfo_) {
        // Only print error if it's NOT a "partition not found" type strict error, 
        // effectively we let the caller handle failure logic.
        return false;
    }
    return true;
}

void TskFilesystemWalker::close() {
    if (fsInfo_) {
        tsk_fs_close(fsInfo_);
        fsInfo_ = nullptr;
    }
}

std::string TskFilesystemWalker::getFsType() const {
    if (!fsInfo_) return "Unknown";
    return tsk_fs_type_toname(fsInfo_->ftype);
}

bool TskFilesystemWalker::walk(TskFileCallback callback) {
    if (!fsInfo_) return false;

    currentCallback_ = callback;

    int result = tsk_fs_dir_walk(fsInfo_, fsInfo_->root_inum,
        static_cast<TSK_FS_DIR_WALK_FLAG_ENUM>(
            TSK_FS_DIR_WALK_FLAG_RECURSE | TSK_FS_DIR_WALK_FLAG_ALLOC | 
            TSK_FS_DIR_WALK_FLAG_UNALLOC),
        dirWalkCallback, this);

    return (result == 0);
}

TSK_WALK_RET_ENUM TskFilesystemWalker::dirWalkCallback(TSK_FS_FILE* fsFile, const char* path, void* ptr) {
    TskFilesystemWalker* walker = static_cast<TskFilesystemWalker*>(ptr);

    if (fsFile && fsFile->name) {
        // Construct full path. TSK's `path` is the directory path relative to
        // the filesystem root and may or may not begin with '/'. Normalise to an
        // absolute path (leading '/') so downstream consumers (Linux/Windows
        // analyzers querying `path LIKE '/var/log/%'`) can match consistently.
        std::string dir = path ? path : "";
        std::string fullPath = dir + fsFile->name->name;
        if (fullPath.empty() || fullPath[0] != '/') {
            fullPath = "/" + fullPath;
        }

        // Skip . and ..
        if (std::string(fsFile->name->name) == "." || std::string(fsFile->name->name) == "..") {
            return TSK_WALK_CONT;
        }

        walker->processFile(fsFile, fullPath);
    }

    return TSK_WALK_CONT;
}

void TskFilesystemWalker::processFile(TSK_FS_FILE* fsFile, const std::string& path) {
    if (!fsFile->meta) return;

    FileRecord record;
    record.inode = fsFile->name->meta_addr;
    record.name = fsFile->name->name;
    record.path = path;
    record.size = fsFile->meta->size;
    record.atime = fsFile->meta->atime;
    record.mtime = fsFile->meta->mtime;
    record.ctime = fsFile->meta->ctime;
    record.crtime = fsFile->meta->crtime;
    
    // Type mapping
    switch (fsFile->meta->type) {
    case TSK_FS_META_TYPE_REG: record.type = "REG"; break;
    case TSK_FS_META_TYPE_DIR: record.type = "DIR"; break;
    case TSK_FS_META_TYPE_LNK: record.type = "LNK"; break;
    case TSK_FS_META_TYPE_FIFO: record.type = "FIFO"; break;
    case TSK_FS_META_TYPE_SOCK: record.type = "SOCK"; break;
    default: record.type = "OTHER"; break;
    }

    record.isDeleted = (fsFile->name->flags & TSK_FS_NAME_FLAG_UNALLOC) ? 1 : 0;
    record.isAllocated = (fsFile->meta->flags & TSK_FS_META_FLAG_ALLOC) ? 1 : 0;
    record.uid = fsFile->meta->uid;
    record.gid = fsFile->meta->gid;

    // Permissions
    std::ostringstream perms;
    perms << std::oct << fsFile->meta->mode;
    record.permissions = perms.str();

    // Only files the lightweight filter keeps, and only up to the cap.
    // Hashing the low-value bulk (the >=70% the scene rules reject) means
    // reading all of it, which is exactly the data the filter exists to drop;
    // on a spinning disk that read, not the hash, dominates the filter window.
    if (record.type == "REG" && record.size > 0 && record.size <= kContentHashMaxBytes
        && worthHashing(record.path)) {
        record.md5 = hashFileContent(fsFile);
    }

    // Invoke user callback
    if (currentCallback_) {
        currentCallback_(record);
    }
}

bool TskFilesystemWalker::loadBlock(TSK_DADDR_T addr) {
    auto existing = blockCache_.find(addr);
    if (existing != blockCache_.end()) {
        blockCacheOrder_.splice(blockCacheOrder_.begin(), blockCacheOrder_,
                                std::find(blockCacheOrder_.begin(), blockCacheOrder_.end(), addr));
        return true;
    }

    const size_t blockSize = fsInfo_->block_size;
    std::vector<char> block(blockSize);
    const ssize_t got = tsk_fs_read_block(fsInfo_, addr, block.data(), blockSize);
    if (got <= 0) {
        return false;
    }
    block.resize(static_cast<size_t>(got));

    if (blockCache_.size() >= kBlockCacheEntries && !blockCacheOrder_.empty()) {
        blockCache_.erase(blockCacheOrder_.back());
        blockCacheOrder_.pop_back();
    }
    blockCache_.emplace(addr, std::move(block));
    blockCacheOrder_.push_front(addr);
    return true;
}

ssize_t TskFilesystemWalker::readCached(TSK_FS_FILE* fsFile, int64_t offset,
                                        char* dst, size_t len) {
    const TSK_FS_ATTR* attr = tsk_fs_file_attr_get_type(
        fsFile, TSK_FS_ATTR_TYPE_DEFAULT, 0, 1);
    // Resident NTFS data and other non-run storage: no block address to cache.
    if (!attr || (attr->flags & TSK_FS_ATTR_RES) || attr->nrd.run == nullptr) {
        return tsk_fs_file_read(fsFile, offset, dst, len, TSK_FS_FILE_READ_FLAG_NONE);
    }

    const size_t blockSize = fsInfo_->block_size;
    size_t filled = 0;
    while (filled < len) {
        const int64_t pos = offset + static_cast<int64_t>(filled);
        const auto fileBlock = static_cast<TSK_DADDR_T>(pos / static_cast<int64_t>(blockSize));
        const size_t within = static_cast<size_t>(
            static_cast<uint64_t>(pos) - static_cast<uint64_t>(fileBlock) * blockSize);

        TSK_DADDR_T imageBlock = 0;
        const TSK_FS_ATTR_RUN* run = attr->nrd.run;
        for (; run && fileBlock >= run->offset + run->len; run = run->next) {
        }
        if (!run || fileBlock < run->offset) {
            return -1;
        }
        if (run->flags & TSK_FS_ATTR_RUN_FLAG_SPARSE) {
            const size_t take = std::min(len - filled, blockSize - within);
            std::memset(dst + filled, 0, take);
            filled += take;
            continue;
        }
        imageBlock = run->addr + (fileBlock - run->offset);
        if (!loadBlock(imageBlock)) {
            return -1;
        }
        const std::vector<char>& block = blockCache_.at(imageBlock);
        if (within >= block.size()) {
            return -1;
        }
        const size_t take = std::min(len - filled, block.size() - within);
        std::memcpy(dst + filled, block.data() + within, take);
        filled += take;
    }
    return static_cast<ssize_t>(filled);
}

std::string TskFilesystemWalker::hashFileContent(TSK_FS_FILE* fsFile) {
    MD5_CTX ctx;
    if (MD5_Init(&ctx) != 1) {
        return "";
    }

    constexpr size_t kChunk = 64 * 1024;
    std::vector<char> buffer(kChunk);
    int64_t offset = 0;
    const int64_t total = fsFile->meta->size;

    while (offset < total) {
        const size_t want = static_cast<size_t>(
            std::min<int64_t>(static_cast<int64_t>(kChunk), total - offset));
        const ssize_t got = readCached(fsFile, offset, buffer.data(), want);
        // A short or failed read must not produce a hash of a partial file —
        // that would split genuine duplicates into different groups.
        if (got <= 0 || static_cast<size_t>(got) != want) {
            return "";
        }
        MD5_Update(&ctx, buffer.data(), static_cast<size_t>(got));
        offset += got;
    }

    unsigned char digest[MD5_DIGEST_LENGTH];
    MD5_Final(digest, &ctx);

    std::ostringstream hex;
    hex << std::hex << std::setfill('0');
    for (unsigned char byte : digest) {
        hex << std::setw(2) << static_cast<int>(byte);
    }
    return hex.str();
}

bool TskFilesystemWalker::worthHashing(const std::string& path) {
    // The kept set across every scene rule: user areas, logs, system config,
    // and the application-data trees. Anything else is rejected as low-value
    // and is not evidence that needs deduplicating.
    static const char* kept[] = {
        "/home/", "/root/", "/Users/", "/users/",
        "/var/log/", "/var/spool/", "/var/lib/",
        "/etc/",
        "/Documents and Settings/",
        // Windows forensic artifacts. Without this prefix the entire Windows
        // tree went unhashed: event logs, prefetch, and every registry hive
        // landed in the report with an empty MD5, and the report freeze
        // downgraded all of them to "partial" with ORIGINAL_HASH_UNAVAILABLE
        // (250 event logs in one PC.E01 run). Those artifacts are the
        // primary evidence in a Windows case, so they must be deduplicable.
        "/Windows/", "/windows/", "/ProgramData/", "/programdata/",
    };
    for (const char* prefix : kept) {
        if (path.find(prefix) != std::string::npos) {
            return true;
        }
    }
    return false;
}
