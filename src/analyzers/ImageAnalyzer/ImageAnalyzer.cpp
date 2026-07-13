#include "ImageAnalyzer.h"
#include "DatabaseManager/DatabaseManager.h"
#include "XFSHelper.h"
#include "NativeFilesystemWalker.h"
#include "TskFilesystemWalker.h"
#include "KeyFileLoader.h"
#include "AuditLog/AuditLog.h"
#include "ConfigManager/ConfigManager.h"
#include <iostream>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <filesystem>
#include <algorithm>
#include <cctype>

namespace fs = std::filesystem;

namespace {

std::string normalizeMountFilesystemType(std::string fsType) {
	std::transform(fsType.begin(), fsType.end(), fsType.begin(),
	               [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });

	if (fsType.find("ntfs") != std::string::npos) return "ntfs";
	if (fsType.find("ext4") != std::string::npos) return "ext4";
	if (fsType.find("ext3") != std::string::npos) return "ext3";
	if (fsType.find("ext2") != std::string::npos) return "ext2";
	if (fsType.find("xfs") != std::string::npos) return "xfs";
	if (fsType.find("exfat") != std::string::npos) return "exfat";
	if (fsType.find("fat") != std::string::npos) return "vfat";
	if (fsType.find("hfs") != std::string::npos) return "hfs";
	if (fsType.find("iso9660") != std::string::npos) return "iso9660";
	return "";
}

} // namespace

ImageAnalyzer::ImageAnalyzer(const std::string& imagePath)
	: imagePath_(imagePath), imgInfo_(nullptr), fsInfo_(nullptr),
	  partitionOffset_(0), isXFS_(false), xfsMode_(XFSMode::Auto) {
	decryptor_ = std::make_unique<DecryptionModule>();
}

ImageAnalyzer::~ImageAnalyzer() {
	closeImage();
	// Release any decrypted volumes (device-mapper nodes, loop devices, temp files).
	for (const auto& dp : decryptedParts_) {
		decryptor_->cleanup(dp);
	}
}

bool ImageAnalyzer::analyze() {
	if (!openImage()) {
		return false;
	}

	if (!openFileSystem()) {
		return false;
	}

	return true;
}

bool ImageAnalyzer::openImage() {
	// Try different image type detection strategies
	TSK_IMG_TYPE_ENUM imgType = TSK_IMG_TYPE_DETECT;

#ifdef _WIN32
	// Windows: Convert UTF-8 path to wide char
	int len = MultiByteToWideChar(CP_UTF8, 0, imagePath_.c_str(), -1, nullptr, 0);
	if (len <= 0) {
		std::cerr << "Error: Invalid path encoding, error code: " << GetLastError() << std::endl;
		return false;
	}

	TSK_TCHAR* imgPathCstr = new TSK_TCHAR[len];
	if (MultiByteToWideChar(CP_UTF8, 0, imagePath_.c_str(), -1, imgPathCstr, len) == 0) {
		std::cerr << "Error converting image path to wide char: " << GetLastError() << std::endl;
		delete[] imgPathCstr;
		return false;
	}

	std::wcout << L"Opening image: " << imgPathCstr << std::endl;

	// First try auto-detection
	imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);

	// If auto-detection fails, try explicitly as RAW
	if (!imgInfo_) {
		std::cout << "Auto-detection failed, trying as RAW/DD format..." << std::endl;
		imgType = TSK_IMG_TYPE_RAW;
		imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
	}

	delete[] imgPathCstr;
#else
	// Linux/Unix: Use path directly (UTF-8 is standard)
	std::cout << "Opening image: " << imagePath_ << std::endl;

	const char* imgPathCstr = imagePath_.c_str();

	// First try auto-detection
	imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);

	// If auto-detection fails, try explicitly as RAW
	if (!imgInfo_) {
		std::cout << "Auto-detection failed, trying as RAW/DD format..." << std::endl;
		imgType = TSK_IMG_TYPE_RAW;
		imgInfo_ = tsk_img_open(1, &imgPathCstr, imgType, 0);
	}
