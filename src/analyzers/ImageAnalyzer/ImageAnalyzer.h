#pragma once

#include <string>
#include <memory>
#include <vector>
#include <functional>
#include <tsk/libtsk.h>
#include "ImageAnalyzerDataTypes.h"
#include "DecryptionModule.h"

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
	bool isEncrypted = false;  // true if this partition was decrypted before extraction
	EncryptionType encType = EncryptionType::NONE;  // detected encryption type
	std::string decryptedPath; // path to the decrypted volume (device-mapper / file) when isEncrypted
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

	/**
	 * @brief Enable automatic decryption of encrypted partitions.
	 *
	 * When enabled, partitions that TSK reports as encrypted (BitLocker/LUKS/
	 * VeraCrypt) are decrypted using a password read from a sibling .key file
	 * before extraction. See KeyFileLoader for the file naming convention.
	 */
	void setEnableDecryption(bool b) { enableDecryption_ = b; }

	/**
	 * @brief Override the directory where sibling .key files are searched.
	 * @param dir Directory path (defaults to the image's own directory).
	 */
	void setKeyFileDir(const std::string& dir) { keyFileDir_ = dir; }

	/**
	 * @brief Provide a password directly (bypasses .key file lookup).
	 *
	 * When set, this password is used for all partitions of this image. Useful
	 * for whole-image LUKS/VeraCrypt containers and CLI usage.
	 */
	void setDecryptPassword(const std::string& p) { explicitPassword_ = p; }

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

	// Decrypt an encrypted partition (returns a decrypted volume handle).
	bool tryDecryptPartition(TSK_PNUM_T partNum, uint64_t offset,
	                         const std::string& desc, PartitionEntry& out);

	// Extract from an already-decrypted partition (device-mapper node or file).
	bool extractDecryptedPartition(const PartitionEntry& part);

	// Legacy single-FS extraction helpers (kept for XFS/native fallback paths).
	bool extractWithXFS(const std::string& dbPath);
	bool extractWithNativeMount(const std::string& dbPath);

	std::string imagePath_;
	TSK_IMG_INFO* imgInfo_;
	TSK_FS_INFO* fsInfo_;          // first successfully opened FS (for detectOSType)
	uint64_t partitionOffset_;     // offset of that first FS (legacy/XFS fallback)
	bool isXFS_;                   // image-level XFS hint (legacy)
	XFSMode xfsMode_;

	// Decryption configuration
	bool enableDecryption_ = false;
	std::string keyFileDir_;        // override dir for .key files (empty = image dir)
	std::string explicitPassword_;  // if non-empty, used for all partitions
	std::unique_ptr<DecryptionModule> decryptor_;
	std::vector<DecryptedPartition> decryptedParts_;  // for cleanup on destruction

	std::vector<PartitionEntry> partitions_;  // all walkable partitions

	std::unique_ptr<DatabaseManager> dbManager_;
	std::unique_ptr<XFSHelper> xfsHelper_;
	std::unique_ptr<NativeFilesystemWalker> nativeWalker_;
	std::unique_ptr<TskFilesystemWalker> tskWalker_;

	std::function<bool()> cancellationCallback_;
};
