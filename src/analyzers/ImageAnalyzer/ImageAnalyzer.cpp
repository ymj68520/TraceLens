#include "ImageAnalyzer.h"
#include "DatabaseManager/DatabaseManager.h"
#include "XFSHelper.h"
#include "NativeFilesystemWalker.h"
#include "TskFilesystemWalker.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <cstring>
#include <sstream>
#include <iomanip>

ImageAnalyzer::ImageAnalyzer(const std::string& imagePath)
	: imagePath_(imagePath), imgInfo_(nullptr), fsInfo_(nullptr),
	  partitionOffset_(0), isXFS_(false), xfsMode_(XFSMode::Auto) {
}

ImageAnalyzer::~ImageAnalyzer() {
	closeImage();
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

	TSK_OFF_T offset = 0;
	bool fsOpened = false;

	if (vsInfo) {
		std::cout << "Volume system detected" << std::endl;
		std::cout << "  Partitions: " << vsInfo->part_count << std::endl;

		// Try each allocated partition until we find one that works
		for (TSK_PNUM_T i = 0; i < vsInfo->part_count && !fsOpened; i++) {
			const TSK_VS_PART_INFO* part = tsk_vs_part_get(vsInfo, i);
			if (part && (part->flags & TSK_VS_PART_FLAG_ALLOC)) {
				offset = part->start * vsInfo->block_size;
				partitionOffset_ = offset;  // Store for native mount
				std::cout << "  Trying partition " << i
				          << " at offset " << offset
				          << " (desc: " << part->desc << ")" << std::endl;

				// Try to open filesystem on this partition
				fsInfo_ = tsk_fs_open_img(imgInfo_, offset, TSK_FS_TYPE_DETECT);
				if (fsInfo_) {
					std::cout << "    Filesystem type: " << tsk_fs_type_toname(fsInfo_->ftype) << std::endl;

					// Check if this filesystem is XFS
					const char* fsTypeName = tsk_fs_type_toname(fsInfo_->ftype);
					isXFS_ = (fsTypeName && strstr(fsTypeName, "xfs"));

#ifdef TSK_FS_TYPE_XFS
					if (fsInfo_->ftype == TSK_FS_TYPE_XFS) {
						isXFS_ = true;
					}
#endif

					if (isXFS_) {
						std::cout << "    Detected XFS filesystem - will use alternative method if TSK fails" << std::endl;
					}

					fsOpened = true;
					break;
				} else {
					std::cout << "    Could not open filesystem: " << tsk_error_get() << std::endl;

#ifdef __linux__
					// On Linux, if TSK can't open it but partition description suggests Linux filesystem
					// assume it might be XFS and try native mount later
					// Only use the first Linux partition we find
					if (strstr(part->desc, "Linux") && !isXFS_) {
						std::cout << "    Note: TSK failed on Linux partition, will try native mount" << std::endl;
						isXFS_ = true;  // Assume XFS for native mount attempt
						partitionOffset_ = offset;  // Store this partition's offset
						fsOpened = true;  // Mark as "opened" to prevent trying other partitions
						break;  // Stop trying other partitions
					}
#endif
				}
			}
		}

		tsk_vs_close(vsInfo);

		// If no filesystem was opened but we detected potential XFS, allow continuing
		if (!fsOpened && isXFS_) {
#ifdef __linux__
			std::cout << "Note: Will attempt native mount for XFS" << std::endl;
			// Create a fake fsInfo structure just to pass checks
			// We won't actually use it
			return true;
#else
			std::cerr << "Error: No valid filesystem found in any partition" << std::endl;
			return false;
#endif
		}

		if (!fsOpened) {
			std::cerr << "Error: No valid filesystem found in any partition" << std::endl;
			return false;
		}
	} else {
		// No partition table, try opening filesystem directly
		std::cout << "No volume system detected, trying direct filesystem access..." << std::endl;
		fsInfo_ = tsk_fs_open_img(imgInfo_, 0, TSK_FS_TYPE_DETECT);
		if (!fsInfo_) {
			std::cerr << "Error opening filesystem: " << tsk_error_get() << std::endl;
			return false;
		}

		// Check if XFS
		const char* fsTypeName = tsk_fs_type_toname(fsInfo_->ftype);
		isXFS_ = (fsTypeName && strstr(fsTypeName, "xfs"));
	}

	if (fsInfo_) {
		std::cout << "Filesystem opened successfully" << std::endl;
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

	// Handle XFS mode selection
	if (isXFS_) {
		// If user explicitly requested native mode
		if (xfsMode_ == XFSMode::Native) {
#ifdef __linux__
			std::cout << "Using native mount method (XFS mode: native)..." << std::endl;
			return extractWithNativeMount(dbPath);
#else
			std::cerr << "Error: Native XFS mount is only supported on Linux" << std::endl;
			std::cerr << "Use --xfs-mode pure or --xfs-mode auto instead" << std::endl;
			return false;
#endif
		}

		// If user explicitly requested pure mode
		if (xfsMode_ == XFSMode::Pure) {
			std::cout << "Using XFS helper (XFS mode: pure)..." << std::endl;
			return extractWithXFS(dbPath);
		}
	}

	// Auto mode or non-XFS filesystem: try TSK first using Universal Walker
	tskWalker_ = std::make_unique<TskFilesystemWalker>(imgInfo_, partitionOffset_);
	
	if (tskWalker_->open()) {
		std::cout << "Walking filesystem using Universal TSK Walker (" << tskWalker_->getFsType() << ")..." << std::endl;
		
		int fileCount = 0;
		bool success = tskWalker_->walk([this, &fileCount](const FileRecord& record) -> bool {
			if (dbManager_->insertFileRecord(record)) {
				fileCount++;
				if (fileCount <= 20) {
					std::cout << "  [" << fileCount << "] " << record.path << std::endl;
				}
			}
			return true;
		});

		tskWalker_->close();
		
		if (success && fileCount > 0) {
			std::cout << "Filesystem walk completed. Total files: " << fileCount << std::endl;
			AuditLog::instance().log("SYSTEM", "EXTRACTION_COMPLETE", "Filesystem walk completed for: " + imagePath_);
			return true;
		} else {
			std::cout << "TSK walk finished with 0 files or error." << std::endl;
		}
	} else {
		std::cout << "TSK could not open filesystem at offset " << partitionOffset_ << std::endl;
	}

	// Falls through to XFS/Native fallback if TSK failed
	if (isXFS_) {
#ifdef __linux__
		std::cout << "Switching to native mount method for XFS..." << std::endl;
		return extractWithNativeMount(dbPath);
#else
		std::cout << "Switching to XFS helper for direct XFS parsing..." << std::endl;
		return extractWithXFS(dbPath);
#endif
	}

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
			if (fileCount <= 20) {
				std::cout << "  [" << fileCount << "] " << record.path << std::endl;
			} else if (fileCount == 21) {
				std::cout << "  (showing first 20 files only...)" << std::endl;
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
			if (fileCount <= 20) {
				std::cout << "  [" << fileCount << "] " << record.path << std::endl;
			} else if (fileCount == 21) {
				std::cout << "  (showing first 20 files only...)" << std::endl;
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