/**
 * @file MySQLBinlogParser.cpp
 * @brief MySQL 二进制日志解析器实现
 */

#include "MySQLBinlogParser.h"

#include <cstring>
#include <algorithm>

namespace ForensicAnalyzer {
namespace Database {

// Binlog magic number
static const uint8_t BINLOG_MAGIC[] = {0xfe, 0x62, 0x69, 0x6e};

// 事件头大小（MySQL 5.x+）
static const size_t EVENT_HEADER_SIZE = 19;

MySQLBinlogParser::MySQLBinlogParser() = default;

MySQLBinlogParser::~MySQLBinlogParser() {
    close();
}

bool MySQLBinlogParser::open(const std::string& path) {
    close();
    
    path_ = path;
    file_.open(path, std::ios::binary);
    
    if (!file_.is_open()) {
        setError("Failed to open binlog file: " + path);
        return false;
    }
    
    if (!parseHeader()) {
        close();
        return false;
    }
    
    return true;
}

void MySQLBinlogParser::close() {
    if (file_.is_open()) {
        file_.close();
    }
    tableMapCache_.clear();
    currentPos_ = 0;
}

bool MySQLBinlogParser::parseHeader() {
    // 读取magic number
    uint8_t magic[4];
    file_.read(reinterpret_cast<char*>(magic), 4);
    
    if (file_.gcount() != 4 || std::memcmp(magic, BINLOG_MAGIC, 4) != 0) {
        setError("Invalid binlog magic number");
        return false;
    }
    
    std::memcpy(header_.magic, magic, 4);
    currentPos_ = 4;
    
    // 第一个事件是Format Description Event (FDE)
    BinlogEvent fde = parseNextEvent();
    if (fde.eventType != BinlogEventType::FORMAT_DESCRIPTION_EVENT) {
        setError("First event is not Format Description Event");
        return false;
    }
    
    return true;
}

bool MySQLBinlogParser::parseEventHeader(BinlogEvent& event) {
    if (!file_.good() || file_.eof()) {
        return false;
    }
    
    event.timestamp = readUint32();
    event.eventType = static_cast<BinlogEventType>(readUint8());
    event.serverId = readUint32();
    event.eventLength = readUint32();
    event.nextPosition = readUint32();
    event.flags = readUint16();
    
    return file_.good();
}

BinlogEvent MySQLBinlogParser::parseNextEvent() {
    BinlogEvent event;
    
    if (!file_.good() || file_.eof()) {
        return event;
    }
    
    size_t startPos = file_.tellg();
    
    if (!parseEventHeader(event)) {
        return event;
    }
    
    // 计算body大小（总长度 - header大小）
    size_t bodySize = event.eventLength - EVENT_HEADER_SIZE;
    
    if (bodySize > 0) {
        std::vector<uint8_t> body = readBytes(bodySize);
        parseEventBody(event, body);
    }
    
    // 移动到下一个事件
    currentPos_ = event.nextPosition;
    if (event.nextPosition > 0 && event.nextPosition > file_.tellg()) {
        file_.seekg(event.nextPosition);
    }
    
    return event;
}

bool MySQLBinlogParser::parseEventBody(BinlogEvent& event, const std::vector<uint8_t>& body) {
    switch (event.eventType) {
        case BinlogEventType::FORMAT_DESCRIPTION_EVENT:
            return parseFormatDescriptionEvent(event, body);
        case BinlogEventType::QUERY_EVENT:
            return parseQueryEvent(event, body);
        case BinlogEventType::TABLE_MAP_EVENT:
            return parseTableMapEvent(event, body);
        case BinlogEventType::WRITE_ROWS_EVENT:
        case BinlogEventType::WRITE_ROWS_EVENT_V1:
        case BinlogEventType::UPDATE_ROWS_EVENT:
        case BinlogEventType::UPDATE_ROWS_EVENT_V1:
        case BinlogEventType::DELETE_ROWS_EVENT:
        case BinlogEventType::DELETE_ROWS_EVENT_V1:
            return parseRowsEvent(event, body);
        case BinlogEventType::ROTATE_EVENT:
            return parseRotateEvent(event, body);
        case BinlogEventType::XID_EVENT:
            return parseXidEvent(event, body);
        default:
            return true;  // 跳过未知事件
    }
}

bool MySQLBinlogParser::parseFormatDescriptionEvent(BinlogEvent& event, const std::vector<uint8_t>& body) {
    if (body.size() < 57) return false;
    
    size_t pos = 0;
    
    // Binlog版本 (2 bytes)
    header_.binlogVersion = body[pos] | (body[pos + 1] << 8);
    pos += 2;
    
    // Server版本 (50 bytes, null-terminated)
    header_.serverVersion = std::string(reinterpret_cast<const char*>(&body[pos]), 50);
    auto nullPos = header_.serverVersion.find('\0');
    if (nullPos != std::string::npos) {
        header_.serverVersion = header_.serverVersion.substr(0, nullPos);
    }
    pos += 50;
    
    // 创建时间 (4 bytes)
    header_.createTimestamp = body[pos] | (body[pos + 1] << 8) | 
                              (body[pos + 2] << 16) | (body[pos + 3] << 24);
    pos += 4;
    
    // 事件头长度 (1 byte)
    header_.headerLength = body[pos];
    
    return true;
}

bool MySQLBinlogParser::parseQueryEvent(BinlogEvent& event, const std::vector<uint8_t>& body) {
    if (body.size() < 13) return false;
    
    size_t pos = 0;
    
    // thread_id (4 bytes)
    pos += 4;
    
    // exec_time (4 bytes)
    pos += 4;
    
    // database name length (1 byte)
    uint8_t dbLen = body[pos++];
    
    // error code (2 bytes)
    pos += 2;
    
    // status_vars_length (2 bytes, MySQL 5.0+)
    uint16_t statusVarsLen = body[pos] | (body[pos + 1] << 8);
    pos += 2;
    
    // 跳过status_vars
    pos += statusVarsLen;
    
    // 数据库名 (null-terminated)
    if (pos + dbLen < body.size()) {
        event.database = std::string(reinterpret_cast<const char*>(&body[pos]), dbLen);
        pos += dbLen + 1;  // +1 for null terminator
    }
    
    // SQL语句
    if (pos < body.size()) {
        event.query = std::string(reinterpret_cast<const char*>(&body[pos]), body.size() - pos);
        // 移除尾部可能的null
        while (!event.query.empty() && event.query.back() == '\0') {
            event.query.pop_back();
        }
    }
    
    return true;
}

bool MySQLBinlogParser::parseTableMapEvent(BinlogEvent& event, const std::vector<uint8_t>& body) {
    if (body.size() < 8) return false;
    
    size_t pos = 0;
    
    // table_id (6 bytes)
    event.tableId = body[pos] | (uint64_t(body[pos + 1]) << 8) |
                    (uint64_t(body[pos + 2]) << 16) | (uint64_t(body[pos + 3]) << 24) |
                    (uint64_t(body[pos + 4]) << 32) | (uint64_t(body[pos + 5]) << 40);
    pos += 6;
    
    // flags (2 bytes)
    pos += 2;
    
    // database name length (1 byte)
    uint8_t dbLen = body[pos++];
    
    // database name
    if (pos + dbLen < body.size()) {
        event.database = std::string(reinterpret_cast<const char*>(&body[pos]), dbLen);
        pos += dbLen + 1;  // +1 for null
    }
    
    // table name length (1 byte)
    if (pos >= body.size()) return false;
    uint8_t tableLen = body[pos++];
    
    // table name
    if (pos + tableLen <= body.size()) {
        event.tableName = std::string(reinterpret_cast<const char*>(&body[pos]), tableLen);
        pos += tableLen + 1;  // +1 for null
    }
    
    // column count (packed integer)
    // 简化处理：假设列数 < 251
    if (pos >= body.size()) return false;
    uint64_t columnCount = body[pos++];
    
    // column types
    event.columnTypes.clear();
    for (uint64_t i = 0; i < columnCount && pos < body.size(); i++) {
        event.columnTypes.push_back(body[pos++]);
    }
    
    // 缓存表映射
    TableMapInfo mapInfo;
    mapInfo.tableId = event.tableId;
    mapInfo.database = event.database;
    mapInfo.table = event.tableName;
    mapInfo.columnTypes = event.columnTypes;
    tableMapCache_[event.tableId] = mapInfo;
    
    return true;
}

bool MySQLBinlogParser::parseRowsEvent(BinlogEvent& event, const std::vector<uint8_t>& body) {
    if (body.size() < 8) return false;
    
    size_t pos = 0;
    
    // table_id (6 bytes)
    uint64_t tableId = body[pos] | (uint64_t(body[pos + 1]) << 8) |
                       (uint64_t(body[pos + 2]) << 16) | (uint64_t(body[pos + 3]) << 24) |
                       (uint64_t(body[pos + 4]) << 32) | (uint64_t(body[pos + 5]) << 40);
    pos += 6;
    event.tableId = tableId;
    
    // 查找表映射
    auto it = tableMapCache_.find(tableId);
    if (it != tableMapCache_.end()) {
        event.database = it->second.database;
        event.tableName = it->second.table;
    }
    
    // flags (2 bytes)
    pos += 2;
    
    // extra_data_length (version 2)
    if (event.eventType == BinlogEventType::WRITE_ROWS_EVENT ||
        event.eventType == BinlogEventType::UPDATE_ROWS_EVENT ||
        event.eventType == BinlogEventType::DELETE_ROWS_EVENT) {
        if (pos + 2 <= body.size()) {
            uint16_t extraLen = body[pos] | (body[pos + 1] << 8);
            pos += 2;
            pos += (extraLen - 2);  // 跳过extra data
        }
    }
    
    // 列数 (packed integer)
    if (pos >= body.size()) return true;
    uint64_t columnCount = body[pos++];
    
    // columns bitmap (used columns)
    size_t bitmapLen = (columnCount + 7) / 8;
    pos += bitmapLen;
    
    // UPDATE事件有额外的after-image bitmap
    if (event.eventType == BinlogEventType::UPDATE_ROWS_EVENT ||
        event.eventType == BinlogEventType::UPDATE_ROWS_EVENT_V1) {
        pos += bitmapLen;
    }
    
    // 解析行数据（简化版本，仅标记有数据）
    // 完整解析需要列元数据信息
    while (pos < body.size()) {
        std::map<std::string, std::string> row;
        
        // NULL bitmap
        size_t nullBitmapLen = (columnCount + 7) / 8;
        if (pos + nullBitmapLen > body.size()) break;
        
        std::vector<uint8_t> nullBitmap(body.begin() + pos, body.begin() + pos + nullBitmapLen);
        pos += nullBitmapLen;
        
        // 简化：标记列位置
        for (uint64_t col = 0; col < columnCount; col++) {
            bool isNull = (nullBitmap[col / 8] >> (col % 8)) & 1;
            row["col_" + std::to_string(col)] = isNull ? "<NULL>" : "<value>";
        }
        
        // DELETE/UPDATE前
        if (event.eventType == BinlogEventType::DELETE_ROWS_EVENT ||
            event.eventType == BinlogEventType::DELETE_ROWS_EVENT_V1 ||
            event.eventType == BinlogEventType::UPDATE_ROWS_EVENT ||
            event.eventType == BinlogEventType::UPDATE_ROWS_EVENT_V1) {
            event.beforeRows.push_back(row);
        }
        
        // INSERT/UPDATE后
        if (event.eventType == BinlogEventType::WRITE_ROWS_EVENT ||
            event.eventType == BinlogEventType::WRITE_ROWS_EVENT_V1 ||
            event.eventType == BinlogEventType::UPDATE_ROWS_EVENT ||
            event.eventType == BinlogEventType::UPDATE_ROWS_EVENT_V1) {
            event.afterRows.push_back(row);
        }
        
        break;  // 简化版本只解析第一行
    }
    
    return true;
}

bool MySQLBinlogParser::parseRotateEvent(BinlogEvent& event, const std::vector<uint8_t>& body) {
    if (body.size() < 8) return false;
    
    // position (8 bytes)
    // next binlog name (rest of body)
    if (body.size() > 8) {
        event.query = std::string(reinterpret_cast<const char*>(&body[8]), body.size() - 8);
    }
    
    return true;
}

bool MySQLBinlogParser::parseXidEvent(BinlogEvent& event, const std::vector<uint8_t>& body) {
    if (body.size() < 8) return false;
    
    // XID (8 bytes) - 事务ID
    uint64_t xid = body[0] | (uint64_t(body[1]) << 8) | (uint64_t(body[2]) << 16) |
                   (uint64_t(body[3]) << 24) | (uint64_t(body[4]) << 32) |
                   (uint64_t(body[5]) << 40) | (uint64_t(body[6]) << 48) |
                   (uint64_t(body[7]) << 56);
    
    event.query = "COMMIT /* xid=" + std::to_string(xid) + " */";
    
    return true;
}

std::vector<BinlogEvent> MySQLBinlogParser::parseAllEvents() {
    std::vector<BinlogEvent> events;
    
    // 重置到开始位置
    file_.seekg(4);  // 跳过magic
    tableMapCache_.clear();
    
    while (file_.good() && !file_.eof()) {
        BinlogEvent event = parseNextEvent();
        if (event.eventType == BinlogEventType::UNKNOWN_EVENT) {
            break;
        }
        events.push_back(std::move(event));
    }
    
    return events;
}

std::vector<BinlogEvent> MySQLBinlogParser::extractRowChanges() {
    std::vector<BinlogEvent> changes;
    
    auto events = parseAllEvents();
    for (const auto& event : events) {
        switch (event.eventType) {
            case BinlogEventType::WRITE_ROWS_EVENT:
            case BinlogEventType::WRITE_ROWS_EVENT_V1:
            case BinlogEventType::UPDATE_ROWS_EVENT:
            case BinlogEventType::UPDATE_ROWS_EVENT_V1:
            case BinlogEventType::DELETE_ROWS_EVENT:
            case BinlogEventType::DELETE_ROWS_EVENT_V1:
                changes.push_back(event);
                break;
            default:
                break;
        }
    }
    
    return changes;
}

std::vector<BinlogEvent> MySQLBinlogParser::extractTableChanges(const std::string& database, 
                                                                 const std::string& table) {
    std::vector<BinlogEvent> changes;
    
    auto rowChanges = extractRowChanges();
    for (const auto& event : rowChanges) {
        if ((database.empty() || event.database == database) &&
            (table.empty() || event.tableName == table)) {
            changes.push_back(event);
        }
    }
    
    return changes;
}

std::vector<BinlogEvent> MySQLBinlogParser::filterByTime(uint32_t startTime, uint32_t endTime) {
    std::vector<BinlogEvent> filtered;
    
    auto events = parseAllEvents();
    for (const auto& event : events) {
        if (event.timestamp >= startTime && event.timestamp <= endTime) {
            filtered.push_back(event);
        }
    }
    
    return filtered;
}

std::vector<DBArtifact> MySQLBinlogParser::toArtifacts() {
    std::vector<DBArtifact> artifacts;
    
    auto events = parseAllEvents();
    for (const auto& event : events) {
        DBArtifact artifact;
        artifact.type = ArtifactType::BINLOG_EVENT;
        artifact.source = path_;
        artifact.timestamp = event.timestamp;
        
        std::string typeStr = binlogEventTypeToString(event.eventType);
        
        if (!event.database.empty()) {
            artifact.data["database"] = event.database;
        }
        if (!event.tableName.empty()) {
            artifact.data["table"] = event.tableName;
        }
        if (!event.query.empty()) {
            artifact.data["query"] = event.query;
        }
        
        artifact.description = typeStr + " event";
        if (!event.tableName.empty()) {
            artifact.description += " on " + event.database + "." + event.tableName;
        }
        
        artifact.data["event_type"] = typeStr;
        artifact.data["server_id"] = std::to_string(event.serverId);
        
        artifacts.push_back(std::move(artifact));
    }
    
    return artifacts;
}

// ========== 辅助读取方法 ==========

std::vector<uint8_t> MySQLBinlogParser::readBytes(size_t count) {
    std::vector<uint8_t> data(count);
    file_.read(reinterpret_cast<char*>(data.data()), count);
    size_t actualRead = file_.gcount();
    if (actualRead < count) {
        data.resize(actualRead);
    }
    return data;
}

uint8_t MySQLBinlogParser::readUint8() {
    uint8_t val = 0;
    file_.read(reinterpret_cast<char*>(&val), 1);
    return val;
}

uint16_t MySQLBinlogParser::readUint16() {
    uint8_t buf[2];
    file_.read(reinterpret_cast<char*>(buf), 2);
    return buf[0] | (buf[1] << 8);
}

uint32_t MySQLBinlogParser::readUint24() {
    uint8_t buf[3];
    file_.read(reinterpret_cast<char*>(buf), 3);
    return buf[0] | (buf[1] << 8) | (buf[2] << 16);
}

uint32_t MySQLBinlogParser::readUint32() {
    uint8_t buf[4];
    file_.read(reinterpret_cast<char*>(buf), 4);
    return buf[0] | (buf[1] << 8) | (buf[2] << 16) | (buf[3] << 24);
}

uint64_t MySQLBinlogParser::readUint48() {
    uint8_t buf[6];
    file_.read(reinterpret_cast<char*>(buf), 6);
    return uint64_t(buf[0]) | (uint64_t(buf[1]) << 8) | (uint64_t(buf[2]) << 16) |
           (uint64_t(buf[3]) << 24) | (uint64_t(buf[4]) << 32) | (uint64_t(buf[5]) << 40);
}

uint64_t MySQLBinlogParser::readUint64() {
    uint8_t buf[8];
    file_.read(reinterpret_cast<char*>(buf), 8);
    return uint64_t(buf[0]) | (uint64_t(buf[1]) << 8) | (uint64_t(buf[2]) << 16) |
           (uint64_t(buf[3]) << 24) | (uint64_t(buf[4]) << 32) | (uint64_t(buf[5]) << 40) |
           (uint64_t(buf[6]) << 48) | (uint64_t(buf[7]) << 56);
}

std::string MySQLBinlogParser::readString(size_t length) {
    std::string str(length, '\0');
    file_.read(&str[0], length);
    return str;
}

std::string MySQLBinlogParser::readNullTerminatedString() {
    std::string str;
    char c;
    while (file_.get(c) && c != '\0') {
        str += c;
    }
    return str;
}

uint64_t MySQLBinlogParser::readPackedInteger() {
    uint8_t first = readUint8();
    if (first < 251) {
        return first;
    } else if (first == 251) {
        return 0;  // NULL
    } else if (first == 252) {
        return readUint16();
    } else if (first == 253) {
        return readUint24();
    } else {
        return readUint64();
    }
}

void MySQLBinlogParser::setError(const std::string& error) {
    lastError_ = error;
}

} // namespace Database
} // namespace ForensicAnalyzer
