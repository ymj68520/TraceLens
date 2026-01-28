/**
 * @file DBParserFactory.h
 * @brief 数据库解析器工厂
 * 
 * 使用工厂模式自动检测数据库类型并创建相应的解析器
 */

#pragma once

#include <string>
#include <memory>
#include <functional>
#include <map>

#include "IDBParser.h"

namespace ForensicAnalyzer {
namespace Database {

/**
 * @brief 解析器创建函数类型
 */
using ParserCreator = std::function<IDBParserPtr()>;

/**
 * @brief 数据库解析器工厂
 * 
 * 提供自动检测数据库类型和创建解析器的功能
 * 支持运行时注册新的解析器类型
 */
class DBParserFactory {
public:
    /**
     * @brief 检测文件或目录的数据库类型
     * @param path 文件或目录路径
     * @return 检测到的数据库类型
     */
    static DatabaseType detectType(const std::string& path);
    
    /**
     * @brief 根据路径自动创建解析器
     * @param path 数据库文件或目录路径
     * @return 解析器实例，如果无法识别返回nullptr
     */
    static IDBParserPtr createParser(const std::string& path);
    
    /**
     * @brief 根据指定类型创建解析器
     * @param type 数据库类型
     * @return 解析器实例
     */
    static IDBParserPtr createParser(DatabaseType type);
    
    /**
     * @brief 注册新的解析器类型
     * @param type 数据库类型
     * @param creator 创建函数
     * @note 用于扩展支持新的数据库类型
     */
    static void registerParser(DatabaseType type, ParserCreator creator);
    
    /**
     * @brief 获取已注册的解析器类型列表
     */
    static std::vector<DatabaseType> getRegisteredTypes();
    
    /**
     * @brief 检查是否支持指定类型
     */
    static bool isTypeSupported(DatabaseType type);
    
    /**
     * @brief 获取文件的Magic Bytes
     * @param path 文件路径
     * @param length 读取长度
     * @return Magic bytes字符串
     */
    static std::string getFileMagic(const std::string& path, size_t length = 16);

private:
    static std::map<DatabaseType, ParserCreator>& getRegistry();
    
    // 类型检测辅助函数
    static bool isSQLiteFile(const std::string& path);
    static bool isMySQLDataDir(const std::string& path);
    static bool isPostgreSQLDataDir(const std::string& path);
};

} // namespace Database
} // namespace ForensicAnalyzer
