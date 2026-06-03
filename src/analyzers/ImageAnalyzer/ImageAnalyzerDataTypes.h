#pragma once
#ifndef IMAGE_ANALYZER_DATA_TYPES_H
#define IMAGE_ANALYZER_DATA_TYPES_H

#include <string>
#include <cstdint>
#include "DatabaseManager/DatabaseManagerDataTypes.h"

/**
 * @brief XFS filesystem operation mode
 */
enum class XFSMode {
	Auto,      // Auto-detect (native on Linux, pure on Windows)
	Native,    // Linux native mount (requires sudo)
	Pure       // Pure XFS parser (cross-platform)
};

/**
 * @brief Native filesystem file information structure
 * 
 * Matches XFSFileInfo for consistency
 */
struct NativeFileInfo {
    uint64_t inode;
    std::string name;
    std::string path;
    uint64_t size;
    int64_t atime;
    int64_t mtime;
    int64_t ctime;
    uint16_t mode;
    uint32_t uid;
    uint32_t gid;
    bool is_directory;
    bool is_allocated;
};

/**
 * @brief XFS Superblock structure (simplified)
 */
#pragma pack(push, 1)
struct XFSSuperblock {
    uint32_t sb_magicnum;       // 0x58465342 ('XFSB')
    uint32_t sb_blocksize;      // Filesystem block size
    uint64_t sb_dblocks;        // Number of data blocks
    uint64_t sb_rblocks;        // Number of realtime blocks
    uint64_t sb_rextents;       // Number of realtime extents
    uint8_t  sb_uuid[16];       // UUID
    uint64_t sb_logstart;       // Log start block
    uint64_t sb_rootino;        // Root inode number
    uint64_t sb_rbmino;         // Realtime bitmap inode
    uint64_t sb_rsumino;        // Realtime summary inode
    uint32_t sb_rextsize;       // Realtime extent size
    uint32_t sb_agblocks;       // Allocation group size in blocks
    uint32_t sb_agcount;        // Number of allocation groups
    uint32_t sb_rbmblocks;      // Realtime bitmap size
    uint32_t sb_logblocks;      // Log size in blocks
    uint16_t sb_versionnum;     // Version number
    uint16_t sb_sectsize;       // Sector size
    uint16_t sb_inodesize;      // Inode size
    uint16_t sb_inopblock;      // Inodes per block
    char     sb_fname[12];      // Filesystem name
    uint8_t  sb_blocklog;       // log2 of sb_blocksize
    uint8_t  sb_sectlog;        // log2 of sb_sectsize
    uint8_t  sb_inodelog;       // log2 of sb_inodesize
    uint8_t  sb_inopblog;       // log2 of sb_inopblock
    uint8_t  sb_agblklog;       // log2 of sb_agblocks
    uint8_t  sb_rextslog;       // log2 of sb_rextents
    uint8_t  sb_inprogress;     // mkfs in progress
    uint8_t  sb_imax_pct;       // max % of fs for inode space
};

/**
 * @brief XFS Dinode core structure (simplified)
 */
struct XFSDinodeCore {
    uint16_t di_magic;          // 0x494e ('IN')
    uint16_t di_mode;           // File mode
    int8_t   di_version;        // Inode version
    int8_t   di_format;         // Format of di_c data
    uint16_t di_onlink;         // Old number of links
    uint32_t di_uid;            // Owner's user id
    uint32_t di_gid;            // Owner's group id
    uint32_t di_nlink;          // Number of links
    uint16_t di_projid;         // Project ID
    uint8_t  di_pad[8];         // Padding
    uint16_t di_flushiter;      // Flush iteration
    uint32_t di_atime_sec;      // Access time seconds (uint32, not int64)
    uint32_t di_atime_nsec;     // Access time nanoseconds
    uint32_t di_mtime_sec;      // Modification time seconds
    uint32_t di_mtime_nsec;     // Modification time nanoseconds
    uint32_t di_ctime_sec;      // Change time seconds
    uint32_t di_ctime_nsec;     // Change time nanoseconds
    uint64_t di_size;           // File size in bytes
    uint64_t di_nblocks;        // Number of blocks
    uint32_t di_extsize;        // Extent size
    uint32_t di_nextents;       // Number of data extents
    uint16_t di_anextents;      // Number of attr extents
    uint8_t  di_forkoff;        // Attr fork offset
    int8_t   di_aformat;        // Attr fork format
    uint32_t di_dmevmask;       // DMIG event mask
    uint16_t di_dmstate;        // DMIG state
    uint16_t di_flags;          // Flags
    uint32_t di_gen;            // Generation number
};

/**
 * @brief XFS Directory entry (simplified)
 */
struct XFSDirEntry {
    uint64_t inumber;           // Inode number
    uint8_t  namelen;           // Name length
    uint8_t  name[256];         // Name (variable length)
    uint8_t  ftype;             // File type
};

/**
 * @brief XFS Extent structure
 */
struct XFSExtent {
    uint64_t startoff;          // Logical file block offset
    uint64_t startblock;        // Absolute block number
    uint64_t blockcount;        // Block count
};
#pragma pack(pop)

/**
 * @brief XFS file information record
 */
struct XFSFileInfo {
    uint64_t inode;
    std::string name;
    std::string path;
    uint64_t size;
    int64_t atime;
    int64_t mtime;
    int64_t ctime;
    uint16_t mode;
    uint32_t uid;
    uint32_t gid;
    bool is_directory;
    bool is_allocated;
};

#endif // IMAGE_ANALYZER_DATA_TYPES_H