#endif

	if (!imgInfo_) {
		std::cerr << "Error opening image: " << tsk_error_get() << std::endl;
		return false;
	}

	std::cout << "Image opened successfully" << std::endl;
	std::cout << "  Type: " << detectImageType() << std::endl;
	std::cout << "  Size: " << imgInfo_->size << " bytes ("
	          << (imgInfo_->size / (1024.0 * 1024 * 1024)) << " GB)" << std::endl;
	AuditLog::instance().log("SYSTEM", "IMAGE_OPEN", "Opened image: " + imagePath_ + ", Type: " + detectImageType() + ", Size: " + std::to_string(imgInfo_->size) + " bytes");

	return true;
}

bool ImageAnalyzer::openFileSystem() {
	// Try to open volume system first
	TSK_VS_INFO* vsInfo = tsk_vs_open(imgInfo_, 0, TSK_VS_TYPE_DETECT);

	if (vsInfo) {
		std::cout << "Volume system detected" << std::endl;
		std::cout << "  Partitions: " << vsInfo->part_count << std::endl;

		// Enumerate EVERY allocated partition and record those whose filesystem
		// opens successfully. Previously this loop stopped at the first openable
		// partition, silently dropping the rest (and almost all real evidence on
		// multi-partition disks). See scripts/FINDINGS_MULTI_PARTITION.md.
		int skipped = 0;
		for (TSK_PNUM_T i = 0; i < vsInfo->part_count; i++) {
			const TSK_VS_PART_INFO* part = tsk_vs_part_get(vsInfo, i);
			if (!part || !(part->flags & TSK_VS_PART_FLAG_ALLOC)) {
				continue;
			}
			uint64_t offset = static_cast<uint64_t>(part->start) * vsInfo->block_size;
			std::cout << "  Trying partition " << i
			          << " at offset " << offset
			          << " (desc: " << part->desc << ")" << std::endl;

			// Try to open filesystem on this partition
			TSK_FS_INFO* fs = tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT);
			if (fs) {
				const char* fsTypeName = tsk_fs_type_toname(fs->ftype);
				std::string fsTypeStr = fsTypeName ? fsTypeName : "unknown";
				bool partIsXfs = (fsTypeName && strstr(fsTypeName, "xfs"));
#ifdef TSK_FS_TYPE_XFS
				if (fs->ftype == TSK_FS_TYPE_XFS) partIsXfs = true;
#endif
				std::cout << "    Filesystem type: " << fsTypeStr
				          << (partIsXfs ? " (XFS)" : "") << std::endl;

				PartitionEntry entry;
				entry.num = i;
				entry.offset = offset;
				entry.desc = part->desc;
				entry.fsType = fsTypeStr;
				entry.isXfs = partIsXfs;
				partitions_.push_back(entry);

				// Keep the first opened FS as the "representative" used by
				// detectOSType() and legacy XFS/native fallback paths.
				if (!fsInfo_) {
					fsInfo_ = fs;            // ownership retained by ImageAnalyzer
					partitionOffset_ = offset;
					isXFS_ = partIsXfs;
					if (partIsXfs) {
						std::cout << "    Detected XFS filesystem - will use alternative method if TSK fails" << std::endl;
					}
				} else {
					// Subsequent partitions: we already recorded metadata, close
					// the FS handle now (extraction reopens per-partition via walker).
					tsk_fs_close(fs);
				}
			} else {
				std::cout << "    Could not open filesystem: " << tsk_error_get() << std::endl;
				// Attempt decryption before filesystem-specific fallbacks. LUKS
				// partitions commonly carry a generic "Linux" partition description.
				if (enableDecryption_) {
					PartitionEntry decEntry;
					if (tryDecryptPartition(i, offset, part->desc, decEntry)) {
						partitions_.push_back(decEntry);
						continue;  // decrypted OK — do NOT skip
					}
					// tryDecryptPartition already printed the reason on failure.
				}
#ifdef __linux__
				// TSK failed but partition description suggests a Linux FS — likely
				// XFS that TSK cannot parse. Record it as an XFS candidate so the
				// native-mount fallback can attempt it during extraction.
				if (strstr(part->desc, "Linux")) {
					std::cout << "    Note: assuming XFS for native mount attempt" << std::endl;
					PartitionEntry entry;
					entry.num = i;
					entry.offset = offset;
					entry.desc = part->desc;
					entry.fsType = "xfs?";
					entry.isXfs = true;
					partitions_.push_back(entry);
					if (!fsInfo_) {
						partitionOffset_ = offset;
						isXFS_ = true;
					}
					continue;
				}
#endif
				std::cout << "    Skipping partition " << i
				          << " (unsupported: " << part->desc
				          << " — may be LVM, encrypted, or unrecognised)" << std::endl;
				skipped++;
			}
		}

		tsk_vs_close(vsInfo);

		if (partitions_.empty()) {
			std::cerr << "Error: No accessible filesystem found in any partition ("
			          << skipped << " skipped)" << std::endl;
			return false;
		}
		std::cout << "  Openable partitions: " << partitions_.size()
		          << (skipped ? " (" + std::to_string(skipped) + " skipped)" : "") << std::endl;
	} else {
		// No partition table, try opening filesystem directly at offset 0.
		// This is the single-partition / raw-filesystem case (e.g. test_image.img),
		// OR a whole-image encrypted container (LUKS/VeraCrypt).
		std::cout << "No volume system detected, trying direct filesystem access..." << std::endl;
		fsInfo_ = tsk_fs_open_img(imgInfo_, 0, TSK_FS_TYPE_DETECT);
		if (!fsInfo_) {
			// Could be a whole-image encrypted volume. Try decryption if enabled.
			if (enableDecryption_) {
				PartitionEntry decEntry;
				if (tryDecryptPartition(0, 0, "whole image", decEntry)) {
					partitions_.push_back(decEntry);
					// fsInfo_ stays null; extraction will use the decrypted path.
				} else {
					std::cerr << "Error opening filesystem: " << tsk_error_get() << std::endl;
					return false;
				}
			} else {
				std::cerr << "Error opening filesystem: " << tsk_error_get() << std::endl;
				return false;
			}
		} else {
			const char* fsTypeName = tsk_fs_type_toname(fsInfo_->ftype);
			isXFS_ = (fsTypeName && strstr(fsTypeName, "xfs"));
			std::string fsTypeStr = fsTypeName ? fsTypeName : "unknown";

			PartitionEntry entry;
			entry.num = 0;
			entry.offset = 0;
			entry.desc = "whole image";
			entry.fsType = fsTypeStr;
			entry.isXfs = isXFS_;
			partitions_.push_back(entry);
		}
	}

	if (fsInfo_) {
		std::cout << "Primary filesystem opened successfully" << std::endl;
		std::cout << "  Type: " << tsk_fs_type_toname(fsInfo_->ftype) << std::endl;
		std::cout << "  Block size: " << fsInfo_->block_size << std::endl;
		std::cout << "  Block count: " << fsInfo_->block_count << std::endl;
		std::cout << "  Root inode: " << fsInfo_->root_inum << std::endl;
		AuditLog::instance().log("SYSTEM", "FS_OPEN", "Filesystem type: " + std::string(tsk_fs_type_toname(fsInfo_->ftype)) + ", Block size: " + std::to_string(fsInfo_->block_size));
	}

	return true;
}

