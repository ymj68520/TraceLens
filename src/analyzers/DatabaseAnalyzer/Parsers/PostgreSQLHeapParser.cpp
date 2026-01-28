/**
 * @file PostgreSQLHeapParser.cpp
 * @brief PostgreSQL 堆文件解析器实现
 */

#include "PostgreSQLHeapParser.h"

#include <cstring>
#include <algorithm>

namespace ForensicAnalyzer {
namespace Database {

PostgreSQLHeapParser::PostgreSQLHeapParser() = default;

PostgreSQLHeapParser::~PostgreSQLHeapParser() {
    close();
}

bool PostgreSQLHeapParser::open(const std::string& path) {
    close();
    
    path_ = path;
    file_.open(path, std::ios::binary);
    
    if (!file_.is_open()) {
        setError("Failed to open heap file: " + path);
        return false;
    }
    
    // 获取文件大小
    file_.seekg(0, std::ios::end);
    size_t fileSize = file_.tellg();
    file_.seekg(0);
    
    if (fileSize == 0) {
        setError("Empty heap file");
        close();
        return false;
    }
    
    // 检测块大小
    if (!detectBlockSize()) {
        close();
        return false;
    }
    
    totalBlocks_ = fileSize / blockSize_;
    
    return true;
}

void PostgreSQLHeapParser::close() {
    if (file_.is_open()) {
        file_.close();
    }
    columns_.clear();
    totalBlocks_ = 0;
}

bool PostgreSQLHeapParser::detectBlockSize() {
    // 读取第一页的pagesize_version字段
    std::vector<uint8_t> header(24);
    file_.read(reinterpret_cast<char*>(header.data()), 24);
    
    if (file_.gcount() < 24) {
        setError("File too small to be a valid heap file");
        return false;
    }
    
    file_.seekg(0);
    
    // pd_pagesize_version: 低8位是版本，高8位是pagesize/256
    uint16_t pagesizeVersion = readUint16(&header[PG::PD_PAGESIZE_VERSION]);
    uint16_t pageSize = (pagesizeVersion & 0xFF00);
    
    if (pageSize == 0) {
        // 未初始化页或使用默认大小
        blockSize_ = PG::DEFAULT_BLOCK_SIZE;
    } else {
        blockSize_ = pageSize;
    }
    
    // 验证块大小是否合理
    if (blockSize_ < 1024 || blockSize_ > 65536 || (blockSize_ & (blockSize_ - 1)) != 0) {
        blockSize_ = PG::DEFAULT_BLOCK_SIZE;
    }
    
    return true;
}

std::vector<uint8_t> PostgreSQLHeapParser::getBlockData(uint32_t blockNo) {
    std::vector<uint8_t> data(blockSize_);
    
    if (!file_.is_open() || blockNo >= totalBlocks_) {
        return {};
    }
    
    file_.seekg(blockNo * blockSize_);
    file_.read(reinterpret_cast<char*>(data.data()), blockSize_);
    
    if (file_.gcount() != static_cast<std::streamsize>(blockSize_)) {
        return {};
    }
    
    return data;
}

std::vector<std::pair<uint16_t, uint16_t>> PostgreSQLHeapParser::getItemIds(uint32_t blockNo) {
    std::vector<std::pair<uint16_t, uint16_t>> items;
    
    auto blockData = getBlockData(blockNo);
    if (blockData.empty()) return items;
    
    uint16_t lower = readUint16(&blockData[PG::PD_LOWER]);
    
    // ItemId数组从页头后开始
    size_t itemIdStart = PG::PAGE_HEADER_SIZE;
    size_t numItems = (lower - PG::PAGE_HEADER_SIZE) / PG::ITEM_ID_SIZE;
    
    for (size_t i = 0; i < numItems; i++) {
        size_t offset = itemIdStart + i * PG::ITEM_ID_SIZE;
        uint32_t itemId = readUint32(&blockData[offset]);
        
        // ItemIdData: lp_off (15 bits), lp_flags (2 bits), lp_len (15 bits)
        uint16_t lpOff = itemId & 0x7FFF;
        uint16_t lpFlags = (itemId >> 15) & 0x03;
        uint16_t lpLen = (itemId >> 17) & 0x7FFF;
        
        items.push_back({lpOff, lpLen});
    }
    
    return items;
}

void PostgreSQLHeapParser::setTableSchema(const std::vector<PGColumnDef>& columns) {
    columns_ = columns;
}

std::vector<PGHeapTuple> PostgreSQLHeapParser::extractTuples(uint32_t blockNo) {
    std::vector<PGHeapTuple> tuples;
    
    auto blockData = getBlockData(blockNo);
    if (blockData.empty()) return tuples;
    
    uint16_t lower = readUint16(&blockData[PG::PD_LOWER]);
    
    size_t itemIdStart = PG::PAGE_HEADER_SIZE;
    size_t numItems = (lower - PG::PAGE_HEADER_SIZE) / PG::ITEM_ID_SIZE;
    
    for (size_t i = 0; i < numItems; i++) {
        size_t offset = itemIdStart + i * PG::ITEM_ID_SIZE;
        uint32_t itemId = readUint32(&blockData[offset]);
        
        uint16_t lpOff = itemId & 0x7FFF;
        uint16_t lpFlags = (itemId >> 15) & 0x03;
        uint16_t lpLen = (itemId >> 17) & 0x7FFF;
        
        // 只处理正常行
        if (lpFlags == PG::LP_NORMAL && lpLen > 0 && lpOff > 0) {
            auto tuple = parseTuple(blockData, lpOff, lpLen, blockNo, i + 1);
            tuples.push_back(tuple);
        }
    }
    
    return tuples;
}

std::vector<PGHeapTuple> PostgreSQLHeapParser::extractAllTuples() {
    std::vector<PGHeapTuple> allTuples;
    
    for (uint32_t i = 0; i < totalBlocks_; i++) {
        auto tuples = extractTuples(i);
        allTuples.insert(allTuples.end(), tuples.begin(), tuples.end());
    }
    
    return allTuples;
}

PGHeapTuple PostgreSQLHeapParser::parseTuple(const std::vector<uint8_t>& blockData,
                                              uint16_t offset, uint16_t length,
                                              uint32_t blockNo, uint16_t offsetNumber) {
    PGHeapTuple tuple;
    tuple.blockNumber = blockNo;
    tuple.offsetNumber = offsetNumber;
    tuple.tupleLength = length;
    
    if (offset + 23 > blockData.size()) {
        return tuple;
    }
    
    // 解析HeapTupleHeader
    tuple.visibility.xmin = readUint32(&blockData[offset + PG::T_XMIN]);
    tuple.visibility.xmax = readUint32(&blockData[offset + PG::T_XMAX]);
    
    uint16_t infomask = readUint16(&blockData[offset + PG::T_INFOMASK]);
    tuple.visibility.hasNulls = (infomask & PG::HEAP_HASNULL) != 0;
    tuple.visibility.hasVarwidth = (infomask & PG::HEAP_HASVARWIDTH) != 0;
    tuple.visibility.hasExternal = (infomask & PG::HEAP_HASEXTERNAL) != 0;
    
    // 判断是否为死元组
    bool xmaxCommitted = (infomask & PG::HEAP_XMAX_COMMITTED) != 0;
    bool xmaxInvalid = (infomask & PG::HEAP_XMAX_INVALID) != 0;
    tuple.isDead = xmaxCommitted && !xmaxInvalid && tuple.visibility.xmax != 0;
    
    // 数据偏移
    uint8_t hoff = blockData[offset + PG::T_HOFF];
    tuple.dataOffset = hoff;
    
    // 如果没有schema，读取原始数据
    if (columns_.empty()) {
        size_t dataStart = offset + hoff;
        size_t dataLen = std::min(size_t(length - hoff), blockData.size() - dataStart);
        dataLen = std::min(dataLen, size_t(100));  // 限制
        
        std::string hexData;
        for (size_t i = 0; i < dataLen; i++) {
            char buf[4];
            snprintf(buf, sizeof(buf), "%02x", blockData[dataStart + i]);
            hexData += buf;
        }
        tuple.values["_raw_hex"] = hexData;
    } else {
        // 解析各列
        size_t dataPos = offset + hoff;
        
        for (const auto& col : columns_) {
            std::string value;
            
            if (dataPos >= blockData.size()) break;
            
            if (col.typlen == -1) {
                // 变长类型 (varlena)
                uint8_t firstByte = blockData[dataPos];
                size_t len = 0;
                size_t headerLen = 0;
                
                if ((firstByte & 0x01) == 0) {
                    // 4字节头
                    uint32_t header = readUint32(&blockData[dataPos]);
                    len = (header >> 2) - 4;
                    headerLen = 4;
                } else if ((firstByte & 0x02) == 0) {
                    // 1字节头
                    len = (firstByte >> 1) - 1;
                    headerLen = 1;
                }
                
                dataPos += headerLen;
                if (dataPos + len <= blockData.size()) {
                    value = std::string(reinterpret_cast<const char*>(&blockData[dataPos]), len);
                    dataPos += len;
                }
            } else if (col.typlen > 0) {
                // 固定长度
                if (dataPos + col.typlen <= blockData.size()) {
                    if (col.typlen <= 8) {
                        uint64_t numVal = 0;
                        for (int16_t j = 0; j < col.typlen; j++) {
                            numVal |= uint64_t(blockData[dataPos + j]) << (j * 8);
                        }
                        value = std::to_string(numVal);
                    } else {
                        value = std::string(reinterpret_cast<const char*>(&blockData[dataPos]), col.typlen);
                    }
                    dataPos += col.typlen;
                }
            }
            
            tuple.values[col.name] = value;
        }
    }
    
    return tuple;
}

std::vector<PGHeapTuple> PostgreSQLHeapParser::findDeadTuples() {
    std::vector<PGHeapTuple> deadTuples;
    
    for (uint32_t i = 0; i < totalBlocks_; i++) {
        auto tuples = findDeadTuplesInBlock(i);
        deadTuples.insert(deadTuples.end(), tuples.begin(), tuples.end());
    }
    
    return deadTuples;
}

std::vector<PGHeapTuple> PostgreSQLHeapParser::findDeadTuplesInBlock(uint32_t blockNo) {
    std::vector<PGHeapTuple> deadTuples;
    
    auto blockData = getBlockData(blockNo);
    if (blockData.empty()) return deadTuples;
    
    uint16_t lower = readUint16(&blockData[PG::PD_LOWER]);
    
    size_t itemIdStart = PG::PAGE_HEADER_SIZE;
    size_t numItems = (lower - PG::PAGE_HEADER_SIZE) / PG::ITEM_ID_SIZE;
    
    for (size_t i = 0; i < numItems; i++) {
        size_t offset = itemIdStart + i * PG::ITEM_ID_SIZE;
        uint32_t itemId = readUint32(&blockData[offset]);
        
        uint16_t lpOff = itemId & 0x7FFF;
        uint16_t lpFlags = (itemId >> 15) & 0x03;
        uint16_t lpLen = (itemId >> 17) & 0x7FFF;
        
        // 查找LP_DEAD或已删除的普通行
        if (lpFlags == PG::LP_DEAD || 
            (lpFlags == PG::LP_NORMAL && lpLen > 0 && lpOff > 0)) {
            auto tuple = parseTuple(blockData, lpOff, lpLen, blockNo, i + 1);
            
            // 只收集死元组
            if (tuple.isDead || lpFlags == PG::LP_DEAD) {
                tuple.isDead = true;
                deadTuples.push_back(tuple);
            }
        }
    }
    
    return deadTuples;
}

std::vector<DBArtifact> PostgreSQLHeapParser::toArtifacts() {
    std::vector<DBArtifact> artifacts;
    
    // 添加死元组作为工件
    auto deadTuples = findDeadTuples();
    for (const auto& tuple : deadTuples) {
        DBArtifact artifact;
        artifact.type = ArtifactType::PG_DEAD_TUPLE;
        artifact.source = path_;
        artifact.pageNumber = tuple.blockNumber;
        artifact.offset = tuple.offsetNumber;
        artifact.description = "Dead PostgreSQL tuple (pre-VACUUM)";
        artifact.data = tuple.values;
        artifact.data["xmin"] = std::to_string(tuple.visibility.xmin);
        artifact.data["xmax"] = std::to_string(tuple.visibility.xmax);
        artifacts.push_back(artifact);
    }
    
    // 统计信息作为工件
    auto stats = getStats();
    DBArtifact statsArtifact;
    statsArtifact.type = ArtifactType::PG_HEAP_TUPLE;
    statsArtifact.source = path_;
    statsArtifact.description = "PostgreSQL heap file statistics";
    for (const auto& [key, value] : stats) {
        statsArtifact.data[key] = std::to_string(value);
    }
    artifacts.push_back(statsArtifact);
    
    return artifacts;
}

std::map<std::string, uint32_t> PostgreSQLHeapParser::getStats() {
    std::map<std::string, uint32_t> stats;
    
    uint32_t totalTuples = 0;
    uint32_t deadTuples = 0;
    uint32_t emptyBlocks = 0;
    
    for (uint32_t i = 0; i < totalBlocks_; i++) {
        auto tuples = extractTuples(i);
        if (tuples.empty()) {
            emptyBlocks++;
        } else {
            for (const auto& tuple : tuples) {
                totalTuples++;
                if (tuple.isDead) deadTuples++;
            }
        }
    }
    
    stats["total_blocks"] = totalBlocks_;
    stats["block_size"] = blockSize_;
    stats["total_tuples"] = totalTuples;
    stats["dead_tuples"] = deadTuples;
    stats["empty_blocks"] = emptyBlocks;
    
    return stats;
}

// ========== 辅助方法 ==========

uint32_t PostgreSQLHeapParser::readUint32(const uint8_t* data) {
    // PostgreSQL使用小端序
    return uint32_t(data[0]) | (uint32_t(data[1]) << 8) |
           (uint32_t(data[2]) << 16) | (uint32_t(data[3]) << 24);
}

uint16_t PostgreSQLHeapParser::readUint16(const uint8_t* data) {
    return uint16_t(data[0]) | (uint16_t(data[1]) << 8);
}

uint64_t PostgreSQLHeapParser::readUint64(const uint8_t* data) {
    return uint64_t(data[0]) | (uint64_t(data[1]) << 8) |
           (uint64_t(data[2]) << 16) | (uint64_t(data[3]) << 24) |
           (uint64_t(data[4]) << 32) | (uint64_t(data[5]) << 40) |
           (uint64_t(data[6]) << 48) | (uint64_t(data[7]) << 56);
}

void PostgreSQLHeapParser::setError(const std::string& error) {
    lastError_ = error;
}

} // namespace Database
} // namespace ForensicAnalyzer
