// ELFParser.h
// ELF文件格式解析器

#pragma once
#ifndef ELF_PARSER_H
#define ELF_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <fstream>
#include "DLLDataTypes.h"

namespace forensics {
namespace dll {

/**
 * @brief ELF文件解析器
 *
 * 职责：
 *   - 解析ELF文件标识和头
 *   - 解析程序头表（Program Headers）
 *   - 解析节头表（Section Headers）
 *   - 解析动态段（Dynamic Section）
 *   - 解析符号表（Symbol Table）
 *   - 计算节熵值
 */
class ELFParser {
public:
    ELFParser();
    ~ELFParser();

    // 禁止拷贝
    ELFParser(const ELFParser&) = delete;
    ELFParser& operator=(const ELFParser&) = delete;

    /**
     * @brief 解析ELF文件
     * @param filePath ELF文件路径
     * @return ELFHeaderInfo 包含所有解析数据
     */
    ELFHeaderInfo parse(const std::string& filePath);

    /**
     * @brief 验证ELF文件有效性
     * @param filePath ELF文件路径
     * @return true如果是有效的ELF文件
     */
    bool isValidELF(const std::string& filePath) const;

    /**
     * @brief 获取字符串表内容
     * @param filePath ELF文件路径
     * @param sectionOffset 节头表偏移
     * @param sectionIndex 节索引
     * @return 字符串表内容
     */
    std::string getStringTable(const std::string& filePath, uint64_t sectionOffset, uint32_t sectionIndex);

private:
    /**
     * @brief 解析ELF头
     * @param filePath ELF文件路径
     * @param info 输出头信息
     * @return true如果解析成功
     */
    bool parseELFHeader(const std::string& filePath, ELFHeaderInfo& info);

    /**
     * @brief 解析32位ELF头
     * @param file 文件流
     * @param info 输出头信息
     * @return true如果解析成功
     */
    bool parseELFHeader32(std::ifstream& file, ELFHeaderInfo& info);

    /**
     * @brief 解析64位ELF头
     * @param file 文件流
     * @param info 输出头信息
     * @return true如果解析成功
     */
    bool parseELFHeader64(std::ifstream& file, ELFHeaderInfo& info);

    /**
     * @brief 解析程序头表
     * @param filePath ELF文件路径
     * @param info 头信息
     */
    void parseProgramHeaders(const std::string& filePath, ELFHeaderInfo& info);

    /**
     * @brief 解析32位程序头
     * @param file 文件流
     * @param offset 偏移
     * @param count 数量
     * @param entries 输出程序头列表
     */
    void parseProgramHeaders32(std::ifstream& file, uint64_t offset, uint16_t count,
                                std::vector<ELFProgramHeader>& entries);

    /**
     * @brief 解析64位程序头
     * @param file 文件流
     * @param offset 偏移
     * @param count 数量
     * @param entries 输出程序头列表
     */
    void parseProgramHeaders64(std::ifstream& file, uint64_t offset, uint16_t count,
                                std::vector<ELFProgramHeader>& entries);

    /**
     * @brief 解析节头表
     * @param filePath ELF文件路径
     * @param info 头信息
     */
    void parseSectionHeaders(const std::string& filePath, ELFHeaderInfo& info);

    /**
     * @brief 解析32位节头表
     * @param file 文件流
     * @param offset 偏移
     * @param count 数量
     * @param entries 输出节头列表
     */
    void parseSectionHeaders32(std::ifstream& file, uint64_t offset, uint16_t count,
                                std::vector<ELFSectionInfo>& entries);

    /**
     * @brief 解析64位节头表
     * @param file 文件流
     * @param offset 偏移
     * @param count 数量
     * @param entries 输出节头列表
     */
    void parseSectionHeaders64(std::ifstream& file, uint64_t offset, uint16_t count,
                                std::vector<ELFSectionInfo>& entries);

    /**
     * @brief 解析动态段
     * @param filePath ELF文件路径
     * @param info 头信息
     */
    void parseDynamicSection(const std::string& filePath, ELFHeaderInfo& info);

    /**
     * @brief 解析32位动态段
     * @param file 文件流
     * @param offset 偏移
     * @param info 头信息
     */
    void parseDynamicSection32(std::ifstream& file, uint64_t offset, ELFHeaderInfo& info);

    /**
     * @brief 解析64位动态段
     * @param file 文件流
     * @param offset 偏移
     * @param info 头信息
     */
    void parseDynamicSection64(std::ifstream& file, uint64_t offset, ELFHeaderInfo& info);

    /**
     * @brief 解析符号表
     * @param filePath ELF文件路径
     * @param info 头信息
     */
    void parseSymbolTable(const std::string& filePath, ELFHeaderInfo& info);

    /**
     * @brief 解析32位符号表
     * @param file 文件流
     * @param strOffset 字符串表偏移
     * @param symOffset 符号表偏移
     * @param count 符号数量
     * @param strTab 字符串表
     * @param isDynamic 是否为动态符号表
     * @param info 头信息
     */
    void parseSymbolTable32(std::ifstream& file, uint64_t strOffset, uint64_t symOffset,
                             uint32_t count, const std::string& strTab, bool isDynamic,
                             ELFHeaderInfo& info);

    /**
     * @brief 解析64位符号表
     * @param file 文件流
     * @param strOffset 字符串表偏移
     * @param symOffset 符号表偏移
     * @param count 符号数量
     * @param strTab 字符串表
     * @param isDynamic 是否为动态符号表
     * @param info 头信息
     */
    void parseSymbolTable64(std::ifstream& file, uint64_t strOffset, uint64_t symOffset,
                             uint32_t count, const std::string& strTab, bool isDynamic,
                             ELFHeaderInfo& info);

    /**
     * @brief 计算节的熵值
     * @param filePath ELF文件路径
     * @param offset 节文件偏移
     * @param size 节大小
     * @return 熵值（0-8）
     */
    double calculateSectionEntropy(const std::string& filePath, uint64_t offset, uint64_t size);

    /**
     * @brief 从动态表项读取字符串
     * @param file 文件流
     * @param strTabOffset 字符串表偏移
     * @param strTabSize 字符串表大小
     * @param val 字符串偏移
     * @return 字符串
     */
    std::string readDynamicString(std::ifstream& file, uint64_t strTabOffset, uint64_t strTabSize, uint64_t val);

    /**
     * @brief 从节头字符串表读取字符串
     * @param file 文件流
     * @param strTabOffset 字符串表偏移
     * @param strTabSize 字符串表大小
     * @param nameOffset 名称偏移
     * @return 字符串
     */
    std::string readSectionName(std::ifstream& file, uint64_t strTabOffset, uint64_t strTabSize, uint32_t nameOffset);

    /**
     * @brief 读取文件内容到缓冲区
     * @param filePath 文件路径
     * @param offset 偏移
     * @param size 大小
     * @return 读取的缓冲区
     */
    std::vector<uint8_t> readFileBuffer(const std::string& filePath, uint64_t offset, uint64_t size);

    /**
     * @brief 获取机器类型名称
     * @param machine 机器类型编码
     * @return 可读的机器类型名称
     */
    std::string getMachineName(uint16_t machine) const;

    /**
     * @brief 获取ABI名称
     * @param osAbi OS/ABI编码
     * @return 可读的ABI名称
     */
    std::string getABIName(uint8_t osAbi) const;

    /**
     * @brief 获取节类型名称
     * @param type 节类型编码
     * @return 可读的节类型名称
     */
    std::string getSectionTypeName(uint32_t type) const;
};

} // namespace dll
} // namespace forensics

#endif // ELF_PARSER_H