void ImageAnalyzer::closeImage() {
	if (fsInfo_) {
		tsk_fs_close(fsInfo_);
		fsInfo_ = nullptr;
	}

	if (imgInfo_) {
		tsk_img_close(imgInfo_);
		imgInfo_ = nullptr;
	}
}

bool ImageAnalyzer::extractToDatabase(const std::string& dbPath) {
	dbManager_ = std::make_unique<DatabaseManager>(dbPath);

	if (!dbManager_->initialize()) {
		std::cerr << "Error initializing database" << std::endl;
		return false;
	}

	// Record partition metadata into the partitions table (previously dead code).
	for (const auto& part : partitions_) {
		dbManager_->insertPartitionInfo(static_cast<int>(part.num),
		                                static_cast<int64_t>(part.offset),
		                                0, part.desc, part.fsType);
	}

	// Walk EVERY walkable partition. Previously only the first openable partition
	// was walked, silently discarding all others. See FINDINGS_MULTI_PARTITION.md.
	int totalFiles = 0;
	int okPartitions = 0;
	for (const auto& part : partitions_) {
		if (isCancelled()) return false;

		std::cout << "\n=== Partition " << part.num << " (offset " << part.offset
		          << ", " << part.fsType << ", " << part.desc << ") ===" << std::endl;

		if (extractPartition(part)) {
			okPartitions++;
		} else {
			std::cout << "  Partition " << part.num << " yielded no files." << std::endl;
		}
	}

	if (isCancelled()) return false;

	// Compute total inserted from the DB (more reliable than per-partition counters
	// because XFS/native fallback paths insert independently).
	totalFiles = dbManager_->getFileCount();

	if (totalFiles > 0) {
		std::cout << "\nFilesystem walk completed across " << okPartitions
		          << "/" << partitions_.size() << " partitions. Total files: "
		          << totalFiles << std::endl;
		AuditLog::instance().log("SYSTEM", "EXTRACTION_COMPLETE",
			"Filesystem walk completed for: " + imagePath_ +
			" (" + std::to_string(okPartitions) + "/" +
			std::to_string(partitions_.size()) + " partitions, " +
			std::to_string(totalFiles) + " files)");
		return true;
	}

	std::cout << "\nExtraction produced 0 files across all partitions." << std::endl;
	return false;
}

