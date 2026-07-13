#include "NativeFilesystemWalker.h"
#include "PathManager/PathManager.h"
#include <iostream>
#include <cstring>
#include <vector>

#ifdef __linux__

#include <unistd.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <linux/loop.h>
#include <dirent.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <cerrno>
#include <fstream>

NativeFilesystemWalker::NativeFilesystemWalker(const std::string& imagePath, uint64_t partitionOffset)
    : imagePath_(imagePath)
    , partitionOffset_(partitionOffset)
    , mounted_(false)
    , loopSetup_(false) {

    // Generate unique mount point using system temp directory
    mountPoint_ = forensics::PathManager::instance().makeTempPath("forensic_mount_");
}

NativeFilesystemWalker::~NativeFilesystemWalker() {
    cleanup();
}

bool NativeFilesystemWalker::initialize() {
    std::cout << "Initializing native filesystem walker..." << std::endl;
    std::cout << "  Image: " << imagePath_ << std::endl;
    std::cout << "  Offset: " << partitionOffset_ << std::endl;

    struct stat st;
    if (stat(imagePath_.c_str(), &st) == 0 && S_ISDIR(st.st_mode)) {
        mountPoint_ = imagePath_;
        mounted_ = true;
        externalMount_ = true;
        std::cout << "  Using existing mounted filesystem: " << mountPoint_ << std::endl;
        return true;
    }

    if (!setupLoopDevice()) {
        std::cerr << "Failed to setup loop device" << std::endl;
        return false;
    }

    if (!mountFilesystem()) {
        std::cerr << "Failed to mount filesystem" << std::endl;
        cleanup();
        return false;
    }

    std::cout << "Native filesystem walker initialized successfully" << std::endl;
    std::cout << "  Mounted at: " << mountPoint_ << std::endl;

    return true;
}

bool NativeFilesystemWalker::setupLoopDevice() {
    // If the source is already a block device (e.g. a decrypted /dev/mapper
    // node), no loop setup is needed — mount it directly.
    struct stat st;
    if (stat(imagePath_.c_str(), &st) == 0 && S_ISBLK(st.st_mode)) {
        loopDevice_ = imagePath_;
        loopSetup_ = false;  // we don't own it; don't detach on cleanup
        return true;
    }

    // Find free loop device
    int ctlFd = open("/dev/loop-control", O_RDWR);
    if (ctlFd < 0) {
        std::cerr << "Error: Cannot open /dev/loop-control: " << strerror(errno) << std::endl;
        std::cerr << "Note: This requires root privileges. Please run with sudo." << std::endl;
        return false;
    }

    int devNum = ioctl(ctlFd, LOOP_CTL_GET_FREE);
    close(ctlFd);

    if (devNum < 0) {
        std::cerr << "Error: Cannot get free loop device: " << strerror(errno) << std::endl;
        return false;
    }

    loopDevice_ = "/dev/loop" + std::to_string(devNum);
    std::cout << "  Using loop device: " << loopDevice_ << std::endl;

    // Open loop device
    int loopFd = open(loopDevice_.c_str(), O_RDWR);
    if (loopFd < 0) {
        std::cerr << "Error: Cannot open loop device: " << strerror(errno) << std::endl;
        return false;
    }

    // Open image file
    int imgFd = open(imagePath_.c_str(), O_RDONLY);
    if (imgFd < 0) {
        std::cerr << "Error: Cannot open image file: " << strerror(errno) << std::endl;
        close(loopFd);
        return false;
    }

    // Setup loop device
    if (ioctl(loopFd, LOOP_SET_FD, imgFd) < 0) {
        std::cerr << "Error: Cannot set loop device: " << strerror(errno) << std::endl;
        close(imgFd);
        close(loopFd);
        return false;
    }

    // Set offset if needed
    if (partitionOffset_ > 0) {
        struct loop_info64 info;
        memset(&info, 0, sizeof(info));
        info.lo_offset = partitionOffset_;

        if (ioctl(loopFd, LOOP_SET_STATUS64, &info) < 0) {
            std::cerr << "Error: Cannot set loop offset: " << strerror(errno) << std::endl;
            ioctl(loopFd, LOOP_CLR_FD, 0);
            close(imgFd);
            close(loopFd);
            return false;
        }
    }

    close(imgFd);
    close(loopFd);
    loopSetup_ = true;

    return true;
}

