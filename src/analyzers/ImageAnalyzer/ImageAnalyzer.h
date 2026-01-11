#pragma once

#include <string>
#include <memory>
#include <vector>
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

class ImageAnalyzer {
public:
	explicit ImageAnalyzer(const std::string& imagePath);
	~ImageAnalyzer();

	bool analyze();
	bool extractToDatabase(const std::string& dbPath);
	
	void setXFSMode(XFSMode mode) { xfsMode_ = mode; }

	TSK_IMG_INFO* getImageInfo() const { return imgInfo_; }
	TSK_FS_INFO* getFileSystemInfo() const { return fsInfo_; }

private:
	bool openImage();
	bool openFileSystem();
	void closeImage();
	std::string detectImageType();
	std::string detectOSType();

	// Extraction methods
	bool extractWithXFS(const std::string& dbPath);
	bool extractWithNativeMount(const std::string& dbPath);

	std::string imagePath_;
	TSK_IMG_INFO* imgInfo_;
	TSK_FS_INFO* fsInfo_;
	uint64_t partitionOffset_;
	bool isXFS_;
	XFSMode xfsMode_;

	std::unique_ptr<DatabaseManager> dbManager_;
	std::unique_ptr<XFSHelper> xfsHelper_;
	std::unique_ptr<NativeFilesystemWalker> nativeWalker_;
	std::unique_ptr<TskFilesystemWalker> tskWalker_;
};