bool ImageAnalyzer::extractPartition(const PartitionEntry& part) {
	// XFS/Native fallback helpers read the member partitionOffset_. Point it at
	// THIS partition so multi-image XFS extraction targets the right partition.
	partitionOffset_ = part.offset;

	// Decrypted partitions expose an accessible block device / file. Route them
	// to a dedicated extractor that opens the decrypted volume directly, since
	// the original TSK walker cannot read the encrypted partition.
	if (part.isEncrypted && !part.decryptedPath.empty()) {
		return extractDecryptedPartition(part);
	}

	// Honor an explicit XFS mode for XFS partitions, falling back to TSK in auto mode.
	if (part.isXfs) {
		if (xfsMode_ == XFSMode::Native) {
#ifdef __linux__
			std::cout << "  Using native mount method for XFS partition "
			          << part.num << "..." << std::endl;
			return extractWithNativeMount(dbManager_->getDbPath());
#else
			std::cerr << "  Native XFS mount is only supported on Linux" << std::endl;
			return false;
#endif
		}
		if (xfsMode_ == XFSMode::Pure) {
			std::cout << "  Using XFS helper for partition " << part.num << "..." << std::endl;
			return extractWithXFS(dbManager_->getDbPath());
		}
		// Auto: fall through to TSK attempt below; XFS fallback handled later.
	}

	// TSK Universal Walker path. The walker opens its own fs handle from the
	// given offset, so we simply instantiate one per partition.
	tskWalker_ = std::make_unique<TskFilesystemWalker>(imgInfo_, part.offset);

	if (!tskWalker_->open()) {
		std::cout << "  TSK could not open filesystem at offset " << part.offset << std::endl;
		// XFS auto fallback for partitions TSK cannot parse
		if (part.isXfs) {
#ifdef __linux__
			std::cout << "  Trying native mount for XFS partition " << part.num << "..." << std::endl;
			if (extractWithNativeMount(dbManager_->getDbPath())) return true;
			std::cout << "  Native mount failed, trying pure XFS parser..." << std::endl;
			return extractWithXFS(dbManager_->getDbPath());
#else
			std::cout << "  Trying pure XFS parser..." << std::endl;
			return extractWithXFS(dbManager_->getDbPath());
#endif
		}
		return false;
	}

	std::cout << "  Walking with Universal TSK Walker ("
	          << tskWalker_->getFsType() << ")..." << std::endl;

	int fileCount = 0;
	int maxLog = forensics::ConfigManager::instance().getMaxLogDisplayFiles();
	bool success = tskWalker_->walk([this, &part, &fileCount, maxLog](const FileRecord& record) -> bool {
		if (isCancelled()) return false;
		FileRecord r = record;
		r.partitionNum = static_cast<int>(part.num);
		if (dbManager_->insertFileRecord(r)) {
			fileCount++;
			if (fileCount <= maxLog) {
				std::cout << "  [" << fileCount << "] " << r.path << std::endl;
			} else if (fileCount % (maxLog * 5) == 0) {
				std::cout << "  ... processing: [" << fileCount << "] " << r.path << " ..." << std::endl;
			}
		}
		return true;
	});

	tskWalker_->close();

	if (isCancelled()) return false;

	if (success && fileCount > 0) {
		std::cout << "  Partition " << part.num << " yielded " << fileCount << " files." << std::endl;
		return true;
	}

	// TSK walked but got nothing; try XFS fallback if applicable.
	if (part.isXfs) {
#ifdef __linux__
		std::cout << "  TSK walk empty, trying native mount for XFS..." << std::endl;
		if (extractWithNativeMount(dbManager_->getDbPath())) return true;
		std::cout << "  Native mount failed, trying pure XFS parser..." << std::endl;
		return extractWithXFS(dbManager_->getDbPath());
#else
		std::cout << "  TSK walk empty, trying pure XFS parser..." << std::endl;
		return extractWithXFS(dbManager_->getDbPath());
#endif
	}
	return false;
}

