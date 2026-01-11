#pragma once

#include <string>
#include <vector>
#include <cstdint>
#include <functional>

#include "ImageAnalyzerDataTypes.h"

// Forward declaration
struct TSK_IMG_INFO;

// XFS Helper class
class XFSHelper {
public:
    XFSHelper(TSK_IMG_INFO* imgInfo, uint64_t partitionOffset);
    ~XFSHelper();

    // Initialize and read superblock
    bool initialize();

    // Get filesystem info
    uint64_t getBlockSize() const { return blockSize_; }
    uint64_t getInodeSize() const { return inodeSize_; }
    uint64_t getRootInode() const { return rootInode_; }
    std::string getFilesystemName() const { return fsName_; }

    // Walk filesystem and call callback for each file
    using FileCallback = std::function<bool(const XFSFileInfo&)>;
    bool walkFilesystem(FileCallback callback);

private:
    // Read data from image
    bool readData(uint64_t offset, void* buffer, size_t size);

    // Read and parse superblock
    bool readSuperblock();

    // Read inode
    bool readInode(uint64_t inodeNum, XFSDinodeCore& inode, std::vector<uint8_t>& data);

    // Calculate inode location
    uint64_t getInodeOffset(uint64_t inodeNum);

    // Parse directory
    bool parseDirectory(uint64_t inodeNum, const std::string& path, FileCallback callback);

    // Parse directory data (format-specific)
    bool parseDirectoryData(const XFSDinodeCore& inode, const std::vector<uint8_t>& data,
                           const std::string& path, FileCallback callback);

    // Parse short form directory (in-inode)
    bool parseShortFormDirectory(const uint8_t* data, size_t dataSize,
                                const std::string& path, FileCallback callback);

    // Parse block/leaf form directory
    bool parseBlockDirectory(const XFSDinodeCore& inode, const std::vector<uint8_t>& data,
                           const std::string& path, FileCallback callback);

    // Parse extent list
    bool parseExtents(const uint8_t* data, size_t dataSize, std::vector<XFSExtent>& extents);

    // Read file data via extents
    bool readFileData(const std::vector<XFSExtent>& extents, std::vector<uint8_t>& buffer, uint64_t fileSize);

    // Convert XFS timestamps to Unix time
    int64_t xfsTimeToUnix(int64_t sec, int32_t nsec);

    // Byte swapping for big-endian XFS
    uint16_t swapBytes16(uint16_t val);
    uint32_t swapBytes32(uint32_t val);
    uint64_t swapBytes64(uint64_t val);

    TSK_IMG_INFO* imgInfo_;
    uint64_t partitionOffset_;
    uint64_t blockSize_;
    uint64_t inodeSize_;
    uint64_t rootInode_;
    uint32_t agCount_;
    uint32_t agBlocks_;
    std::string fsName_;
    bool initialized_;
};
