#include "FileCarver.h"
#include <iostream>
#include <fstream>
#include <algorithm>
#include <filesystem>
#include <cstring>
#include <chrono>
#include <sqlite3.h>

namespace fs = std::filesystem;

// Context struct to pass to callback
struct CarvingContext {
    FileCarver* carver;
    TSK_FS_INFO* fs;
    std::string outputDir;
    int recoveredCount;
    CarvingStatistics* stats;
    std::vector<CarvedFileInfo>* carvedFiles;
    CarvingProgressCallback progressCallback;
    uint64_t progressBase;
    uint64_t progressTotal;
    std::vector<std::pair<uint64_t, uint64_t>>* carvedRegions;
    bool validationEnabled;
    std::string databasePath;
};

FileCarver::FileCarver() {
    initializeSignatures();
}

FileCarver::~FileCarver() {}

void FileCarver::initializeSignatures() {
    // ============ IMAGE FORMATS ============
    
    // JPEG: FF D8 FF
    signatures_.push_back({
        "JPEG Image", "jpg",
        {0xFF, 0xD8, 0xFF},
        {0xFF, 0xD9},
        10 * 1024 * 1024  // 10 MB Max
    });

    // PNG: 89 50 4E 47 0D 0A 1A 0A
    signatures_.push_back({
        "PNG Image", "png",
        {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A},
        {0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82},
        10 * 1024 * 1024
    });

    // GIF: GIF89a (more common version)
    signatures_.push_back({
        "GIF Image", "gif",
        {0x47, 0x49, 0x46, 0x38, 0x39, 0x61},
        {0x00, 0x3B},
        5 * 1024 * 1024
    });

    // GIF: GIF87a (older version)
    signatures_.push_back({
        "GIF Image (87a)", "gif",
        {0x47, 0x49, 0x46, 0x38, 0x37, 0x61},
        {0x00, 0x3B},
        5 * 1024 * 1024
    });

    // BMP: 42 4D
    signatures_.push_back({
        "BMP Image", "bmp",
        {0x42, 0x4D},
        {},  // No footer
        50 * 1024 * 1024
    });

    // WEBP: 52 49 46 46 + WEBP
    signatures_.push_back({
        "WebP Image", "webp",
        {0x52, 0x49, 0x46, 0x46},
        {},  // No reliable footer
        20 * 1024 * 1024
    });

    // TIFF (little-endian): 49 49 2A 00
    signatures_.push_back({
        "TIFF Image (LE)", "tiff",
        {0x49, 0x49, 0x2A, 0x00},
        {},
        100 * 1024 * 1024
    });

    // TIFF (big-endian): 4D 4D 00 2A
    signatures_.push_back({
        "TIFF Image (BE)", "tiff",
        {0x4D, 0x4D, 0x00, 0x2A},
        {},
        100 * 1024 * 1024
    });

    // ============ DOCUMENT FORMATS ============

    // PDF: %PDF
    signatures_.push_back({
        "PDF Document", "pdf",
        {0x25, 0x50, 0x44, 0x46},
        {0x25, 0x25, 0x45, 0x4F, 0x46},  // %%EOF
        100 * 1024 * 1024
    });

    // ============ ARCHIVE FORMATS ============

    // ZIP: 50 4B 03 04 (also DOCX, XLSX, PPTX, ODT, etc.)
    signatures_.push_back({
        "ZIP Archive", "zip",
        {0x50, 0x4B, 0x03, 0x04},
        {0x50, 0x4B, 0x05, 0x06},  // End of central directory
        500 * 1024 * 1024
    });

    // RAR 5.0+: 52 61 72 21 1A 07 01 00
    signatures_.push_back({
        "RAR Archive (5.0+)", "rar",
        {0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x01, 0x00},
        {},
        500 * 1024 * 1024
    });

    // RAR 4.x: 52 61 72 21 1A 07 00
    signatures_.push_back({
        "RAR Archive (4.x)", "rar",
        {0x52, 0x61, 0x72, 0x21, 0x1A, 0x07, 0x00},
        {},
        500 * 1024 * 1024
    });

    // 7z: 37 7A BC AF 27 1C
    signatures_.push_back({
        "7-Zip Archive", "7z",
        {0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C},
        {},
        500 * 1024 * 1024
    });

    // GZIP: 1F 8B 08
    signatures_.push_back({
        "GZIP Archive", "gz",
        {0x1F, 0x8B, 0x08},
        {},
        200 * 1024 * 1024
    });

    // BZIP2: 42 5A 68
    signatures_.push_back({
        "BZIP2 Archive", "bz2",
        {0x42, 0x5A, 0x68},
        {},
        200 * 1024 * 1024
    });

    // XZ: FD 37 7A 58 5A 00
    signatures_.push_back({
        "XZ Archive", "xz",
        {0xFD, 0x37, 0x7A, 0x58, 0x5A, 0x00},
        {},
        200 * 1024 * 1024
    });

    // ============ AUDIO FORMATS ============

    // MP3 with ID3v2: 49 44 33
    signatures_.push_back({
        "MP3 Audio (ID3)", "mp3",
        {0x49, 0x44, 0x33},
        {},
        50 * 1024 * 1024
    });

    // MP3 Frame sync: FF FB, FF FA, FF F3, FF F2
    signatures_.push_back({
        "MP3 Audio (Frame)", "mp3",
        {0xFF, 0xFB},
        {},
        50 * 1024 * 1024
    });

    // WAV: 52 49 46 46 + WAVE
    signatures_.push_back({
        "WAV Audio", "wav",
        {0x52, 0x49, 0x46, 0x46},
        {},
        200 * 1024 * 1024
    });

    // FLAC: 66 4C 61 43
    signatures_.push_back({
        "FLAC Audio", "flac",
        {0x66, 0x4C, 0x61, 0x43},
        {},
        200 * 1024 * 1024
    });

    // OGG: 4F 67 67 53
    signatures_.push_back({
        "OGG Audio/Video", "ogg",
        {0x4F, 0x67, 0x67, 0x53},
        {},
        200 * 1024 * 1024
    });

    // ============ VIDEO FORMATS ============

    // MP4/MOV: ftyp at offset 4
    signatures_.push_back({
        "MP4/MOV Video", "mp4",
        {0x66, 0x74, 0x79, 0x70},  // "ftyp"
        {},
        2ULL * 1024 * 1024 * 1024,  // 2GB
        -4  // ftyp appears at offset 4, so go back 4 bytes
    });

    // AVI: 52 49 46 46 + AVI
    signatures_.push_back({
        "AVI Video", "avi",
        {0x52, 0x49, 0x46, 0x46},
        {},
        2ULL * 1024 * 1024 * 1024
    });

    // MKV/WebM: 1A 45 DF A3
    signatures_.push_back({
        "MKV/WebM Video", "mkv",
        {0x1A, 0x45, 0xDF, 0xA3},
        {},
        2ULL * 1024 * 1024 * 1024
    });

    // FLV: 46 4C 56 01
    signatures_.push_back({
        "FLV Video", "flv",
        {0x46, 0x4C, 0x56, 0x01},
        {},
        500 * 1024 * 1024
    });

    // ============ DATABASE FORMATS ============

    // SQLite: 53 51 4C 69 74 65 20 66 6F 72 6D 61 74 20 33 00
    signatures_.push_back({
        "SQLite Database", "sqlite",
        {0x53, 0x51, 0x4C, 0x69, 0x74, 0x65, 0x20, 0x66, 0x6F, 0x72, 0x6D, 0x61, 0x74, 0x20, 0x33, 0x00},
        {},
        500 * 1024 * 1024
    });

    // ============ EXECUTABLE FORMATS ============

    // ELF: 7F 45 4C 46
    signatures_.push_back({
        "ELF Executable", "elf",
        {0x7F, 0x45, 0x4C, 0x46},
        {},
        100 * 1024 * 1024
    });

    // Windows PE: 4D 5A (MZ)
    signatures_.push_back({
        "Windows Executable", "exe",
        {0x4D, 0x5A},
        {},
        100 * 1024 * 1024
    });

    // ============ EMAIL FORMATS ============

    // PST (Outlook): 21 42 44 4E
    signatures_.push_back({
        "Outlook PST", "pst",
        {0x21, 0x42, 0x44, 0x4E},
        {},
        2ULL * 1024 * 1024 * 1024
    });
}

