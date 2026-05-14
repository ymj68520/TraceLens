// PEHeaderParser.h
// PE文件头解析器

#pragma once
#ifndef PE_HEADER_PARSER_H
#define PE_HEADER_PARSER_H

#include <string>
#include <vector>
#include <fstream>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class PEHeaderParser {
public:
    explicit PEHeaderParser(const std::string& filePath);
    ~PEHeaderParser();

    // 禁止拷贝
    PEHeaderParser(const PEHeaderParser&) = delete;
    PEHeaderParser& operator=(const PEHeaderParser&) = delete;

    // 解析PE文件
    bool parse();

    // 获取解析结果
    const PEHeaderInfo& getHeaderInfo() const;
    bool isValid() const;
    std::string getErrorMessage() const;

    // 工具方法
    static std::string machineTypeToString(MachineType type);
    static std::string subsystemToString(SubsystemType type);
    static bool isDLL(uint16_t characteristics);

private:
    // 解析步骤
    bool parseDOSHeader();
    bool parsePEHeader();
    bool parseOptionalHeader();
    bool parseSectionTable();

    // 验证方法
    bool validateDOSHeader();
    bool validatePESignature();

    std::string filePath_;
    std::ifstream file_;
    PEHeaderInfo headerInfo_;
    bool isValid_;
    std::string errorMessage_;

    // 缓存
    uint32_t peHeaderOffset_;
    bool isPE32Plus_;
};

} // namespace dll
} // namespace forensics

#endif // PE_HEADER_PARSER_H
