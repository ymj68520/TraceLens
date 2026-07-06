#include "TskFilesystemWalker.h"
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

    // Invoke user callback
    if (currentCallback_) {
        currentCallback_(record);
    }
}