// Check if a region has already been carved
static bool isRegionCarved(const std::vector<std::pair<uint64_t, uint64_t>>& regions, 
                           uint64_t start, uint64_t end) {
    for (const auto& region : regions) {
        // Check for overlap
        if (start < region.second && end > region.first) {
            return true;
        }
    }
    return false;
}

// Carving block walk callback
TSK_WALK_RET_ENUM carving_block_walk_ctx(const TSK_FS_BLOCK* block, void* ptr) {
    CarvingContext* ctx = static_cast<CarvingContext*>(ptr);
    size_t blockSize = ctx->fs->block_size;
    
    ctx->stats->blocksScanned++;

    if (ctx->carver->cancelCallback_ && ctx->carver->cancelCallback_()) {
        return TSK_WALK_STOP;
    }

    // Report progress every 1000 blocks
    if (ctx->progressCallback && ctx->stats->blocksScanned % 1000 == 0) {
        uint64_t total = ctx->fs->last_block - ctx->fs->first_block + 1;
        ctx->progressCallback(ctx->stats->blocksScanned,
                              ctx->progressTotal, "");
    }

    if (block->flags & TSK_FS_BLOCK_FLAG_UNALLOC) {
        ctx->stats->unallocatedBlocks++;
        
        const auto& signatures = ctx->carver->getSignatures();
        
        for (const auto& sig : signatures) {
            // Search for signature in this block
            auto it = std::search(
                (uint8_t*)block->buf, (uint8_t*)block->buf + blockSize,
                sig.header.begin(), sig.header.end()
            );

            if (it != (uint8_t*)block->buf + blockSize) {
                // Found a header!
                size_t offsetInBlock = it - (uint8_t*)block->buf;
                uint64_t startByteAddr = block->addr * blockSize + offsetInBlock;
                const uint64_t fsBase = static_cast<uint64_t>(ctx->fs->offset);

                // Apply header offset adjustment
                if (sig.headerOffset != 0) {
                    if (sig.headerOffset < 0 && static_cast<size_t>(-sig.headerOffset) > startByteAddr) {
                        continue;  // Can't go before start of image
                    }
                    startByteAddr += sig.headerOffset;
                }
                
                // Check if this region was already carved
                if (isRegionCarved(*ctx->carvedRegions,
                                   fsBase + startByteAddr,
                                   fsBase + startByteAddr + sig.maxSize)) {
                    continue;
                }
                
                // Construct output filename
                std::string filename = "carved_" + std::to_string(fsBase + startByteAddr) + "." + sig.extension;
                std::string outPath = ctx->outputDir + "/" + filename;
                
                // Report progress
                if (ctx->progressCallback) {
                    uint64_t total = ctx->fs->last_block - ctx->fs->first_block + 1;
                    ctx->progressCallback(ctx->stats->blocksScanned,
                                          ctx->progressTotal, filename);
                }
                
                std::ofstream outFile(outPath, std::ios::binary);
                if (!outFile) {
                    ctx->stats->errors++;
                    continue;
                }

                size_t currentSize = 0;
                char buffer[4096];
                uint64_t currentOffset = startByteAddr;
                const uint64_t fsEnd = static_cast<uint64_t>(ctx->fs->block_count) *
                                       static_cast<uint64_t>(ctx->fs->block_size);
                const uint64_t available = currentOffset < fsEnd ? fsEnd - currentOffset : 0;
                const uint64_t maxRead = std::min<uint64_t>(sig.maxSize, available);

                while (currentSize < maxRead) {
                    size_t request = std::min<uint64_t>(sizeof(buffer), maxRead - currentSize);
                    ssize_t cnt = tsk_img_read(ctx->fs->img_info, fsBase + currentOffset, buffer, request);
                    if (cnt <= 0) break;

                    // Check for footer if it exists
                    if (!sig.footer.empty()) {
                        auto fit = std::search(
                            (uint8_t*)buffer, (uint8_t*)buffer + cnt,
                            sig.footer.begin(), sig.footer.end()
                        );
                        if (fit != (uint8_t*)buffer + cnt) {
                            // Footer found
                            size_t writeLen = (fit - (uint8_t*)buffer) + sig.footer.size();
                            outFile.write(buffer, writeLen);
                            currentSize += writeLen;
                            break;
                        }
                    }

                    outFile.write(buffer, cnt);
                    currentSize += cnt;
                    currentOffset += cnt;
                    
                    // For files without footer, use fixed size if specified
                    if (sig.hasFixedSize && currentSize >= sig.maxSize) {
                        break;
                    }
                }
                
                outFile.close();
                
                // Remove empty or tiny files (< 100 bytes)
                if (currentSize < 100) {
                    fs::remove(outPath);
                    continue;
                }
                
                const uint64_t imageStartByte = fsBase + startByteAddr;
                // Track carved regions in image-absolute coordinates so two
                // partitions with equal relative offsets do not suppress each
                // other's recovered files.
                ctx->carvedRegions->push_back({imageStartByte, imageStartByte + currentSize});

                // Create carved file info
                CarvedFileInfo info;
                info.path = outPath;
                info.signatureName = sig.name;
                info.extension = sig.extension;
                info.sourceOffset = imageStartByte;
                info.size = currentSize;
                if (ctx->validationEnabled) {
                    info.validated = ctx->carver->validateCarvedFile(outPath, sig, info.validationMessage);
                } else {
                    info.validated = false;
                    info.validationMessage = "Validation disabled";
                }

                ctx->carvedFiles->push_back(info);
                ctx->recoveredCount++;

                // Update statistics
                ctx->stats->totalFilesCarved++;
                ctx->stats->totalBytesCarved += currentSize;
                ctx->stats->filesByType[sig.name]++;

                if (info.validated) {
                    ctx->stats->validFiles++;
                } else {
                    ctx->stats->invalidFiles++;
                }
            }
        }
    }
    return TSK_WALK_CONT;
}

