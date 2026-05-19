// PEHeaderParser.h
// PE文件头解析器

#pragma once
#ifndef PE_HEADER_PARSER_H
#define PE_HEADER_PARSER_H

#include <string>
#include <vector>
#include <array>
#include <cmath>
#include <cstdint>
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

    // 获取PE头信息（供其他解析器使用）
    uint32_t getPEOffset() const { return peHeaderOffset_; }
    bool isPE32Plus() const { return isPE32Plus_; }

    // Rich Signature访问
    const std::string& getRichHash() const { return richHash_; }
    const std::vector<std::pair<uint32_t, uint32_t>>& getRichEntries() const { return richEntries_; }

    // 工具方法
    static std::string machineTypeToString(MachineType type);
    static std::string subsystemToString(SubsystemType type);
    static bool isDLL(uint16_t characteristics);

    // 节熵值计算（公开工具方法，供测试和外部使用）
    static double calculateEntropy(const std::vector<uint8_t>& data);

private:
    // 解析步骤
    bool parseDOSHeader();
    bool parsePEHeader();
    bool parseOptionalHeader();
    bool parseSectionTable();

    // 验证方法
    bool validateDOSHeader();
    bool validatePESignature();

    // 节数据读取（仅parseSectionTable内部使用）
    std::vector<uint8_t> readSectionData(const PESectionInfo& section);

    // Rich Signature解析
    bool parseRichSignature();

    std::string filePath_;
    std::ifstream file_;
    PEHeaderInfo headerInfo_;
    bool isValid_;
    std::string errorMessage_;

    // 缓存
    uint32_t peHeaderOffset_;
    bool isPE32Plus_;

    // Rich Signature缓存
    std::string richHash_;
    std::vector<std::pair<uint32_t, uint32_t>> richEntries_; // (toolID, version)
};

} // namespace dll
} // namespace forensics

#endif // PE_HEADER_PARSER_H
