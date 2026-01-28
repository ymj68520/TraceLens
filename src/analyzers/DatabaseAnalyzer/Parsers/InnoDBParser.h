/**
 * @file InnoDBParser.h
 * @brief InnoDB 表空间文件解析器
 * 
 * 用于直接解析InnoDB .ibd文件和ibdata系统表空间
 * 支持页结构解析、记录提取和删除记录恢复
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
 * @brief InnoDB 页常量
 */
namespace InnoDB {
    // 页大小（默认16KB，可能是4K/8K/16K/32K/64K）
    constexpr size_t DEFAULT_PAGE_SIZE = 16384;
    
    // FIL Header偏移
    constexpr size_t FIL_PAGE_SPACE_OR_CHKSUM = 0;
    constexpr size_t FIL_PAGE_OFFSET = 4;
    constexpr size_t FIL_PAGE_PREV = 8;
    constexpr size_t FIL_PAGE_NEXT = 12;
    constexpr size_t FIL_PAGE_LSN = 16;
    constexpr size_t FIL_PAGE_TYPE = 24;
    constexpr size_t FIL_PAGE_FILE_FLUSH_LSN = 26;
    constexpr size_t FIL_PAGE_SPACE_ID = 34;
    constexpr size_t FIL_PAGE_DATA = 38;
    
    // Page Header偏移（相对于FIL_PAGE_DATA）
    constexpr size_t PAGE_N_DIR_SLOTS = 0;
    constexpr size_t PAGE_HEAP_TOP = 2;
    constexpr size_t PAGE_N_HEAP = 4;
    constexpr size_t PAGE_FREE = 6;
    constexpr size_t PAGE_GARBAGE = 8;
    constexpr size_t PAGE_LAST_INSERT = 10;
    constexpr size_t PAGE_DIRECTION = 12;
    constexpr size_t PAGE_N_DIRECTION = 14;
    constexpr size_t PAGE_N_RECS = 16;
    constexpr size_t PAGE_MAX_TRX_ID = 18;
    constexpr size_t PAGE_LEVEL = 26;
    constexpr size_t PAGE_INDEX_ID = 28;
    constexpr size_t PAGE_HEADER_SIZE = 36;
    
    // Infimum/Supremum
    constexpr size_t PAGE_NEW_INFIMUM = 99;   // Compact格式
    constexpr size_t PAGE_NEW_SUPREMUM = 112;
    constexpr size_t PAGE_OLD_INFIMUM = 101;  // Redundant格式
    constexpr size_t PAGE_OLD_SUPREMUM = 116;
    
    // 记录头偏移（Compact格式，5字节）
    constexpr size_t REC_N_NEW_EXTRA_BYTES = 5;
    constexpr size_t REC_N_OLD_EXTRA_BYTES = 6;
    
    // 页类型
    constexpr uint16_t FIL_PAGE_INDEX = 17855;
    constexpr uint16_t FIL_PAGE_UNDO_LOG = 2;
    constexpr uint16_t FIL_PAGE_INODE = 3;
    constexpr uint16_t FIL_PAGE_TYPE_FSP_HDR = 8;
    constexpr uint16_t FIL_PAGE_TYPE_XDES = 9;
}

/**
 * @brief 表列定义（用于记录解析）
 */
struct InnoDBColumnDef {
    std::string name;
    uint8_t mtype;      // 主类型 (DATA_INT, DATA_VARCHAR, etc.)
    uint8_t prtype;     // 精确类型
    uint32_t len;       // 固定长度或最大长度
    bool isNullable = true;
    bool isVariable = false;  // 是否变长
};

/**
 * @brief InnoDB 表空间解析器
 */
class InnoDBParser {
public:
    InnoDBParser();
    ~InnoDBParser();
    
    // 禁止拷贝
    InnoDBParser(const InnoDBParser&) = delete;
    InnoDBParser& operator=(const InnoDBParser&) = delete;
    
    /**
     * @brief 打开表空间文件
     * @param path .ibd或ibdata文件路径
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
     * @brief 获取页大小
     */
    size_t getPageSize() const { return pageSize_; }
    