int FileCarver::carveFilesystem(TSK_FS_INFO* fs_info, const std::string& outputDir,
                                uint64_t progressBase, uint64_t progressTotal) {
    if (!fs::exists(outputDir)) {
        fs::create_directories(outputDir);
    }

    CarvingContext ctx;
    ctx.carver = this;
    ctx.fs = fs_info;
    ctx.outputDir = outputDir;
    ctx.recoveredCount = 0;
    ctx.stats = &statistics_;
    ctx.carvedFiles = &carvedFiles_;
    ctx.progressCallback = progressCallback_;
    ctx.progressBase = progressBase;
    ctx.progressTotal = progressTotal > 0 ? progressTotal :
        (fs_info->last_block - fs_info->first_block + 1);
    ctx.carvedRegions = &carvedRegions_;
    ctx.validationEnabled = validationEnabled_;
    ctx.databasePath = databasePath_;

    // Walk unallocated blocks
    if (tsk_fs_block_walk(fs_info, fs_info->first_block, fs_info->last_block,
        (TSK_FS_BLOCK_WALK_FLAG_ENUM)(TSK_FS_BLOCK_WALK_FLAG_UNALLOC),
        carving_block_walk_ctx, &ctx)) {
        // Errors are printed by TSK
    }

    return ctx.recoveredCount;
}

