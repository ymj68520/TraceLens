#pragma once
#ifndef ANDROID_ADB_EXTRACTOR_DATA_TYPES_H
#define ANDROID_ADB_EXTRACTOR_DATA_TYPES_H

#include <string>
#include <cstdint>

/**
 * @brief Android partition information structure
 * 
 * Contains information about Android device partitions.
 */
struct PartitionInfo {
    std::string name;           // 分区名称 (如 "vbmeta", "boot")
    std::string device_path;     // 设备路径 (如 "/dev/block/by-name/vbmeta")
    std::string block_device;    // 实际块设备路径 (如 "/dev/block/sde12")
    uint64_t size;              // 分区大小 (字节)
    std::string type;           // 分区类型 (如 "emmc", "ufs")
    bool is_readable;           // 是否可读
    bool requires_root;         // 是否需要root权限

    PartitionInfo() : size(0), is_readable(false), requires_root(true) {}
};

#endif // ANDROID_ADB_EXTRACTOR_DATA_TYPES_H
