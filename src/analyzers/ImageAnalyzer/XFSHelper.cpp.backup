#include "XFSHelper.h"
#include <tsk/libtsk.h>
#include <iostream>
#include <cstring>
#include <algorithm>

#ifdef _WIN32
#include <intrin.h>
// Windows already defines these in sys/stat.h
#else
// Linux/Unix file type flags
#ifndef S_IFMT
#define S_IFMT   0170000
#endif
#ifndef S_IFREG
#define S_IFREG  0100000
#endif
#ifndef S_IFDIR
#define S_IFDIR  0040000
#endif
#ifndef S_IFLNK
#define S_IFLNK  0120000
#endif
#endif

// XFS constants
#define XFS_SB_MAGIC 0x58465342  // 'XFSB'
#define XFS_DINODE_MAGIC 0x494e  // 'IN'
#define XFS_DIR3_BLOCK_MAGIC 0x58444233  // 'XDB3'
#define XFS_DIR3_DATA_MAGIC 0x58444433   // 'XDD3'

// XFS inode format types
#define XFS_DINODE_FMT_DEV       0  // Device
#define XFS_DINODE_FMT_LOCAL     1  // Short form (in-inode data)
#define XFS_DINODE_FMT_EXTENTS   2  // Extent list
#define XFS_DINODE_FMT_BTREE     3  // B+tree root
#define XFS_DINODE_FMT_UUID      4  // UUID

// Cross-platform bit counting
#ifdef _WIN32
inline int count_trailing_zeros_64(uint64_t val) {
    if (val == 0) return 64;
    unsigned long index;
    _BitScanForward64(&index, val);
    return (int)index;
}
#else
inline int count_trailing_zeros_64(uint64_t val) {
    return __builtin_ctzll(val);
}
#endif

XFSHelper::XFSHelper(TSK_IMG_INFO* imgInfo, uint64_t partitionOffset)
    : imgInfo_(imgInfo)
    , partitionOffset_(partitionOffset)
    , blockSize_(0)
    , inodeSize_(0)
    , rootInode_(0)
    , agCount_(0)
    , agBlocks_(0)
    , initialized_(false) {
}

XFSHelper::~XFSHelper() {
}

bool XFSHelper::initialize() {
    if (initialized_) return true;

    if (!readSuperblock()) {
        std::cerr << "Failed to read XFS superblock" << std::endl;
        return false;
    }

    initialized_ = true;
    std::cout << "XFS Helper initialized successfully" << std::endl;
    std::cout << "  Filesystem: " << fsName_ << std::endl;
    std::cout << "  Block size: " << blockSize_ << std::endl;
    std::cout << "  Inode size: " << inodeSize_ << std::endl;
    std::cout << "  Root inode: " << rootInode_ << std::endl;
    std::cout << "  AG count: " << agCount_ << std::endl;
    std::cout << "  AG blocks: " << agBlocks_ << std::endl;

    return true;
}

bool XFSHelper::readData(uint64_t offset, void* buffer, size_t size) {
    ssize_t bytesRead = tsk_img_read(imgInfo_, partitionOffset_ + offset,
                                     (char*)buffer, size);
    return bytesRead == (ssize_t)size;
}

uint16_t XFSHelper::swapBytes16(uint16_t val) {
    return ((val & 0xFF) << 8) | ((val >> 8) & 0xFF);
}

uint32_t XFSHelper::swapBytes32(uint32_t val) {
    return ((val & 0xFF) << 24) | ((val & 0xFF00) << 8) |
           ((val >> 8) & 0xFF00) | ((val >> 24) & 0xFF);
}

uint64_t XFSHelper::swapBytes64(uint64_t val) {
    return ((val & 0xFFULL) << 56) | ((val & 0xFF00ULL) << 40) |
           ((val & 0xFF0000ULL) << 24) | ((val & 0xFF000000ULL) << 8) |
           ((val >> 8) & 0xFF000000ULL) | ((val >> 24) & 0xFF0000ULL) |
           ((val >> 40) & 0xFF00ULL) | ((val >> 56) & 0xFFULL);
}

