/**
 * @file InnoDBParser.cpp
 * @brief InnoDB 表空间文件解析器实现
 */

#include "InnoDBParser.h"

#include <cstring>
#include <algorithm>

namespace ForensicAnalyzer {
namespace Database {

InnoDBParser::InnoDBParser() = default;

InnoDBParser::~InnoDBParser() {
    close();
}

bool InnoDBParser::open(const std::string& path) {
    close();
    
    path_ = path;
    file_.open(path, std::ios::binary);
    
    if (!file_.is_open()) {
        setError("Failed to open tablespace file: " + path);
        return false;
    }
    
    // 获取文件大小
    file_.seekg(0, std::ios::end);
    size_t fileSize = file_.tellg();
    file_.seekg(0);
    
    // 检测页大小
    if (!detectPageSize()) {
        close();
        return false;
    }
    
    totalPages_ = fileSize / pageSize_;
    
    // 读取space ID
    auto firstPage = getPageData(0);
    if (firstPage.size() >= 38) {
        spaceId_ = readUint32BE(&firstPage[InnoDB::FIL_PAGE_SPACE_ID]);
    }
    
    return true;
}

void InnoDBParser::close() {
    if (file_.is_open()) {
        file_.close();
    }
    columns_.clear();
    totalPages_ = 0;
}

bool InnoDBParser::detectPageSize() {
    // 尝试常见页大小
    std::vector<size_t> pageSizes = {16384, 8192, 4096, 32768, 65536};
    
    for (size_t size : pageSizes) {
        file_.seekg(0);
        std::vector<uint8_t> header(38);
        file_.read(reinterpret_cast<char*>(header.data()), 38);
        
        if (file_.gcount() < 38) continue;
        
        // 检查页类型是否有效
        uint16_t pageType = readUint16BE(&header[InnoDB::FIL_PAGE_TYPE]);
        
        // FSP_HDR页应该在第一页
        if (pageType == InnoDB::FIL_PAGE_TYPE_FSP_HDR) {
            pageSize_ = size;
            return true;
        }
    }
    
    // 默认使用16KB
    pageSize_ = InnoDB::DEFAULT_PAGE_SIZE;
    return true;
}

std::vector<uint8_t> InnoDBParser::getPageData(uint32_t pageNo) {
    std::vector<uint8_t> data(pageSize_);
    
    if (!file_.is_open() || pageNo >= totalPages_) {
        return {};
    }
    
    file_.seekg(pageNo * pageSize_);
    file_.read(reinterpret_cast<char*>(data.data()), pageSize_);
    
    if (file_.gcount() != static_cast<std::streamsize>(pageSize_)) {
        return {};
    }
    
    return data;
}

InnoDBPage InnoDBParser::readPage(uint32_t pageNo) {
    InnoDBPage page;
    page.pageNumber = pageNo;
    
    auto data = getPageData(pageNo);
    if (data.empty()) {
        return page;
    }
    
    parseFilePage(data, page);
    parsePageHeader(data, page);
    
    return page;
}

bool InnoDBParser::parseFilePage(const std::vector<uint8_t>& data, InnoDBPage& page) {
    if (data.size() < 38) return false;
    
    page.spaceId = readUint32BE(&data[InnoDB::FIL_PAGE_SPACE_ID]);
    page.prevPage = readUint32BE(&data[InnoDB::FIL_PAGE_PREV]);
    page.nextPage = readUint32BE(&data[InnoDB::FIL_PAGE_NEXT]);
    page.lsn = readUint64BE(&data[InnoDB::FIL_PAGE_LSN]);
    page.pageType = static_cast<InnoDBPageType>(readUint16BE(&data[InnoDB::FIL_PAGE_TYPE]));
    
    return true;
}

bool InnoDBParser::parsePageHeader(const std::vector<uint8_t>& data, InnoDBPage& page) {
    if (data.size() < InnoDB::FIL_PAGE_DATA + InnoDB::PAGE_HEADER_SIZE) return false;
    
    size_t offset = InnoDB::FIL_PAGE_DATA;
    
    uint16_t nDirSlots = readUint16BE(&data[offset + InnoDB::PAGE_N_DIR_SLOTS]);
    page.heapTop = readUint16BE(&data[offset + InnoDB::PAGE_HEAP_TOP]);
    page.nHeap = readUint16BE(&data[offset + InnoDB::PAGE_N_HEAP]);
    page.freeOffset = readUint16BE(&data[offset + InnoDB::PAGE_FREE]);
    page.garbage = readUint16BE(&data[offset + InnoDB::PAGE_GARBAGE]);
    page.nRecords = readUint16BE(&data[offset + InnoDB::PAGE_N_RECS]);
    
    uint16_t pageLevel = readUint16BE(&data[offset + InnoDB::PAGE_LEVEL]);
    page.isLeaf = (pageLevel == 0);
    
    // 检测是否为Compact格式
    page.isCompact = (page.nHeap & 0x8000) != 0;
    page.nHeap &= 0x7FFF;  // 清除格式位
    
    return true;
}

std::vector<InnoDBPage> InnoDBParser::scanIndexPages() {
    std::vector<InnoDBPage> pages;
    
    for (uint32_t i = 0; i < totalPages_; i++) {
        InnoDBPage page = readPage(i);
        if (page.pageType == InnoDBPageType::FIL_PAGE_INDEX) {
            pages.push_back(page);
        }
    }
    
    return pages;
}

void InnoDBParser::setTableSchema(const std::vector<InnoDBColumnDef>& columns) {
    columns_ = columns;
}

std::vector<DBRecordInfo> InnoDBParser::extractRecords(uint32_t pageNo) {
    std::vector<DBRecordInfo> records;
    
    auto pageData = getPageData(pageNo);
    if (pageData.empty()) return records;
    
    InnoDBPage page = readPage(pageNo);
    if (page.pageType != InnoDBPageType::FIL_PAGE_INDEX || !page.isLeaf) {
        return records;
    }
    
    return parseUserRecords(pageData, page);
}

std::vector<DBRecordInfo> InnoDBParser::extractAllRecords() {
    std::vector<DBRecordInfo> allRecords;
    
    auto indexPages = scanIndexPages();
    for (const auto& page : indexPages) {
        if (page.isLeaf) {
            auto records = extractRecords(page.pageNumber);
            allRecords.insert(allRecords.end(), records.begin(), records.end());
        }
    }
    
    return allRecords;
}

std::vector<DBRecordInfo> InnoDBParser::parseUserRecords(const std::vector<uint8_t>& pageData,
                                                          const InnoDBPage& page) {
    std::vector<DBRecordInfo> records;
    
    if (!page.isCompact) {
        // Redundant格式暂不支持
        return records;
    }
    
    // 从infimum开始遍历记录链
    size_t infimumOffset = InnoDB::FIL_PAGE_DATA + InnoDB::PAGE_HEADER_SIZE + 5; // 5 for infimum extra bytes
    size_t currentOffset = InnoDB::PAGE_NEW_INFIMUM;
    
    // 读取infimum的next record offset
    int16_t nextOffset = static_cast<int16_t>(readUint16BE(&pageData[currentOffset - 2]));
    currentOffset = currentOffset + nextOffset;
    
    int recordCount = 0;
    const int maxRecords = 10000;  // 安全限制
    
    while (recordCount < maxRecords && currentOffset < pageData.size() - 10) {
        // 检查是否到达supremum
        if (currentOffset == InnoDB::PAGE_NEW_SUPREMUM) {
            break;
        }
        
        // 解析记录头
        uint8_t info = pageData[currentOffset - 5];
        bool isDeleted = (info & 0x20) != 0;
        uint8_t recordType = (info >> 4) & 0x03;
        
        // 跳过非用户记录
        if (recordType == 2 || recordType == 3) {  // infimum/supremum
            break;
        }
        
        DBRecordInfo record = parseRecord(pageData, currentOffset, isDeleted);
        record.pageNumber = page.pageNumber;
        record.cellOffset = currentOffset;
        records.push_back(record);
        
        // 读取下一记录偏移
        nextOffset = static_cast<int16_t>(readUint16BE(&pageData[currentOffset - 2]));
        if (nextOffset == 0) break;
        
        currentOffset = currentOffset + nextOffset;
        recordCount++;
    }
    
    return records;
}

DBRecordInfo InnoDBParser::parseRecord(const std::vector<uint8_t>& pageData,
                                        size_t offset, bool isDeleted) {
    DBRecordInfo record;
    record.isDeleted = isDeleted;
    record.cellOffset = offset;
    
    // 如果没有schema，只能返回原始偏移信息
    if (columns_.empty()) {
        // 尝试读取一些原始字节作为数据
        size_t dataLen = std::min(size_t(100), pageData.size() - offset);
        std::string hexData;
        for (size_t i = 0; i < dataLen; i++) {
            char buf[4];
            snprintf(buf, sizeof(buf), "%02x", pageData[offset + i]);
            hexData += buf;
        }
        record.values["_raw_hex"] = hexData;
        return record;
    }
    
    // 有schema时解析各列
    size_t dataOffset = offset;
    
    for (size_t i = 0; i < columns_.size(); i++) {
        const auto& col = columns_[i];
        std::string value;
        
        if (dataOffset >= pageData.size()) break;
        
        // 简化解析：读取固定或变长数据
        if (col.isVariable) {
            // 变长字段需要先读取长度
            uint8_t lenByte = pageData[dataOffset];
            size_t len = 0;
            
            if (lenByte < 128) {
                len = lenByte;
                dataOffset++;
            } else {
                // 2字节长度
                len = ((lenByte & 0x3f) << 8) | pageData[dataOffset + 1];
                dataOffset += 2;
            }
            
            if (dataOffset + len <= pageData.size()) {
                value = std::string(reinterpret_cast<const char*>(&pageData[dataOffset]), len);
                dataOffset += len;
            }
        } else {
            // 固定长度
            if (dataOffset + col.len <= pageData.size()) {
                if (col.len <= 8) {
                    // 数值类型
                    uint64_t numVal = 0;
                    for (uint32_t j = 0; j < col.len; j++) {
                        numVal = (numVal << 8) | pageData[dataOffset + j];
                    }
                    value = std::to_string(numVal);
                } else {
                    value = std::string(reinterpret_cast<const char*>(&pageData[dataOffset]), col.len);
                }
                dataOffset += col.len;
            }
        }
        
        record.values[col.name] = value;
    }
    
    return record;
}

std::vector<DBRecordInfo> InnoDBParser::recoverDeletedRecords() {
    std::vector<DBRecordInfo> deletedRecords;
    
    auto indexPages = scanIndexPages();
    for (const auto& page : indexPages) {
        if (page.isLeaf && page.garbage > 0) {
            auto pageData = getPageData(page.pageNumber);
            if (pageData.empty()) continue;
            
            // 扫描free list
            auto freeRecords = scanFreeList(pageData, page);
            deletedRecords.insert(deletedRecords.end(), freeRecords.begin(), freeRecords.end());
            
            // 扫描garbage区域
            auto garbageRecords = scanGarbage(pageData, page);
            deletedRecords.insert(deletedRecords.end(), garbageRecords.begin(), garbageRecords.end());
        }
    }
    
    return deletedRecords;
}

std::vector<DBRecordInfo> InnoDBParser::scanDeletedInPage(uint32_t pageNo) {
    std::vector<DBRecordInfo> records;
    
    auto pageData = getPageData(pageNo);
    if (pageData.empty()) return records;
    
    InnoDBPage page = readPage(pageNo);
    if (page.pageType != InnoDBPageType::FIL_PAGE_INDEX) {
        return records;
    }
    
    if (page.garbage > 0) {
        auto freeRecords = scanFreeList(pageData, page);
        records.insert(records.end(), freeRecords.begin(), freeRecords.end());
        
        auto garbageRecords = scanGarbage(pageData, page);
        records.insert(records.end(), garbageRecords.begin(), garbageRecords.end());
    }
    
    return records;
}

std::vector<DBRecordInfo> InnoDBParser::scanFreeList(const std::vector<uint8_t>& pageData,
                                                      const InnoDBPage& page) {
    std::vector<DBRecordInfo> records;
    
    if (page.freeOffset == 0) return records;
    
    size_t currentOffset = page.freeOffset;
    int count = 0;
    const int maxRecords = 1000;
    
    while (count < maxRecords && currentOffset > 0 && currentOffset < pageData.size() - 10) {
        DBRecordInfo record = parseRecord(pageData, currentOffset, true);
        record.pageNumber = page.pageNumber;
        record.isDeleted = true;
        records.push_back(record);
        
        // 读取下一个free record
        int16_t nextOffset = static_cast<int16_t>(readUint16BE(&pageData[currentOffset - 2]));
        if (nextOffset == 0) break;
        
        currentOffset = currentOffset + nextOffset;
        count++;
    }
    
    return records;
}

std::vector<DBRecordInfo> InnoDBParser::scanGarbage(const std::vector<uint8_t>& pageData,
                                                     const InnoDBPage& page) {
    std::vector<DBRecordInfo> records;
    
    // 扫描heap区域中标记为deleted的记录
    size_t heapStart = InnoDB::FIL_PAGE_DATA + InnoDB::PAGE_HEADER_SIZE + 16; // After infimum/supremum
    size_t heapEnd = page.heapTop;
    
    // 简化扫描：查找可能的记录头模式
    for (size_t offset = heapStart + 5; offset < heapEnd && offset < pageData.size() - 10; offset++) {
        // 检查是否有deleted标记
        uint8_t info = pageData[offset - 5];
        bool isDeleted = (info & 0x20) != 0;
        uint8_t recordType = (info >> 4) & 0x03;
        
        if (isDeleted && recordType == 0) {  // 普通记录且已删除
            // 验证这是一个有效的记录位置
            uint16_t nextOffset = readUint16BE(&pageData[offset - 2]);
            
            // 简单验证
            if (nextOffset < pageSize_ && nextOffset != 0) {
                DBRecordInfo record = parseRecord(pageData, offset, true);
                record.pageNumber = page.pageNumber;
                records.push_back(record);
            }
        }
    }
    
    return records;
}

std::vector<DBArtifact> InnoDBParser::toArtifacts() {
    std::vector<DBArtifact> artifacts;
    
    // 添加删除记录作为工件
    auto deletedRecords = recoverDeletedRecords();
    for (const auto& record : deletedRecords) {
        DBArtifact artifact;
        artifact.type = ArtifactType::INNODB_DELETED;
        artifact.source = path_;
        artifact.pageNumber = record.pageNumber;
        artifact.offset = record.cellOffset;
        artifact.description = "Deleted InnoDB record";
        artifact.data = record.values;
        artifacts.push_back(artifact);
    }
    
    // 页统计作为工件
    auto stats = getPageTypeStats();
    DBArtifact statsArtifact;
    statsArtifact.type = ArtifactType::INNODB_PAGE;
    statsArtifact.source = path_;
    statsArtifact.description = "InnoDB tablespace statistics";
    for (const auto& [type, count] : stats) {
        statsArtifact.data[innoDBPageTypeToString(type)] = std::to_string(count);
    }
    statsArtifact.data["total_pages"] = std::to_string(totalPages_);
    statsArtifact.data["page_size"] = std::to_string(pageSize_);
    artifacts.push_back(statsArtifact);
    
    return artifacts;
}

std::map<InnoDBPageType, uint32_t> InnoDBParser::getPageTypeStats() {
    std::map<InnoDBPageType, uint32_t> stats;
    
    for (uint32_t i = 0; i < totalPages_; i++) {
        InnoDBPage page = readPage(i);
        stats[page.pageType]++;
    }
    
    return stats;
}

// ========== 辅助方法 ==========

uint32_t InnoDBParser::readUint32BE(const uint8_t* data) {
    return (uint32_t(data[0]) << 24) | (uint32_t(data[1]) << 16) |
           (uint32_t(data[2]) << 8) | uint32_t(data[3]);
}

uint16_t InnoDBParser::readUint16BE(const uint8_t* data) {
    return (uint16_t(data[0]) << 8) | uint16_t(data[1]);
}

uint64_t InnoDBParser::readUint64BE(const uint8_t* data) {
    return (uint64_t(data[0]) << 56) | (uint64_t(data[1]) << 48) |
           (uint64_t(data[2]) << 40) | (uint64_t(data[3]) << 32) |
           (uint64_t(data[4]) << 24) | (uint64_t(data[5]) << 16) |
           (uint64_t(data[6]) << 8) | uint64_t(data[7]);
}

void InnoDBParser::setError(const std::string& error) {
    lastError_ = error;
}

} // namespace Database
} // namespace ForensicAnalyzer