bool ImageAnalyzer::tryDecryptPartition(TSK_PNUM_T partNum, uint64_t offset,
                                         const std::string& desc, PartitionEntry& out) {
	EncryptionType encType = DecryptionModule::detect(imagePath_, offset);
	if (encType == EncryptionType::NONE) {
		// Not a recognised encryption type — nothing we can do here.
		return false;
	}
	std::cout << "    Detected " << DecryptionModule::encryptionTypeName(encType)
	          << " on partition " << partNum
	          << " (offset " << offset << "). Attempting decryption..." << std::endl;

	// Resolve the password: explicit CLI password first, else sibling .key file.
	// BitLocker may still proceed without one when a sibling FVEK is available.
	std::string password = explicitPassword_;
	if (password.empty()) {
		auto key = KeyFileLoader::loadForPartition(imagePath_, static_cast<int>(partNum), keyFileDir_);
		if (key) password = *key;
	}

	DecryptedPartition dp;
	dp.encType = encType;
	std::string errMsg;
	bool ok = false;
	if (!password.empty()) {
		ok = decryptor_->decrypt(imagePath_, offset, password, dp, errMsg);
	}
	if (!ok) {
		// Password unlock failed (or no password). For BitLocker, try the FVEK
		// direct-decrypt path: dislocker/libbde cannot handle AES-XTS-128 on
		// older versions, but a FVEK recovered from memory decrypts directly.
		if (encType == EncryptionType::BITLOCKER) {
			auto fvekPath = KeyFileLoader::loadFvekForPartition(
				imagePath_, static_cast<int>(partNum), keyFileDir_);
			if (fvekPath) {
					std::cout << "    Trying sibling FVEK direct decrypt..." << std::endl;
				DecryptedPartition dpFvek;
				std::string fvekErr;
				if (decryptor_->decryptBitlockerWithFvek(imagePath_, offset, *fvekPath,
				                                         dpFvek, fvekErr)) {
					dp = dpFvek;
					ok = true;
				} else {
					std::cout << "    FVEK decrypt failed: " << fvekErr << std::endl;
				}
			}
		}
	}
	if (!ok) {
		std::cout << "    Decryption failed for partition " << partNum
		          << ": " << errMsg << std::endl;
		return false;
	}

	// Probe the decrypted volume's filesystem type so callers can label it.
	// Open the decrypted path through a fresh TSK image handle (it's a raw
	// device/file now, not the encrypted one).
	DecryptedPartition* stored = nullptr;
	{
		TSK_IMG_INFO* decImg = tsk_img_open_sing(dp.accessiblePath.c_str(),
		                                          TSK_IMG_TYPE_DETECT, 0);
		std::string fsType = "unknown";
		if (decImg) {
			TSK_FS_INFO* decFs = tsk_fs_open_img(decImg, 0, TSK_FS_TYPE_DETECT);
			if (decFs) {
				const char* tn = tsk_fs_type_toname(decFs->ftype);
				if (tn) fsType = tn;
				tsk_fs_close(decFs);
			}
			tsk_img_close(decImg);
		}
		out.num = partNum;
		out.offset = offset;
		out.desc = desc;
		out.fsType = fsType;
		out.isEncrypted = true;
		out.encType = encType;
		out.decryptedPath = dp.accessiblePath;
		decryptedParts_.push_back(dp);
		stored = &decryptedParts_.back();
		std::cout << "    Decryption succeeded: partition " << partNum
		          << " (" << fsType << ") accessible at " << dp.accessiblePath
		          << std::endl;
	}
	(void)stored;
	return true;
}

