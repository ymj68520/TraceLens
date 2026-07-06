#pragma once

#include <string>
#include <memory>
#include <vector>
#include <functional>
#include <tsk/libtsk.h>
#include "ImageAnalyzerDataTypes.h"

// Forward declarations
struct TSK_IMG_INFO;
struct TSK_FS_INFO;
struct TSK_FS_FILE;
class DatabaseManager;
class XFSHelper;
class NativeFilesystemWalker;
class TskFilesystemWalker;

/**
 * @brief Metadata for a single detected partition whose filesystem opened OK.
 *
 * An ImageAnalyzer keeps a vector of these (one per walkable partition) so the
 * extraction phase can iterate every partition instead of stopping at the first.
 */
struct PartitionEntry {
	TSK_PNUM_T num = 0;        // TSK partition slot index
	uint64_t offset = 0;       // byte offset into the image
	std::string desc;          // human-readable description (e.g. "NTFS / exFAT (0x07)")
	std::string fsType;        // filesystem type name from TSK (e.g. "ntfs", "ext4")
	bool isXfs = false;        // true if TSK failed but partition looks like XFS
};

/**
 * @brief Analyzes forensic disk images
 * Handles image opening, file system detection, and artifact extraction.
 */
class ImageAnalyzer {
public:
	/**
	 * @brief Construct a new Image Analyzer
	 * @param imagePath Path to the disk image file
	 */
	explicit ImageAnalyzer(const std::string& imagePath);
	~ImageAnalyzer();

	/**
	 * @brief Perform full image analysis
	 * @return true if analysis successful
	 */
	bool analyze();

	/**
	 * @brief Extract artifacts to database
	 * @param dbPath Path to output database
	 * @return true if extraction successful
	 */
	bool extractToDatabase(const std::string& dbPath);

	void setXFSMode(XFSMode mode) { xfsMode_ = mode; }

	TSK_IMG_INFO* getImageInfo() const { return imgInfo_; }
	TSK_FS_INFO* getFileSystemInfo() const { return fsInfo_; }

	/** Partitions whose filesystem opened successfully (walkable). */
	const std::vector<PartitionEntry>& partitions() const { return partitions_; }

	/**
	 * @brief Set a callback to check for cancellation
	 * @param callback Callback that returns true if analysis should be cancelled
	 */
	void setCancellationCallback(std::function<bool()> callback) {
		cancellationCallback_ = callback;
	}

private:
	bool isCancelled() const {
		return cancellationCallback_ && cancellationCallback_();
	}

	bool openImage();
	bool openFileSystem();
	void closeImage();
	std::string detectImageType();
	std::string detectOSType();

	// Per-partition extraction (walks one partition into the database).
	bool extractPartition(const PartitionEntry& part);

	// Legacy single-FS extraction helpers (kept for XFS/native fallback paths).
	bool extractWithXFS(const std::string& dbPath);
	bool extractWithNativeMount(const std::string& dbPath);

	std::string imagePath_;
	TSK_IMG_INFO* imgInfo_;
	TSK_FS_INFO* fsInfo_;          // first successfully opened FS (for detectOSType)
	uint64_t partitionOffset_;     // offset of that first FS (legacy/XFS fallback)
	bool isXFS_;                   // image-level XFS hint (legacy)
	XFSMode xfsMode_;

	std::vector<PartitionEntry> partitions_;  // all walkable partitions

	std::unique_ptr<DatabaseManager> dbManager_;
	std::unique_ptr<XFSHelper> xfsHelper_;
	std::unique_ptr<NativeFilesystemWalker> nativeWalker_;
	std::unique_ptr<TskFilesystemWalker> tskWalker_;

	std::function<bool()> cancellationCallback_;
};