bool XFSHelper::readSuperblock() {
    XFSSuperblock sb;
    if (!readData(0, &sb, sizeof(sb))) {
        std::cerr << "Failed to read XFS superblock" << std::endl;
        return false;
    }

    // XFS is big-endian, convert to host byte order
    uint32_t magic = swapBytes32(sb.sb_magicnum);
    if (magic != XFS_SB_MAGIC) {
        std::cerr << "Invalid XFS magic: 0x" << std::hex << magic << std::dec << std::endl;
        return false;
    }

    // Parse superblock fields
    blockSize_ = swapBytes32(sb.sb_blocksize);
    inodeSize_ = swapBytes16(sb.sb_inodesize);
    rootInode_ = swapBytes64(sb.sb_rootino);
    agCount_ = swapBytes32(sb.sb_agcount);
    agBlocks_ = swapBytes32(sb.sb_agblocks);

    // Get filesystem name
    size_t maxLen = sizeof(sb.sb_fname);
    size_t actualLen = strnlen(sb.sb_fname, maxLen);
    fsName_ = std::string(sb.sb_fname, actualLen);

    // Validate
    if (blockSize_ == 0 || inodeSize_ == 0 || rootInode_ == 0) {
        std::cerr << "Invalid XFS superblock values" << std::endl;
        return false;
    }

    return true;
}

uint64_t XFSHelper::getInodeOffset(uint64_t inodeNum) {
    // XFS inode number format: [AG number][AG block offset][inode offset in block]

    // Calculate AG number
    uint64_t agNo = inodeNum >> (agBlocks_ == 0 ? 0 : count_trailing_zeros_64(agBlocks_) +
                                 count_trailing_zeros_64(blockSize_ / inodeSize_));

    // Simpler approach: use inode number directly with AG structure
    // Each AG starts at: ag_number * ag_blocks * block_size
    uint64_t inodesPerBlock = blockSize_ / inodeSize_;
    uint64_t inodesPerAG = agBlocks_ * inodesPerBlock;

    uint64_t ag = inodeNum / inodesPerAG;
    uint64_t inodeInAG = inodeNum % inodesPerAG;

    uint64_t agOffset = ag * agBlocks_ * blockSize_;
    uint64_t blockInAG = inodeInAG / inodesPerBlock;
    uint64_t inodeInBlock = inodeNum % inodesPerBlock;

    // Skip AG header (first few blocks)
    uint64_t inodeBlockOffset = (blockInAG + 4) * blockSize_;  // +4 to skip AG headers
    uint64_t inodeOffset = inodeBlockOffset + (inodeInBlock * inodeSize_);

    return agOffset + inodeOffset;
}

bool XFSHelper::readInode(uint64_t inodeNum, XFSDinodeCore& inode, std::vector<uint8_t>& data) {
    uint64_t offset = getInodeOffset(inodeNum);

    std::vector<uint8_t> inodeBuffer(inodeSize_);
    if (!readData(offset, inodeBuffer.data(), inodeSize_)) {
        return false;
    }

    // Copy inode core
    memcpy(&inode, inodeBuffer.data(), sizeof(XFSDinodeCore));

    // Convert from big-endian
    inode.di_magic = swapBytes16(inode.di_magic);
    inode.di_mode = swapBytes16(inode.di_mode);
    inode.di_uid = swapBytes32(inode.di_uid);
    inode.di_gid = swapBytes32(inode.di_gid);
    inode.di_nlink = swapBytes32(inode.di_nlink);
    inode.di_size = swapBytes64(inode.di_size);
    inode.di_nblocks = swapBytes64(inode.di_nblocks);
    inode.di_nextents = swapBytes32(inode.di_nextents);
    inode.di_atime_sec = (int64_t)swapBytes64((uint64_t)inode.di_atime_sec);
    inode.di_mtime_sec = (int64_t)swapBytes64((uint64_t)inode.di_mtime_sec);
    inode.di_ctime_sec = (int64_t)swapBytes64((uint64_t)inode.di_ctime_sec);
    inode.di_atime_nsec = (int32_t)swapBytes32((uint32_t)inode.di_atime_nsec);
    inode.di_mtime_nsec = (int32_t)swapBytes32((uint32_t)inode.di_mtime_nsec);
    inode.di_ctime_nsec = (int32_t)swapBytes32((uint32_t)inode.di_ctime_nsec);

    // Validate magic
    if (inode.di_magic != XFS_DINODE_MAGIC) {
        return false;
    }

    // Get data fork (after inode core)
    size_t dataOffset = sizeof(XFSDinodeCore);
    size_t dataSize = inodeSize_ - dataOffset;

    data.resize(dataSize);
    memcpy(data.data(), inodeBuffer.data() + dataOffset, dataSize);

    return true;
}

int64_t XFSHelper::xfsTimeToUnix(int64_t sec, int32_t nsec) {
    return sec;  // Already Unix time
}

bool XFSHelper::walkFilesystem(FileCallback callback) {
    if (!initialized_) {
        std::cerr << "XFS Helper not initialized" << std::endl;
        return false;
    }

    std::cout << "Walking XFS filesystem from root inode " << rootInode_ << "..." << std::endl;

    // Start with root directory
    return parseDirectory(rootInode_, "/", callback);
}