int FileCarver::carve(const std::string& imagePath, const std::string& outputDir, uint64_t partitionOffset) {
    // Reset state
    carvedFiles_.clear();
    carvedRegions_.clear();
    statistics_ = CarvingStatistics();

    auto startTime = std::chrono::high_resolution_clock::now();

    if (!fs::exists(outputDir)) {
        fs::create_directories(outputDir);
    }

    TSK_IMG_INFO* img = tsk_img_open_utf8_sing(imagePath.c_str(), TSK_IMG_TYPE_DETECT, 0);
    if (!img) {
        std::cerr << "FileCarver: Failed to open image: " << imagePath << std::endl;
        return 0;
    }

    int recoveredTotal = 0;
    std::cout << "FileCarver: Registered " << signatures_.size() << " file signatures" << std::endl;

    TSK_FS_INFO* fs_info = tsk_fs_open_img(img, partitionOffset, TSK_FS_TYPE_DETECT);
    if (fs_info) {
        std::cout << "FileCarver: Scanning unallocated blocks..." << std::endl;
        recoveredTotal += carveFilesystem(fs_info, outputDir);
        tsk_fs_close(fs_info);
    } else if (partitionOffset == 0) {
        // Partitioned disk image: offset 0 holds a volume system, not a
        // filesystem. Carve every openable partition into its own subdirectory.
        TSK_VS_INFO* vs = tsk_vs_open(img, 0, TSK_VS_TYPE_DETECT);
        if (vs) {
            std::cout << "FileCarver: partitioned image — carving each partition's unallocated space" << std::endl;
            for (TSK_PNUM_T i = 0; i < vs->part_count; i++) {
                const TSK_VS_PART_INFO* part = tsk_vs_part_get(vs, i);
                if (!part || !(part->flags & TSK_VS_PART_FLAG_ALLOC)) continue;
                TSK_OFF_T off = part->start * vs->block_size;
                TSK_FS_INFO* pfs = tsk_fs_open_img(img, off, TSK_FS_TYPE_DETECT);
                if (!pfs) continue;
                std::cout << "FileCarver: partition " << i << " (offset " << off << ")" << std::endl;
                std::string subDir = outputDir + "/part" + std::to_string(i);
                uint64_t partitionBlocks = pfs->last_block - pfs->first_block + 1;
                recoveredTotal += carveFilesystem(pfs, subDir, statistics_.blocksScanned,
                                                  statistics_.blocksScanned + partitionBlocks);
                tsk_fs_close(pfs);
            }
            tsk_vs_close(vs);
        } else {
            std::cerr << "FileCarver: neither filesystem nor volume system found in image" << std::endl;
        }
    } else {
        std::cerr << "FileCarver: Failed to open filesystem at offset " << partitionOffset << std::endl;
    }

    auto endTime = std::chrono::high_resolution_clock::now();
    statistics_.elapsedSeconds = std::chrono::duration<double>(endTime - startTime).count();

    // Print summary
    std::cout << "\n=== FileCarver Summary ===" << std::endl;
    std::cout << "Recovered: " << recoveredTotal << " files" << std::endl;
    std::cout << "Total size: " << (statistics_.totalBytesCarved / 1024) << " KB" << std::endl;
    std::cout << "Blocks scanned: " << statistics_.blocksScanned << std::endl;
    std::cout << "Unallocated blocks: " << statistics_.unallocatedBlocks << std::endl;
    std::cout << "Time elapsed: " << statistics_.elapsedSeconds << " seconds" << std::endl;

    if (!statistics_.filesByType.empty()) {
        std::cout << "\nFiles by type:" << std::endl;
        for (const auto& [type, count] : statistics_.filesByType) {
            std::cout << "  " << type << ": " << count << std::endl;
        }
    }

    // Log to database if path is set
    if (!databasePath_.empty()) {
        initDatabaseTable();
        for (const auto& info : carvedFiles_) {
            logToDatabase(info);
        }
    }

    tsk_img_close(img);

    return recoveredTotal;
}