    /**
     * @brief 获取总页数
     */
    uint32_t getTotalPages() const { return totalPages_; }
    
    // ========== 页操作 ==========
    
    /**
     * @brief 读取指定页
     */
    InnoDBPage readPage(uint32_t pageNo);
    
    /**
     * @brief 扫描所有INDEX页
     */
    std::vector<InnoDBPage> scanIndexPages();
    
    /**
     * @brief 获取页的原始数据
     */
    std::vector<uint8_t> getPageData(uint32_t pageNo);
    
    // ========== 记录操作 ==========
    
    /**
     * @brief 设置表结构（用于记录解析）
     */
    void setTableSchema(const std::vector<InnoDBColumnDef>& columns);
    
    /**
     * @brief 提取页中的所有记录
     */
    std::vector<DBRecordInfo> extractRecords(uint32_t pageNo);
    
    /**
     * @brief 提取所有叶子页的记录
     */
    std::vector<DBRecordInfo> extractAllRecords();
    
    /**
     * @brief 恢复删除的记录
     */
    std::vector<DBRecordInfo> recoverDeletedRecords();
    
    /**
     * @brief 扫描页中的删除记录
     */
    std::vector<DBRecordInfo> scanDeletedInPage(uint32_t pageNo);
    
    // ========== 工件转换 ==========
    
    /**
     * @brief 转换为取证工件
     */
    std::vector<DBArtifact> toArtifacts();
    
    /**
     * @brief 获取页统计信息
     */
    std::map<InnoDBPageType, uint32_t> getPageTypeStats();
    
    /**
     * @brief 获取最后错误
     */
    std::string getLastError() const { return lastError_; }

private:
    std::string path_;
    std::ifstream file_;
    size_t pageSize_ = InnoDB::DEFAULT_PAGE_SIZE;
    uint32_t totalPages_ = 0;
    uint32_t spaceId_ = 0;
    std::vector<InnoDBColumnDef> columns_;
    std::string lastError_;
    
    // 内部方法
    bool detectPageSize();
    bool parseFilePage(const std::vector<uint8_t>& data, InnoDBPage& page);
    bool parsePageHeader(const std::vector<uint8_t>& data, InnoDBPage& page);
    
    // 记录解析
    std::vector<DBRecordInfo> parseUserRecords(const std::vector<uint8_t>& pageData, 
                                                const InnoDBPage& page);
    DBRecordInfo parseRecord(const std::vector<uint8_t>& pageData, 
                             size_t offset, bool isDeleted);
    
    // 删除记录扫描
    std::vector<DBRecordInfo> scanFreeList(const std::vector<uint8_t>& pageData,
                                           const InnoDBPage& page);
    std::vector<DBRecordInfo> scanGarbage(const std::vector<uint8_t>& pageData,
                                          const InnoDBPage& page);
    
    // 辅助方法
    uint32_t readUint32BE(const uint8_t* data);
    uint16_t readUint16BE(const uint8_t* data);
    uint64_t readUint64BE(const uint8_t* data);
    
    void setError(const std::string& error);
};

/**
 * @brief InnoDB页类型转字符串
 */
inline std::string innoDBPageTypeToString(InnoDBPageType type) {
    switch (type) {
        case InnoDBPageType::FIL_PAGE_INDEX: return "INDEX";
        case InnoDBPageType::FIL_PAGE_UNDO_LOG: return "UNDO_LOG";
        case InnoDBPageType::FIL_PAGE_INODE: return "INODE";
        case InnoDBPageType::FIL_PAGE_TYPE_FSP_HDR: return "FSP_HDR";
        case InnoDBPageType::FIL_PAGE_TYPE_XDES: return "XDES";
        case InnoDBPageType::FIL_PAGE_TYPE_BLOB: return "BLOB";
        case InnoDBPageType::FIL_PAGE_TYPE_ALLOCATED: return "ALLOCATED";
        default: return "UNKNOWN";
    }
}

} // namespace Database
} // namespace ForensicAnalyzer