bool ImageAnalyzer::extractDecryptedPartition(const PartitionEntry& part) {
	// The decrypted volume is a raw block device or file. Open it with a fresh
	// TSK image handle and walk the filesystem directly — this reuses the
	// universal TSK walker without needing loop/mount privileges.
	std::cout << "  Extracting decrypted partition " << part.num
	          << " (" << DecryptionModule::encryptionTypeName(part.encType)
	          << " -> " << part.fsType << ") from " << part.decryptedPath
	          << "..." << std::endl;

	const bool mountedDirectory = fs::is_directory(part.decryptedPath);
	TSK_IMG_INFO* decImg = nullptr;
	bool opened = false;
	if (!mountedDirectory) {
		const char* path = part.decryptedPath.c_str();
		decImg = tsk_img_open_sing(path, TSK_IMG_TYPE_DETECT, 0);
		if (decImg) {
			// Reuse the TSK walker against the decrypted image. The walker opens its
			// own FS handle from offset 0 on the given image.
			tskWalker_ = std::make_unique<TskFilesystemWalker>(decImg, 0);
			opened = tskWalker_->open();
		} else {
			std::cerr << "  Cannot open decrypted volume " << part.decryptedPath
			          << " with TSK: " << tsk_error_get() << std::endl;
		}
	}

	int fileCount = 0;
	int maxLog = forensics::ConfigManager::instance().getMaxLogDisplayFiles();
	bool success = false;

	if (opened) {
		std::cout << "  Walking decrypted volume (" << tskWalker_->getFsType() << ")..." << std::endl;
		success = tskWalker_->walk([this, &part, &fileCount, maxLog](const FileRecord& record) -> bool {
			if (isCancelled()) return false;
			FileRecord r = record;
			// Tag extracted files so their origin (decrypted partition) is visible.
			r.partitionNum = static_cast<int>(part.num);
			if (dbManager_->insertFileRecord(r)) {
				fileCount++;
				if (fileCount <= maxLog) {
					std::cout << "  [" << fileCount << "] " << r.path << std::endl;
				} else if (fileCount % (maxLog * 5) == 0) {
					std::cout << "  ... processing: [" << fileCount << "] " << r.path
					          << " ..." << std::endl;
				}
			}
			return true;
		});
		tskWalker_->close();
	}

	if (decImg) tsk_img_close(decImg);

	if (isCancelled()) return false;

	if (success && fileCount > 0) {
		std::cout << "  Decrypted partition " << part.num << " yielded "
		          << fileCount << " files." << std::endl;
		AuditLog::instance().log("SYSTEM", "DECRYPT_EXTRACTION_COMPLETE",
			"Extracted " + std::to_string(fileCount) + " files from decrypted partition " +
			std::to_string(part.num) + " (" +
			DecryptionModule::encryptionTypeName(part.encType) + ")");
		return true;
	}

#ifdef __linux__
	// TSK could not parse the decrypted FS (e.g. some NTFS variants). Fall back
	// to a native read-only mount of the decrypted device/file.
	std::cout << "  TSK could not walk the decrypted volume; trying native mount..." << std::endl;
	nativeWalker_ = std::make_unique<NativeFilesystemWalker>(part.decryptedPath, 0);
	nativeWalker_->setFilesystemType(normalizeMountFilesystemType(part.fsType));
	if (nativeWalker_->initialize()) {
		fileCount = 0;
		success = nativeWalker_->walkFilesystem([this, &part, &fileCount](const NativeFileInfo& nf) -> bool {
			if (isCancelled()) return false;
			FileRecord r;
			r.inode = nf.inode;
			r.name = nf.name;
			r.path = nf.path;
			r.size = nf.size;
			r.atime = nf.atime;
			r.mtime = nf.mtime;
			r.ctime = nf.ctime;
			r.crtime = 0;
			uint16_t ft = nf.mode & S_IFMT;
			r.type = nf.is_directory ? "DIR" :
			         (ft == S_IFREG ? "REG" : (ft == S_IFLNK ? "LNK" : "OTHER"));
			r.isDeleted = nf.is_allocated ? 0 : 1;
			r.isAllocated = nf.is_allocated ? 1 : 0;
			r.uid = nf.uid;
			r.gid = nf.gid;
			r.partitionNum = static_cast<int>(part.num);
			if (dbManager_->insertFileRecord(r)) fileCount++;
			return true;
		});
		if (success && fileCount > 0) {
			std::cout << "  Native mount of decrypted partition " << part.num
			          << " yielded " << fileCount << " files." << std::endl;
			return true;
		}
	}
#endif
	std::cerr << "  Decrypted partition " << part.num << " yielded no files." << std::endl;
	return false;
}

