#pragma once

#include <string>
#include <functional>
#include <tsk/libtsk.h>
#include "ImageAnalyzerDataTypes.h"

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

    TSK_IMG_INFO* imgInfo_;
    TSK_FS_INFO* fsInfo_;
    uint64_t offset_;
    TskFileCallback currentCallback_;
};
