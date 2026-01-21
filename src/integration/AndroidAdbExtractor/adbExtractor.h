#pragma once

#include <sys/stat.h>
#include <sys/types.h>
#include <vector>
#include <string>

#include "adbClient.h"
#include "AndroidAdbExtractorDataTypes.h"

#ifdef _WIN32
#include <direct.h>
#define mkdir_cross(dir) _mkdir(dir)
#else
#include <sys/stat.h>
#include <sys/types.h>
#define mkdir_cross(dir) mkdir(dir, 0755)
#endif

class AndroidDirectoryExtractor{
    private:
    ADBClient adb;
    std::string output_dir;
    bool has_root;
    bool use_root_for_extraction;

    void createDirectory(const std::string &path);
    bool extractFileRecursive(const std::string& remote_path, const std::string& local_base);

    // Partition extraction methods
    /**
     * @brief Test read access to a partition
     * @param device_path Path to device partition
     * @return true if readable
     */
    bool testPartitionReadAccess(const std::string& device_path);
    bool extractPartitionUsingDD(const std::string& partition_name, const std::string& block_device, const std::string& output_path);
    bool extractPartitionUsingShell(const std::string& block_device, const std::string& output_path);

    // Direct partition pull methods - implements dd + pull combination
    /**
     * @brief Extract partition directly using dd and pull
     * @param partition_name Name of partition
     * @param output_filename Optional output filename
     * @return true if successful
     */
    bool extractPartitionDirectly(const std::string& partition_name, const std::string& output_filename = "");
    bool pullPartitionImage(const std::string& partition_name, const std::string& remote_path, const std::string& local_path);

    // Streaming methods - avoids temporary files on device
    /**
     * @brief Extract partition via streaming
     * @param device_path Path to device partition
     * @param output_path Local output path
     * @param expected_size Expected size in bytes
     * @return true if successful
     */
    bool extractPartitionStreaming(const std::string& device_path, const std::string& output_path, uint64_t expected_size);
    bool extractPartitionTraditional(const std::string& partition_name, const std::string& device_path,
                                   const std::string& output_path, const std::string& output_filename);

    public:
    AndroidDirectoryExtractor(const std::string& output = "./extracted_data")
        : output_dir(output), has_root(false), use_root_for_extraction(false) {
        createDirectory(output_dir);
    }

    bool initialize(bool auto_root = true);
    bool extractDirectory(const std::string& device_path);
    void extractMultiple(const std::vector<std::string>& paths);

    // Partition extraction features
    /**
     * @brief Extract a specific partition
     * @param partition_name Name of partition
     * @param output_filename Optional custom output name
     * @return true if extraction successful
     */
    bool extractPartition(const std::string& partition_name, const std::string& output_filename = "");
    bool extractMultiplePartitions(const std::vector<std::string>& partition_names);
    void listAvailablePartitions();
    std::vector<PartitionInfo> getPartitionList();
    bool hasRootAccess() const { return has_root; }
};