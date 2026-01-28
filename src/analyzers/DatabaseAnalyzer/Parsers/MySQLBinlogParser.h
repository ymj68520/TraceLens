/**
 * @file MySQLBinlogParser.h
 * @brief MySQL 二进制日志解析器
 * 
 * 用于取证分析 MySQL binlog 文件，提取数据库操作历史
 */

#pragma once

#include "Common/DBDataTypes.h"
#include <string>
#include <vector>
#include <fstream>
#include <memory>
#include <map>

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief 表映射信息（用于Row事件解析）
 */
struct TableMapInfo {
    uint64_t tableId = 0;
    std::string database;
    std::string table;
    std::vector<uint8_t> columnTypes;
    std::vector<uint16_t> columnMeta;
    std::vector<bool> nullBitmap;
};

/**
 * @brief MySQL Binlog解析器
 * 
 * 支持解析MySQL 5.x/8.x的binlog文件，提取：
 * - SQL查询语句
 * - 行级变更（INSERT/UPDATE/DELETE）
 * - 事务边界
 */
class MySQLBinlogParser {
public:
    MySQLBinlogParser();
    ~MySQLBinlogParser();
    
    // 禁止拷贝
    MySQLBinlogParser(const MySQLBinlogParser&) = delete;
    MySQLBinlogParser& operator=(const MySQLBinlogParser&) = delete;
    
    /**
     * @brief 打开binlog文件
     * @param path binlog文件路径
     * @return 成功返回true
     */
    bool open(const std::string& path);
    
    /**
     * @brief 关闭文件
     */
    void close();
    
    /**
     * @brief 是否已打开
     */
    bool isOpen() const { return file_.is_open(); }
    
    /**
     * @brief 获取文件路径
     */
    std::string getPath() const { return path_; }
    
    /**
     * @brief 获取binlog头信息
     */
    BinlogHeader getHeader() const { return header_; }
    
    /**
     * @brief 解析所有事件
     * @return 事件列表
     */
    std::vector<BinlogEvent> parseAllEvents();
    
    /**
     * @brief 解析下一个事件
     * @return 事件（如果到达文件末尾或出错，返回UNKNOWN_EVENT类型）
     */
    BinlogEvent parseNextEvent();
    
    /**
     * @brief 提取行级变更
     * @return 包含INSERT/UPDATE/DELETE的事件
     */
    std::vector<BinlogEvent> extractRowChanges();
    
    /**
     * @brief 提取指定表的变更
     * @param database 数据库名
     * @param table 表名
     * @return 该表的变更事件
     */
    std::vector<BinlogEvent> extractTableChanges(const std::string& database, 
                                                  const std::string& table);
    
    /**
     * @brief 按时间范围过滤事件
     * @param startTime 开始时间戳
     * @param endTime 结束时间戳
     * @return 时间范围内的事件
     */
    std::vector<BinlogEvent> filterByTime(uint32_t startTime, uint32_t endTime);
    
    /**
     * @brief 转换为取证工件
     */
    std::vector<DBArtifact> toArtifacts();
    
    /**
     * @brief 获取最后错误
     */
    std::string getLastError() const { return lastError_; }

private:
    std::string path_;
    std::ifstream file_;
    BinlogHeader header_;
    std::string lastError_;
    uint64_t currentPos_ = 0;
    
    // 表映射缓存 (tableId -> TableMapInfo)
    std::map<uint64_t, TableMapInfo> tableMapCache_;
    
    // 解析方法
    bool parseHeader();
    bool parseEventHeader(BinlogEvent& event);
    bool parseEventBody(BinlogEvent& event, const std::vector<uint8_t>& body);
    
    // 特定事件解析
    bool parseFormatDescriptionEvent(BinlogEvent& event, const std::vector<uint8_t>& body);
    bool parseQueryEvent(BinlogEvent& event, const std::vector<uint8_t>& body);
    bool parseTableMapEvent(BinlogEvent& event, const std::vector<uint8_t>& body);
    bool parseRowsEvent(BinlogEvent& event, const std::vector<uint8_t>& body);
    bool parseRotateEvent(BinlogEvent& event, const std::vector<uint8_t>& body);
    bool parseXidEvent(BinlogEvent& event, const std::vector<uint8_t>& body);
    
    // 辅助方法
    std::vector<uint8_t> readBytes(size_t count);
    uint8_t readUint8();
    uint16_t readUint16();
    uint32_t readUint24();
    uint32_t readUint32();
    uint64_t readUint48();
    uint64_t readUint64();
    std::string readString(size_t length);
    std::string readNullTerminatedString();
    uint64_t readPackedInteger();
    
    void setError(const std::string& error);
};

/**
 * @brief 将BinlogEventType转换为字符串
 */
inline std::string binlogEventTypeToString(BinlogEventType type) {
    switch (type) {
        case BinlogEventType::QUERY_EVENT: return "QUERY";
        case BinlogEventType::TABLE_MAP_EVENT: return "TABLE_MAP";
        case BinlogEventType::WRITE_ROWS_EVENT:
        case BinlogEventType::WRITE_ROWS_EVENT_V1: return "INSERT";
        case BinlogEventType::UPDATE_ROWS_EVENT:
        case BinlogEventType::UPDATE_ROWS_EVENT_V1: return "UPDATE";
        case BinlogEventType::DELETE_ROWS_EVENT:
        case BinlogEventType::DELETE_ROWS_EVENT_V1: return "DELETE";
        case BinlogEventType::XID_EVENT: return "COMMIT";
        case BinlogEventType::ROTATE_EVENT: return "ROTATE";
        case BinlogEventType::FORMAT_DESCRIPTION_EVENT: return "FDE";
        case BinlogEventType::GTID_LOG_EVENT: return "GTID";
        default: return "UNKNOWN";
    }
}

} // namespace Database
} // namespace ForensicAnalyzer