void FileCarver::initDatabaseTable() {
    if (databasePath_.empty()) return;
    
    sqlite3* db;
    if (sqlite3_open(databasePath_.c_str(), &db) != SQLITE_OK) {
        std::cerr << "FileCarver: Failed to open database: " << databasePath_ << std::endl;
        return;
    }
    
    const char* sql = R"(
        CREATE TABLE IF NOT EXISTS carved_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            signature_name TEXT,
            extension TEXT,
            source_offset INTEGER,
            size INTEGER,
            validated INTEGER,
            validation_message TEXT,
            carved_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
    )";
    
    char* errMsg = nullptr;
    if (sqlite3_exec(db, sql, nullptr, nullptr, &errMsg) != SQLITE_OK) {
        std::cerr << "FileCarver: SQL error: " << errMsg << std::endl;
        sqlite3_free(errMsg);
    }
    
    sqlite3_close(db);
}

void FileCarver::logToDatabase(const CarvedFileInfo& info) {
    if (databasePath_.empty()) return;
    
    sqlite3* db;
    if (sqlite3_open(databasePath_.c_str(), &db) != SQLITE_OK) {
        return;
    }
    
    const char* sql = R"(
        INSERT INTO carved_files (path, signature_name, extension, source_offset, size, validated, validation_message)
        VALUES (?, ?, ?, ?, ?, ?, ?);
    )";
    
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(stmt, 1, info.path.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 2, info.signatureName.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(stmt, 3, info.extension.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(stmt, 4, info.sourceOffset);
        sqlite3_bind_int64(stmt, 5, info.size);
        sqlite3_bind_int(stmt, 6, info.validated ? 1 : 0);
        sqlite3_bind_text(stmt, 7, info.validationMessage.c_str(), -1, SQLITE_TRANSIENT);
        
        sqlite3_step(stmt);
        sqlite3_finalize(stmt);
    }
    
    sqlite3_close(db);
}

