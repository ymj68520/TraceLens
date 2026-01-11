# FileCarving

## Overview
The FileCarving module recovers deleted files from unallocated disk space using signature-based carving. It scans raw disk images for known file headers and footers, extracting potential files even when filesystem metadata is no longer available.

## Features
- **30+ File Signatures**: Supports images, documents, archives, audio, video, databases, and executables
- **Smart Carving**: Detects headers and footers to accurately extract files
- **Duplicate Prevention**: Tracks carved regions to avoid extracting the same file multiple times
- **Statistics Tracking**: Reports files recovered, bytes carved, and per-type counts
- **Database Logging**: Optionally logs all carved files to SQLite for audit trail
- **Progress Callbacks**: Integration point for UI progress reporting
- **File Validation**: Basic validation for common formats (JPEG, PNG, PDF, ZIP)

## Supported File Types

| Category | Extensions |
|----------|------------|
| Images | JPG, PNG, GIF, BMP, WEBP, TIFF |
| Documents | PDF |
| Archives | ZIP, RAR, 7Z, GZIP, BZIP2, XZ |
| Audio | MP3, WAV, FLAC, OGG |
| Video | MP4, AVI, MKV, FLV |
| Database | SQLite |
| Executables | ELF, EXE |
| Email | PST |

## Usage

### Command Line
```bash
# Basic carving
./forensic_analyzer disk_image.dd --carve

# Carve to specific output directory
./forensic_analyzer disk_image.dd --carve --carve-out /path/to/output
```

### Programmatic API
```cpp
#include "FileCarving/FileCarver.h"

FileCarver carver;

// Optional: Set progress callback
carver.setProgressCallback([](uint64_t current, uint64_t total, const std::string& file) {
    std::cout << "Progress: " << (100.0 * current / total) << "%" << std::endl;
});

// Optional: Enable database logging
carver.setDatabasePath("carving_log.db");

// Perform carving
int recovered = carver.carve("disk_image.dd", "carved_files/");

// Get statistics
const auto& stats = carver.getStatistics();
std::cout << "Recovered: " << stats.totalFilesCarved << " files" << std::endl;
std::cout << "Total size: " << stats.totalBytesCarved << " bytes" << std::endl;

// Get detailed file list
for (const auto& file : carver.getCarvedFiles()) {
    std::cout << file.path << " (" << file.signatureName << ")" << std::endl;
}
```

### Adding Custom Signatures
```cpp
CarvingSignature customSig;
customSig.name = "Custom Format";
customSig.extension = "custom";
customSig.header = {0x12, 0x34, 0x56, 0x78};
customSig.footer = {0xAB, 0xCD};
customSig.maxSize = 10 * 1024 * 1024;  // 10 MB

carver.addSignature(customSig);
```

## Dependencies
- **The Sleuth Kit (TSK)**: For disk image access and unallocated block walking
- **SQLite3**: For optional database logging
