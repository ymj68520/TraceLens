/**
 * @file PostgreSQLHeapParser.h
 * @brief PostgreSQL 堆文件解析器
 * 
 * 用于直接解析PostgreSQL堆文件(base/OID/relfilenode)
 * 支持元组提取和死元组恢复
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
 * @brief PostgreSQL 常量
 */
namespace PG {
    // 默认块大小 (BLCKSZ)
    constexpr size_t DEFAULT_BLOCK_SIZE = 8192;
    
    // 页头大小
    constexpr size_t PAGE_HEADER_SIZE = 24;
    
    // PageHeaderData偏移
    constexpr size_t PD_LSN = 0;           // 8 bytes
    constexpr size_t PD_CHECKSUM = 8;      // 2 bytes (9.3+)
    constexpr size_t PD_FLAGS = 10;        // 2 bytes
    constexpr size_t PD_LOWER = 12;        // 2 bytes - 空闲空间开始
    constexpr size_t PD_UPPER = 14;        // 2 bytes - 空闲空间结束
    constexpr size_t PD_SPECIAL = 16;      // 2 bytes - 特殊区域偏移
    constexpr size_t PD_PAGESIZE_VERSION = 18; // 2 bytes
    constexpr size_t PD_PRUNE_XID = 20;    // 4 bytes
    
    // ItemId 相关
    constexpr size_t ITEM_ID_SIZE = 4;
    constexpr uint16_t LP_UNUSED = 0;
    constexpr uint16_t LP_NORMAL = 1;
    constexpr uint16_t LP_REDIRECT = 2;
    constexpr uint16_t LP_DEAD = 3;
    
    // HeapTupleHeader偏移
    constexpr size_t T_XMIN = 0;           // 4 bytes
    constexpr size_t T_XMAX = 4;           // 4 bytes
    constexpr size_t T_CID = 8;            // 4 bytes (union)
    constexpr size_t T_CTID = 12;          // 6 bytes (block + offset)
    constexpr size_t T_INFOMASK2 = 18;     // 2 bytes
    constexpr size_t T_INFOMASK = 20;      // 2 bytes
    constexpr size_t T_HOFF = 22;          // 1 byte - header offset
    constexpr size_t T_BITS = 23;          // null bitmap start
    
    // Infomask 标志
    constexpr uint16_t HEAP_HASNULL = 0x0001;
    constexpr uint16_t HEAP_HASVARWIDTH = 0x0002;
    constexpr uint16_t HEAP_HASEXTERNAL = 0x0004;
    constexpr uint16_t HEAP_XMAX_COMMITTED = 0x0200;
    constexpr uint16_t HEAP_XMAX_INVALID = 0x0400;
    constexpr uint16_t HEAP_XMAX_IS_MULTI = 0x1000;
}

/**
 * @brief PostgreSQL 列定义
 */
struct PGColumnDef {
    std::string name;
    uint32_t typid;         // oid of the type
    int16_t typlen;         // -1 for varlena, -2 for cstring
    bool typbyval = false;  // pass by value?
    char typalign = 'i';    // 对齐方式: c=char, s=short, i=int, d=double
    bool nullable = true;
};

/**
 * @brief PostgreSQL 堆文件解析器
 */
class PostgreSQLHeapParser {
public:
    PostgreSQLHeapParser();
    ~PostgreSQLHeapParser();
    
    // 禁止拷贝
    PostgreSQLHeapParser(const PostgreSQLHeapParser&) = delete;
    PostgreSQLHeapParser& operator=(const PostgreSQLHeapParser&) = delete;
    
    /**
     * @brief 打开堆文件
     * @param path 堆文件路径 (通常是 base/OID/relfilenode)
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
     * @brief 获取块大小
     */
    size_t getBlockSize() const { return blockSize_; }
    
    /**
     * @brief 获取总块数
     */
    uint32_t getTotalBlocks() const { return totalBlocks_; }
    
    // ========== 块操作 ==========
    
    /**
     * @brief 读取指定块的原始数据
     */
    std::vector<uint8_t> getBlockData(uint32_t blockNo);
    
    /**
     * @brief 获取块中的ItemId数组
     */
    std::vector<std::pair<uint16_t, uint16_t>> getItemIds(uint32_t blockNo);
    
    // ========== 元组操作 ==========
    
    /**
     * @brief 设置表结构
     */
    void setTableSchema(const std::vector<PGColumnDef>& columns);
    
    /**
     * @brief 提取块中的所有元组
     */
    std::vector<PGHeapTuple> extractTuples(uint32_t blockNo);
    
    /**
     * @brief 提取所有块的元组
     */
    std::vector<PGHeapTuple> extractAllTuples();
    
    /**
     * @brief 查找死元组 (VACUUM前的删除数据)
     */
    std::vector<PGHeapTuple> findDeadTuples();
    
    /**
     * @brief 查找指定块的死元组
     */
    std::vector<PGHeapTuple> findDeadTuplesInBlock(uint32_t blockNo);
    
    // ========== 工件转换 ==========
    
    /**
     * @brief 转换为取证工件
     */
    std::vector<DBArtifact> toArtifacts();
    
    /**
     * @brief 获取统计信息
     */
    std::map<std::string, uint32_t> getStats();
    
    /**
     * @brief 获取最后错误
     */
    std::string getLastError() const { return lastError_; }

private:
    std::string path_;
    std::ifstream file_;
    size_t blockSize_ = PG::DEFAULT_BLOCK_SIZE;
    uint32_t totalBlocks_ = 0;
    std::vector<PGColumnDef> columns_;
    std::string lastError_;
    
    // 内部方法
    bool detectBlockSize();
    PGHeapTuple parseTuple(const std::vector<uint8_t>& blockData,
                           uint16_t offset, uint16_t length,
                           uint32_t blockNo, uint16_t offsetNumber);
    
    // 辅助方法
    uint32_t readUint32(const uint8_t* data);
    uint16_t readUint16(const uint8_t* data);
    uint64_t readUint64(const uint8_t* data);
    
    void setError(const std::string& error);
};

} // namespace Database
} // namespace ForensicAnalyzer
