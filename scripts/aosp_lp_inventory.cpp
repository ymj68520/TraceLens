// Read-only JSON adapter around AOSP liblp (android-10.0.0_r36).
// This does not parse LP metadata itself; ReadMetadata validates geometry,
// headers and checksums in the pinned AOSP implementation.
#include <liblp/liblp.h>
#include <nlohmann/json.hpp>
#include <sys/stat.h>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

using android::fs_mgr::GetBlockDevicePartitionName;
using android::fs_mgr::GetPartitionGroupName;
using android::fs_mgr::GetPartitionName;
using android::fs_mgr::ReadMetadata;
using nlohmann::json;

int main(int argc, char** argv) {
    if (argc != 3) return 64;
    std::string path = argv[1];
    std::uint32_t slot = 0;
    try {
        std::size_t parsed = 0;
        unsigned long value = std::stoul(argv[2], &parsed, 10);
        if (parsed != std::string(argv[2]).size() || value > 31) return 64;
        slot = static_cast<std::uint32_t>(value);
    } catch (...) { return 64; }
    struct stat info{};
    if (stat(path.c_str(), &info) || !S_ISREG(info.st_mode) || info.st_size < 0) return 65;
    auto metadata = ReadMetadata(path, slot);
    if (!metadata) return 66;
    const auto& m = *metadata;
    json out = {
        {"status", "ANDROID_SUPER"},
        {"metadata_version", {m.header.major_version, m.header.minor_version}},
        {"metadata_slot_count", m.geometry.metadata_slot_count},
        {"metadata_max_size", m.geometry.metadata_max_size},
        {"logical_block_size", m.geometry.logical_block_size},
        {"slot", slot}, {"active_slot", "ACTIVE_SLOT_UNKNOWN"},
        {"block_devices", json::array()}, {"groups", json::array()},
        {"partitions", json::array()}, {"extents", json::array()},
        {"multi_device", m.block_devices.size() != 1},
        {"image_size", static_cast<std::uint64_t>(info.st_size)}
    };
    if (m.block_devices.empty() || m.geometry.metadata_slot_count == 0 ||
        m.geometry.metadata_slot_count > 32) return 67;
    for (std::size_t i = 0; i < m.block_devices.size(); ++i) {
        const auto& d = m.block_devices[i];
        out["block_devices"].push_back({
            {"index", i}, {"name", GetBlockDevicePartitionName(d)},
            {"size", d.size}, {"first_logical_sector", d.first_logical_sector},
            {"alignment", d.alignment}, {"alignment_offset", d.alignment_offset},
            {"flags", d.flags}});
    }
    for (std::size_t i = 0; i < m.groups.size(); ++i) {
        const auto& group = m.groups[i];
        out["groups"].push_back({{"index", i}, {"name", GetPartitionGroupName(group)},
                                   {"maximum_size", group.maximum_size}, {"flags", group.flags}});
    }
    std::uint64_t totalPartitionBytes = 0;
    for (std::size_t i = 0; i < m.partitions.size(); ++i) {
        const auto& partition = m.partitions[i];
        if (partition.group_index >= m.groups.size() ||
            static_cast<std::uint64_t>(partition.first_extent_index) + partition.num_extents >
                m.extents.size()) return 68;
        std::uint64_t bytes = 0;
        for (std::uint64_t j = partition.first_extent_index;
             j < static_cast<std::uint64_t>(partition.first_extent_index) + partition.num_extents; ++j) {
            const auto& extent = m.extents[j];
            if (extent.num_sectors > std::numeric_limits<std::uint64_t>::max() / 512 ||
                bytes > std::numeric_limits<std::uint64_t>::max() - extent.num_sectors * 512)
                return 69;
            bytes += extent.num_sectors * 512;
        }
        if (totalPartitionBytes > std::numeric_limits<std::uint64_t>::max() - bytes) return 69;
        totalPartitionBytes += bytes;
        out["partitions"].push_back({
            {"index", i}, {"name", GetPartitionName(partition)},
            {"attributes", partition.attributes},
            {"group_index", partition.group_index},
            {"group_name", GetPartitionGroupName(m.groups[partition.group_index])},
            {"first_extent_index", partition.first_extent_index},
            {"extent_count", partition.num_extents}, {"size", bytes}});
    }
    for (std::size_t i = 0; i < m.extents.size(); ++i) {
        const auto& extent = m.extents[i];
        if (extent.target_type != LP_TARGET_TYPE_LINEAR && extent.target_type != LP_TARGET_TYPE_ZERO)
            return 70;
        if (extent.target_type == LP_TARGET_TYPE_LINEAR) {
            if (extent.target_source >= m.block_devices.size()) return 71;
            const auto& device = m.block_devices[extent.target_source];
            const unsigned __int128 end =
                (static_cast<unsigned __int128>(extent.target_data) + extent.num_sectors) * 512;
            if (end > device.size ||
                (extent.target_source == 0 && end > static_cast<std::uint64_t>(info.st_size)))
                return 72;
        }
        out["extents"].push_back({
            {"index", i}, {"num_sectors", extent.num_sectors},
            {"target_type", extent.target_type},
            {"target_data", extent.target_data},
            {"target_source", extent.target_source}});
    }
    out["partition_count"] = m.partitions.size();
    out["total_partition_bytes"] = totalPartitionBytes;
    out["normalizable"] = !out["multi_device"].get<bool>();
    std::cout << out.dump() << '\n';
    return 0;
}