// REMOVED old declaration of fileWalkCallback and processFile since they are now in TskFilesystemWalker
/*
TSK_WALK_RET_ENUM ImageAnalyzer::fileWalkCallback(...) { ... }
bool ImageAnalyzer::processFile(...) { ... }
*/

std::string ImageAnalyzer::detectImageType() {
	if (!imgInfo_) return "Unknown";

	switch (imgInfo_->itype) {
	case TSK_IMG_TYPE_RAW:
		return "RAW/DD";
	case TSK_IMG_TYPE_AFF_AFF:
		return "AFF";
	case TSK_IMG_TYPE_EWF_EWF:
		return "E01/EWF";
	default:
		return "Other";
	}
}

std::string ImageAnalyzer::detectOSType() {
	if (!fsInfo_) return "Unknown";

	switch (fsInfo_->ftype) {
	case TSK_FS_TYPE_NTFS:
		return "Windows (NTFS)";
	case TSK_FS_TYPE_FAT32:
	case TSK_FS_TYPE_FAT16:
	case TSK_FS_TYPE_FAT12:
		return "Windows/DOS (FAT)";
	case TSK_FS_TYPE_EXT2:
	case TSK_FS_TYPE_EXT3:
	case TSK_FS_TYPE_EXT4:
		return "Linux (EXT)";
	case TSK_FS_TYPE_HFS:
	case TSK_FS_TYPE_HFS_DETECT:
		return "macOS (HFS)";
	default:
		return "Unknown";
	}
}

bool ImageAnalyzer::extractWithXFS(const std::string& dbPath) {
	// Create XFS helper
	xfsHelper_ = std::make_unique<XFSHelper>(imgInfo_, partitionOffset_);

	if (!xfsHelper_->initialize()) {
		std::cerr << "Failed to initialize XFS helper" << std::endl;
		return false;
	}

	std::cout << "Using XFS helper to extract files..." << std::endl;

	int fileCount = 0;

	// Walk XFS filesystem
	bool success = xfsHelper_->walkFilesystem([this, &fileCount](const XFSFileInfo& xfsFile) -> bool {
		// Convert XFSFileInfo to FileRecord
		FileRecord record;
		record.inode = xfsFile.inode;
		record.name = xfsFile.name;
		record.path = xfsFile.path;
		record.size = xfsFile.size;
		record.atime = xfsFile.atime;
		record.mtime = xfsFile.mtime;
		record.ctime = xfsFile.ctime;
		record.crtime = 0;  // XFS doesn't have creation time

		// Determine file type
		uint16_t fileType = xfsFile.mode & 0xF000;
		if (xfsFile.is_directory) {
			record.type = "DIR";
		} else if (fileType == 0x8000) {  // S_IFREG
			record.type = "REG";
		} else if (fileType == 0xA000) {  // S_IFLNK
			record.type = "LNK";
		} else {
			record.type = "OTHER";
		}

		record.isDeleted = xfsFile.is_allocated ? 0 : 1;
		record.isAllocated = xfsFile.is_allocated ? 1 : 0;
		record.uid = xfsFile.uid;
		record.gid = xfsFile.gid;

		// Format permissions
		std::ostringstream perms;
		perms << std::oct << (xfsFile.mode & 0777);
		record.permissions = perms.str();

		// Insert into database
		if (dbManager_->insertFileRecord(record)) {
			fileCount++;
			int max_log = forensics::ConfigManager::instance().getMaxLogDisplayFiles();
			if (fileCount <= max_log) {
			    // For XFS/Native we might be using different struct names, but they both have .name and .size
			    // In this scope, we'll try to find the record or the source file object
			    std::cout << "  [" << fileCount << "] " << record.name << " (" << record.size << " bytes)" << std::endl;
			} else if (fileCount % (max_log * 5) == 0) {
			    std::cout << "  ... processing: [" << fileCount << "] " << record.name << " ..." << std::endl;
			}

		}

		return true;  // Continue walking
	});

	if (success) {
		std::cout << "XFS extraction completed successfully" << std::endl;
		std::cout << "Total files extracted: " << fileCount << std::endl;
		AuditLog::instance().log("SYSTEM", "XFS_EXTRACTION_COMPLETE", "XFS extraction completed, files: " + std::to_string(fileCount));
	} else {
		std::cerr << "XFS extraction failed" << std::endl;
	}

	return success;
}

