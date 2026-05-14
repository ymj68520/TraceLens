// PEImportExportParser.h
// PE导入/导出表解析器（骨架实现）

#pragma once
#ifndef PE_IMPORT_EXPORT_PARSER_H
#define PE_IMPORT_EXPORT_PARSER_H

#include <string>
#include <vector>
#include <fstream>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

/**
 * @brief PE导入/导出表解析器
 *
 * 职责：
 *   - 解析PE文件的导入表（IAT/INT）
 *   - 解析PE文件的导出表（EAT）
 *   - 计算ImpHash（基于导入函数名的模糊哈希）
 *
 * 注意：当前为骨架实现，完整解析将在后续任务中完成。
 *       未来将从PEHeaderParser获取数据目录RVA。
 */
class PEImportExportParser {
public:
    explicit PEImportExportParser(const std::string& filePath);
    ~PEImportExportParser();

    // 禁止拷贝
    PEImportExportParser(const PEImportExportParser&) = delete;
    PEImportExportParser& operator=(const PEImportExportParser&) = delete;

    /**
     * @brief 解析导入表
     * @param imports 输出参数，解析出的导入DLL列表
     * @return true 解析成功（即使为空也视为成功），false 文件错误
     */
    bool parseImports(std::vector<ImportedDLL>& imports);

    /**
     * @brief 解析导出表
     * @param exports 输出参数，解析出的导出函数列表
     * @return true 解析成功（即使为空也视为成功），false 文件错误
     */
    bool parseExports(std::vector<ExportedFunction>& exports);

    /**
     * @brief 计算ImpHash（Import Hash / dhash）
     * @return 导入函数名的16位十六进制哈希字符串，失败返回空字符串
     *
     * 算法：
     *   1. 收集所有导入DLL名称（转小写）及其导入函数名
     *   2. 按"dll.function"格式拼接字符串
     *   3. 对拼接后的字符串计算dhash
     */
    std::string calculateImpHash();

    bool isValid() const;
    std::string getErrorMessage() const;

public:
    // ---- PE格式内部结构（公开以便测试和外部验证）----

    /**
     * @brief IMAGE_IMPORT_DESCRIPTOR（每个导入DLL对应一个）
     *
     * 位于数据目录IMAGE_DIRECTORY_ENTRY_IMPORT指向的位置。
     */
    struct ImportDescriptor {
        uint32_t originalFirstThunk;   // INT RVA
        uint32_t timeDateStamp;
        uint32_t forwarderChain;
        uint32_t name;                 // DLL名称字符串RVA
        uint32_t firstThunk;           // IAT RVA
    };

    /**
     * @brief IMAGE_EXPORT_DIRECTORY（导出表头）
     */
    struct ExportDirectory {
        uint32_t characteristics;
        uint32_t timeDateStamp;
        uint16_t majorVersion;
        uint16_t minorVersion;
        uint32_t name;
        uint32_t base;
        uint32_t numberOfFunctions;
        uint32_t numberOfNames;
        uint32_t addressOfFunctions;   // EAT RVA
        uint32_t addressOfNames;       // ENT RVA
        uint32_t addressOfNameOrdinals;// EOT RVA
    };

private:

    // ---- 内部辅助方法 ----

    /**
     * @brief 读取并解析IMAGE_EXPORT_DIRECTORY
     * @return true 成功，false 失败
     */
    bool readExportDirectory(ExportDirectory& exportDir);

    /**
     * @brief 读取IMAGE_IMPORT_DESCRIPTOR数组
     * @return 解析结果，失败返回空
     */
    std::vector<ImportDescriptor> readImportDescriptors();

    /**
     * @brief 读取指定RVA位置的零终止字符串
     * @param rva 字符串相对虚拟地址
     * @param out 输出字符串
     * @return true 成功
     */
    bool readStringAt(uint32_t rva, std::string& out);

    /**
     * @brief 将RVA转换为文件偏移量
     * @param rva 相对虚拟地址
     * @return 文件偏移，失败返回UINT32_MAX
     */
    uint32_t rvaToOffset(uint32_t rva) const;

    /**
     * @brief 从文件读取指定偏移的数据
     * @param offset 文件偏移
     * @param buffer 输出缓冲区
     * @param size 读取字节数
     * @return true 成功
     */
    bool readAtOffset(uint32_t offset, void* buffer, uint32_t size) const;

    // ---- ImpHash 辅助 ----

    /**
     * @brief 简单的dhash实现，用于ImpHash计算
     * @param input 输入字符串
     * @return 16位小写十六进制哈希
     */
    static std::string computeDhash(const std::string& input);

    // ---- 成员变量 ----

    std::string filePath_;
    bool isValid_;
    std::string errorMessage_;

    // 缓存（TODO：未来应从PEHeaderParser注入，而非自行解析）
    uint32_t imageBase_ = 0;
    uint32_t fileAlignment_ = 0x200;
    uint32_t peHeaderOffset_ = 0;
    bool isPE32Plus_ = false;
    std::vector<SectionHeader> sections_; // 节表（简化：节名截断为8字节）
};

} // namespace dll
} // namespace forensics

#endif // PE_IMPORT_EXPORT_PARSER_H