bool XFSHelper::parseDirectory(uint64_t inodeNum, const std::string& path, FileCallback callback) {
    XFSDinodeCore inode;
    std::vector<uint8_t> data;

    if (!readInode(inodeNum, inode, data)) {
        return false;
    }

    // Check if it's a directory
    if ((inode.di_mode & S_IFMT) != S_IFDIR) {
        return false;
    }

    // Create entry for this directory itself
    XFSFileInfo dirInfo;
    dirInfo.inode = inodeNum;
    dirInfo.name = (path == "/") ? "/" : path.substr(path.find_last_of('/') + 1);
    dirInfo.path = path;
    dirInfo.size = inode.di_size;
    dirInfo.atime = xfsTimeToUnix(inode.di_atime_sec, inode.di_atime_nsec);
    dirInfo.mtime = xfsTimeToUnix(inode.di_mtime_sec, inode.di_mtime_nsec);
    dirInfo.ctime = xfsTimeToUnix(inode.di_ctime_sec, inode.di_ctime_nsec);
    dirInfo.mode = inode.di_mode;
    dirInfo.uid = inode.di_uid;
    dirInfo.gid = inode.di_gid;
    dirInfo.is_directory = true;
    dirInfo.is_allocated = true;

    if (!callback(dirInfo)) {
        return false;
    }

    // Parse directory contents based on format
    return parseDirectoryData(inode, data, path, callback);
}

bool XFSHelper::parseDirectoryData(const XFSDinodeCore& inode, const std::vector<uint8_t>& data,
                                   const std::string& path, FileCallback callback) {
    switch (inode.di_format) {
        case XFS_DINODE_FMT_LOCAL:
            // Short form directory (in-inode)
            return parseShortFormDirectory(data.data(), data.size(), path, callback);

        case XFS_DINODE_FMT_EXTENTS:
            // Extent-based directory
            return parseBlockDirectory(inode, data, path, callback);

        case XFS_DINODE_FMT_BTREE:
            // B+tree directory (complex, skip for now)
            std::cout << "  Note: B+tree directories not yet fully supported" << std::endl;
            return true;

        default:
            return false;
    }
}

bool XFSHelper::parseShortFormDirectory(const uint8_t* data, size_t dataSize,
                                       const std::string& path, FileCallback callback) {
    if (dataSize < 10) return false;

    // Short form directory header
    uint8_t count = data[0];
    uint8_t i8count = data[1];

    const uint8_t* ptr = data + 6;  // Skip header

    for (uint8_t i = 0; i < count && ptr < data + dataSize; i++) {
        // Parse entry
        uint8_t namelen = *ptr++;
        if (namelen == 0 || ptr + namelen > data + dataSize) break;

        uint64_t inum;
        if (i8count == 0) {
            // 4-byte inode numbers
            if (ptr + 4 + namelen > data + dataSize) break;
            inum = swapBytes32(*(uint32_t*)ptr);
            ptr += 4;
        } else {
            // 8-byte inode numbers
            if (ptr + 8 + namelen > data + dataSize) break;
            inum = swapBytes64(*(uint64_t*)ptr);
            ptr += 8;
        }

        std::string name((char*)ptr, namelen);
        ptr += namelen;

        // Skip . and ..
        if (name == "." || name == "..") continue;

        // Read child inode
        XFSDinodeCore childInode;
        std::vector<uint8_t> childData;
        if (readInode(inum, childInode, childData)) {
            XFSFileInfo fileInfo;
            fileInfo.inode = inum;
            fileInfo.name = name;
            fileInfo.path = path + (path == "/" ? "" : "/") + name;
            fileInfo.size = childInode.di_size;
            fileInfo.atime = xfsTimeToUnix(childInode.di_atime_sec, childInode.di_atime_nsec);
            fileInfo.mtime = xfsTimeToUnix(childInode.di_mtime_sec, childInode.di_mtime_nsec);
            fileInfo.ctime = xfsTimeToUnix(childInode.di_ctime_sec, childInode.di_ctime_nsec);
            fileInfo.mode = childInode.di_mode;
            fileInfo.uid = childInode.di_uid;
            fileInfo.gid = childInode.di_gid;
            fileInfo.is_directory = ((childInode.di_mode & S_IFMT) == S_IFDIR);
            fileInfo.is_allocated = true;

            if (!callback(fileInfo)) {
                return false;
            }

            // Recurse into subdirectories
            if (fileInfo.is_directory) {
                parseDirectory(inum, fileInfo.path, callback);
            }
        }
    }

    return true;
}

