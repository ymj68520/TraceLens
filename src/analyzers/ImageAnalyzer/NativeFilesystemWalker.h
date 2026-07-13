#pragma once

#include <string>
#include <functional>
#include <cstdint>

#include "ImageAnalyzerDataTypes.h"

// Forward declarations
struct TSK_IMG_INFO;
class DatabaseManager;

#ifdef __linux__

#include <sys/stat.h>
#include <sys/mount.h>

// Linux-specific native filesystem walker
// Uses loop mount + standard POSIX filesystem traversal
class NativeFilesystemWalker {
public:
    NativeFilesystemWalker(const std::string& imagePath, uint64_t partitionOffset);
    ~NativeFilesystemWalker();

    // Initialize and mount filesystem
    bool initialize();

    // Walk filesystem and call callback for each file
    using FileCallback = std::function<bool(const NativeFileInfo&)>;
    bool walkFilesystem(FileCallback callback);

    // Get mount point
    std::string getMountPoint() const { return mountPoint_; }

    /**
     * @brief Set the filesystem type to use for mounting.
     *
     * Default is "xfs" (the historical use of this walker). For decrypted
     * volumes (NTFS/ext4 from BitLocker/LUKS), set this to "ntfs"/"ext4"
     * before calling initialize(), or leave empty to let the kernel
     * auto-detect (mount with type "auto").
     */
    void setFilesystemType(const std::string& fsType) { fsType_ = fsType; }

private:
    // Setup loop device
    bool setupLoopDevice();

    // Mount filesystem
    bool mountFilesystem();

    // Unmount and cleanup
    void cleanup();

    // Recursively walk directory
    bool walkDirectory(const std::string& dirPath, const std::string& relativePath,
                      FileCallback callback);

    std::string imagePath_;
    uint64_t partitionOffset_;
    std::string loopDevice_;
    std::string mountPoint_;
    std::string fsType_ = "xfs";  // filesystem type passed to mount()
    bool mounted_;
    bool loopSetup_;
    bool externalMount_ = false;
};

#else

// Stub for non-Linux platforms
class NativeFilesystemWalker {
public:
    NativeFilesystemWalker(const std::string&, uint64_t) {}
    ~NativeFilesystemWalker() {}
    bool initialize() { return false; }
    bool walkFilesystem(std::function<bool(const NativeFileInfo&)>) { return false; }
    std::string getMountPoint() const { return ""; }
};

#endif // __linux__