bool NativeFilesystemWalker::mountFilesystem() {
    // Create mount point
    if (mkdir(mountPoint_.c_str(), 0755) < 0 && errno != EEXIST) {
        std::cerr << "Error: Cannot create mount point: " << strerror(errno) << std::endl;
        return false;
    }

    // Choose mount source: a loop device for image files, or the device path
    // directly when imagePath_ is already a block device (e.g. a decrypted
    // /dev/mapper node from the DecryptionModule).
    std::string mountSource = loopDevice_;
    if (mountSource.empty()) mountSource = imagePath_;

    // Determine filesystem type & options. "xfs" uses norecovery (skip log
    // replay for ro mount); other types use plain ro.
    std::string fsType = fsType_.empty() ? "auto" : fsType_;
    std::string mountOpts = (fsType == "xfs") ? "ro,norecovery" : "ro";

    if (mount(mountSource.c_str(), mountPoint_.c_str(), fsType.c_str(), MS_RDONLY, mountOpts.c_str()) < 0) {
        std::cerr << "Error: Cannot mount filesystem (" << fsType << "): " << strerror(errno) << std::endl;
        std::cerr << "Note: This requires root privileges. Please run with sudo." << std::endl;
        rmdir(mountPoint_.c_str());
        return false;
    }

    mounted_ = true;
    return true;
}

void NativeFilesystemWalker::cleanup() {
    if (externalMount_) {
        mounted_ = false;
        externalMount_ = false;
        return;
    }

    // Unmount filesystem
    if (mounted_) {
        std::cout << "Unmounting filesystem..." << std::endl;
        if (umount(mountPoint_.c_str()) < 0) {
            std::cerr << "Warning: Failed to unmount: " << strerror(errno) << std::endl;
        }
        rmdir(mountPoint_.c_str());
        mounted_ = false;
    }

    // Detach loop device
    if (loopSetup_ && !loopDevice_.empty()) {
        std::cout << "Detaching loop device..." << std::endl;
        int loopFd = open(loopDevice_.c_str(), O_RDONLY);
        if (loopFd >= 0) {
            ioctl(loopFd, LOOP_CLR_FD, 0);
            close(loopFd);
        }
        loopSetup_ = false;
    }
}

bool NativeFilesystemWalker::walkFilesystem(FileCallback callback) {
    if (!mounted_) {
        std::cerr << "Error: Filesystem not mounted" << std::endl;
        return false;
    }

    std::cout << "Walking mounted filesystem..." << std::endl;

    return walkDirectory(mountPoint_, "/", callback);
}

bool NativeFilesystemWalker::walkDirectory(const std::string& dirPath, const std::string& relativePath,
                                          FileCallback callback) {
    DIR* dir = opendir(dirPath.c_str());
    if (!dir) {
        std::cerr << "Warning: Cannot open directory: " << dirPath << ": " << strerror(errno) << std::endl;
        return true;  // Continue with other directories
    }

    struct dirent* entry;
    while ((entry = readdir(dir)) != nullptr) {
        // Skip . and ..
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }

        std::string fullPath = dirPath + "/" + entry->d_name;
        std::string relPath = relativePath;
        if (relPath != "/") {
            relPath += "/";
        }
        relPath += entry->d_name;

        struct stat st;
        if (lstat(fullPath.c_str(), &st) < 0) {
            std::cerr << "Warning: Cannot stat file: " << fullPath << ": " << strerror(errno) << std::endl;
            continue;
        }

        // Create file info
        NativeFileInfo fileInfo;
        fileInfo.inode = st.st_ino;
        fileInfo.name = entry->d_name;
        fileInfo.path = relPath;
        fileInfo.size = st.st_size;
        fileInfo.atime = st.st_atime;
        fileInfo.mtime = st.st_mtime;
        fileInfo.ctime = st.st_ctime;
        fileInfo.mode = st.st_mode;
        fileInfo.uid = st.st_uid;
        fileInfo.gid = st.st_gid;
        fileInfo.is_directory = S_ISDIR(st.st_mode);
        fileInfo.is_allocated = true;  // Mounted files are always allocated

        // Call callback
        if (!callback(fileInfo)) {
            closedir(dir);
            return false;
        }

        // Recurse into subdirectories
        if (S_ISDIR(st.st_mode)) {
            if (!walkDirectory(fullPath, relPath, callback)) {
                closedir(dir);
                return false;
            }
        }
    }

    closedir(dir);
    return true;
}

#else

// Non-Linux stub implementation (empty, handled by #ifdef in header)

#endif // __linux__