bool XFSHelper::parseExtents(const uint8_t* data, size_t dataSize, std::vector<XFSExtent>& extents) {
    extents.clear();

    // Each extent is 16 bytes in packed format
    size_t numExtents = dataSize / 16;

    for (size_t i = 0; i < numExtents && i * 16 + 16 <= dataSize; i++) {
        const uint8_t* extData = data + (i * 16);

        // XFS extent format (packed 128-bit value):
        // [63:54] extent flag + logical offset high
        // [53:0]  logical offset low
        // [127:73] start block
        // [72:64]  block count

        uint64_t low = swapBytes64(*(uint64_t*)(extData));
        uint64_t high = swapBytes64(*(uint64_t*)(extData + 8));

        XFSExtent ext;
        ext.startoff = (low & 0x1FFFFFFFFFFFFFULL);  // Bits 0-53
        ext.startblock = (high >> 21);                 // Bits 73-127
        ext.blockcount = (high & 0x1FFFFFULL);        // Bits 64-72

        if (ext.blockcount > 0) {
            extents.push_back(ext);
        }
    }

    return !extents.empty();
}

bool XFSHelper::readFileData(const std::vector<XFSExtent>& extents,
                             std::vector<uint8_t>& buffer, uint64_t fileSize) {
    buffer.clear();
    buffer.reserve(fileSize);

    for (const auto& ext : extents) {
        uint64_t offset = ext.startblock * blockSize_;
        uint64_t size = ext.blockcount * blockSize_;

        size_t oldSize = buffer.size();
        buffer.resize(oldSize + size);

        if (!readData(offset, buffer.data() + oldSize, size)) {
            return false;
        }
    }

    // Truncate to actual file size
    if (buffer.size() > fileSize) {
        buffer.resize(fileSize);
    }

    return true;
}

bool XFSHelper::parseBlockDirectory(const XFSDinodeCore& inode, const std::vector<uint8_t>& data,
                                    const std::string& path, FileCallback callback) {
    // Parse extent list
    std::vector<XFSExtent> extents;
    size_t extentsDataSize = (size_t)(inode.di_nextents * 16);
    size_t dataSize = (data.size() < extentsDataSize) ? data.size() : extentsDataSize;
    if (!parseExtents(data.data(), dataSize, extents)) {
        return false;
    }

    // Read directory blocks via extents
    std::vector<uint8_t> dirData;
    if (!readFileData(extents, dirData, inode.di_size)) {
        return false;
    }

    // Parse directory block entries
    // XFS directory block format: [header][entries...]
    if (dirData.size() < 16) return false;

    size_t offset = 16;  // Skip block header

    while (offset + 11 < dirData.size()) {  // Minimum entry size
        // XFS dir entry: [inode:8][namelen:1][name:N][ftype:1][tag:2]
        uint64_t inum = swapBytes64(*(uint64_t*)(dirData.data() + offset));
        offset += 8;

        uint8_t namelen = dirData[offset++];
        if (namelen == 0 || namelen == 0xFF) break;
        if (offset + namelen + 3 > dirData.size()) break;

        std::string name((char*)(dirData.data() + offset), namelen);
        offset += namelen;

        uint8_t ftype = dirData[offset++];
        offset += 2;  // Skip tag

        // Align to 8-byte boundary
        offset = (offset + 7) & ~7ULL;

        // Skip . and ..
        if (name == "." || name == "..") continue;
        if (inum == 0) continue;

        // Read child inode
        XFSDinodeCore childInode;
        std::vector<uint8_t> childData;
        if (readInode(inum, childInode, childData)) {
            XFSFileInfo fileInfo;
            fileInfo.inode = inum;
            fileInfo.name = name;
            fileInfo.path = path + (path == "/" ? "" : "/") + name;
            fileInfo.size = childInode.di_size;
            fileInfo.atime = xfsTimeToUnix(childInode.di_atime_sec, childInode.di_atime_nsec);
            fileInfo.mtime = xfsTimeToUnix(childInode.di_mtime_sec, childInode.di_mtime_nsec);
            fileInfo.ctime = xfsTimeToUnix(childInode.di_ctime_sec, childInode.di_ctime_nsec);
            fileInfo.mode = childInode.di_mode;
            fileInfo.uid = childInode.di_uid;
            fileInfo.gid = childInode.di_gid;
            fileInfo.is_directory = ((childInode.di_mode & S_IFMT) == S_IFDIR);
            fileInfo.is_allocated = true;

            if (!callback(fileInfo)) {
                return false;
            }

            // Recurse into subdirectories
            if (fileInfo.is_directory) {
                parseDirectory(inum, fileInfo.path, callback);
            }
        }
    }

    return true;
}