// Validation methods - basic implementations
bool FileCarver::validateCarvedFile(const std::string& filepath, const CarvingSignature& sig, std::string& message) {
    if (sig.extension == "jpg" || sig.extension == "jpeg") {
        return validateJPEG(filepath, message);
    } else if (sig.extension == "png") {
        return validatePNG(filepath, message);
    } else if (sig.extension == "pdf") {
        return validatePDF(filepath, message);
    } else if (sig.extension == "zip") {
        return validateZIP(filepath, message);
    }
    message = "No content validator for this type";
    return false;
}

bool FileCarver::validateJPEG(const std::string& filepath, std::string& message) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) {
        message = "Cannot open file";
        return false;
    }
    
    // Check header
    uint8_t header[3];
    file.read(reinterpret_cast<char*>(header), 3);
    if (header[0] != 0xFF || header[1] != 0xD8 || header[2] != 0xFF) {
        message = "Invalid JPEG header";
        return false;
    }
    
    // Check footer
    file.seekg(-2, std::ios::end);
    uint8_t footer[2];
    file.read(reinterpret_cast<char*>(footer), 2);
    if (footer[0] != 0xFF || footer[1] != 0xD9) {
        message = "Missing JPEG footer";
        return false;
    }
    
    message = "Valid JPEG";
    return true;
}

bool FileCarver::validatePNG(const std::string& filepath, std::string& message) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) {
        message = "Cannot open file";
        return false;
    }
    
    uint8_t header[8];
    file.read(reinterpret_cast<char*>(header), 8);
    
    const uint8_t pngHeader[] = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    if (memcmp(header, pngHeader, 8) != 0) {
        message = "Invalid PNG header";
        return false;
    }
    
    message = "Valid PNG header";
    return true;
}

bool FileCarver::validatePDF(const std::string& filepath, std::string& message) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) {
        message = "Cannot open file";
        return false;
    }
    
    char header[5];
    file.read(header, 4);
    header[4] = '\0';
    
    if (std::string(header) != "%PDF") {
        message = "Invalid PDF header";
        return false;
    }
    
    message = "Valid PDF header";
    return true;
}

bool FileCarver::validateZIP(const std::string& filepath, std::string& message) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) {
        message = "Cannot open file";
        return false;
    }
    
    uint8_t header[4];
    file.read(reinterpret_cast<char*>(header), 4);
    
    if (header[0] != 0x50 || header[1] != 0x4B || header[2] != 0x03 || header[3] != 0x04) {
        message = "Invalid ZIP header";
        return false;
    }
    
    message = "Valid ZIP header";
    return true;
}

// Placeholder for member functions - logic moved to callback
void FileCarver::processUnallocatedBlock(const void* data, size_t len, uint64_t addr) {
    (void)data; (void)len; (void)addr;
}

void FileCarver::extractFile(TSK_FS_INFO* fs, uint64_t startBlock, const CarvingSignature& sig, const std::string& outputDir) {
    (void)fs; (void)startBlock; (void)sig; (void)outputDir;
}