bool ImageAnalyzer::extractWithNativeMount(const std::string& dbPath) {
#ifdef __linux__
	// Create native filesystem walker
	nativeWalker_ = std::make_unique<NativeFilesystemWalker>(imagePath_, partitionOffset_);
	nativeWalker_->setFilesystemType(normalizeMountFilesystemType("xfs"));

	if (!nativeWalker_->initialize()) {
		std::cerr << "Failed to initialize native filesystem walker" << std::endl;
		std::cerr << "Note: This requires root privileges. Please run with sudo." << std::endl;
		return false;
	}

	std::cout << "Using native mount to extract files..." << std::endl;

	int fileCount = 0;

	// Walk filesystem
	bool success = nativeWalker_->walkFilesystem([this, &fileCount](const NativeFileInfo& nativeFile) -> bool {
		// Convert NativeFileInfo to FileRecord
		FileRecord record;
		record.inode = nativeFile.inode;
		record.name = nativeFile.name;
		record.path = nativeFile.path;
		record.size = nativeFile.size;
		record.atime = nativeFile.atime;
		record.mtime = nativeFile.mtime;
		record.ctime = nativeFile.ctime;
		record.crtime = 0;  // XFS doesn't have creation time

		// Determine file type
		uint16_t fileType = nativeFile.mode & S_IFMT;
		if (nativeFile.is_directory) {
			record.type = "DIR";
		} else if (fileType == S_IFREG) {
			record.type = "REG";
		} else if (fileType == S_IFLNK) {
			record.type = "LNK";
		} else {
			record.type = "OTHER";
		}

		record.isDeleted = nativeFile.is_allocated ? 0 : 1;
		record.isAllocated = nativeFile.is_allocated ? 1 : 0;
		record.uid = nativeFile.uid;
		record.gid = nativeFile.gid;

		// Format permissions
		std::ostringstream perms;
		perms << std::oct << (nativeFile.mode & 0777);
		record.permissions = perms.str();

		// Insert into database
		if (dbManager_->insertFileRecord(record)) {
			fileCount++;
			int max_log = forensics::ConfigManager::instance().getMaxLogDisplayFiles();
			if (fileCount <= max_log) {
			    // For XFS/Native we might be using different struct names, but they both have .name and .size
			    // In this scope, we'll try to find the record or the source file object
			    std::cout << "  [" << fileCount << "] " << record.name << " (" << record.size << " bytes)" << std::endl;
			} else if (fileCount % (max_log * 5) == 0) {
			    std::cout << "  ... processing: [" << fileCount << "] " << record.name << " ..." << std::endl;
			}

		}

		return true;  // Continue walking
	});

	if (success) {
		std::cout << "Native mount extraction completed successfully" << std::endl;
		std::cout << "Total files extracted: " << fileCount << std::endl;
		AuditLog::instance().log("SYSTEM", "NATIVE_EXTRACTION_COMPLETE", "Native mount extraction completed, files: " + std::to_string(fileCount));
	} else {
		std::cerr << "Native mount extraction failed" << std::endl;
	}

	return success;
#else
	std::cerr << "Error: Native mount not available on non-Linux platforms" << std::endl;
	return false;
#endif
}