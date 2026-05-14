// PEHeaderParser.cpp
// PE文件头解析器实现

#include "PEHeaderParser.h"
#include <iostream>
#include <stdexcept>
#include <cstring>

using namespace forensics::dll;

PEHeaderParser::PEHeaderParser(const std::string& filePath)
    : filePath_(filePath), file_(filePath, std::ios::binary),
      isValid_(false), peHeaderOffset_(0), isPE32Plus_(false) {
    if (!file_.is_open()) {
        errorMessage_ = "Cannot open file: " + filePath;
    }
}

PEHeaderParser::~PEHeaderParser() {
    if (file_.is_open()) {
        file_.close();
    }
}

bool PEHeaderParser::parse() {
    if (!file_.is_open()) {
        return false;
    }

    // 1. 解析DOS头
    if (!parseDOSHeader()) {
        errorMessage_ = "Failed to parse DOS header";
        return false;
    }

    // 2. 验证PE签名
    if (!validatePESignature()) {
        errorMessage_ = "Invalid PE signature";
        return false;
    }

    // 3. 解析COFF头
    if (!parsePEHeader()) {
        errorMessage_ = "Failed to parse COFF header";
        return false;
    }

    // 4. 解析可选头
    if (!parseOptionalHeader()) {
        errorMessage_ = "Failed to parse optional header";
        return false;
    }

    // 5. 解析节表
    if (!parseSectionTable()) {
        errorMessage_ = "Failed to parse section table";
        return false;
    }

    isValid_ = true;
    return true;
}

bool PEHeaderParser::parseDOSHeader() {
    file_.seekg(0);
    DOSHeader dosHeader;
    file_.read(reinterpret_cast<char*>(&dosHeader), sizeof(DOSHeader));

    if (!file_ || file_.gcount() != sizeof(DOSHeader)) {
        return false;
    }

    // 验证DOS签名 "MZ"
    if (!validateDOSHeader()) {
        return false;
    }

    peHeaderOffset_ = dosHeader.e_lfanew;
    return true;
}

bool PEHeaderParser::validateDOSHeader() {
    file_.seekg(0);
    uint16_t magic;
    file_.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    return file_ && magic == DOS_MAGIC;
}

bool PEHeaderParser::validatePESignature() {
    file_.seekg(peHeaderOffset_);
    uint32_t signature;
    file_.read(reinterpret_cast<char*>(&signature), sizeof(signature));
    return file_ && signature == PE_SIGNATURE;
}

bool PEHeaderParser::parsePEHeader() {
    file_.seekg(peHeaderOffset_ + 4); // 跳过"PE\0\0"

    COFFHeader coffHeader;
    file_.read(reinterpret_cast<char*>(&coffHeader), sizeof(COFFHeader));

    if (!file_) {
        return false;
    }

    headerInfo_.machine = static_cast<MachineType>(coffHeader.machine);
    headerInfo_.numberOfSections = coffHeader.numberOfSections;
    headerInfo_.timestamp = coffHeader.timestamp;
    headerInfo_.characteristics = coffHeader.characteristics;
    headerInfo_.isDLL = isDLL(coffHeader.characteristics);

    return true;
}

bool PEHeaderParser::parseOptionalHeader() {
    // 定位到可选头开始位置
    file_.seekg(peHeaderOffset_ + 4 + sizeof(COFFHeader));

    uint16_t magic;
    file_.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    if (!file_) {
        return false;
    }

    isPE32Plus_ = (magic == PE32PLUS_MAGIC);
    headerInfo_.format = isPE32Plus_ ? "PE32+" : "PE32";

    file_.seekg(peHeaderOffset_ + 4 + sizeof(COFFHeader));
    OptionalHeaderBase baseHeader;
    file_.read(reinterpret_cast<char*>(&baseHeader), sizeof(OptionalHeaderBase));

    if (!file_) {
        return false;
    }

    headerInfo_.entryPointRVA = baseHeader.addressOfEntryPoint;
    headerInfo_.sectionAlignment = 0;
    headerInfo_.fileAlignment = 0;
    headerInfo_.subsystem = 0;
    headerInfo_.checkSum = 0;
    headerInfo_.imageBase = 0;

    // 读取可选头剩余字段（sectionAlignment起）
    if (isPE32Plus_) {
        // PE32+ OptionalHeaderPE32Plus (after OptionalHeaderBase)
        // imageBase (8) + sectionAlignment (4) + fileAlignment (4) +
        // majorOSVersion (2) + minorOSVersion (2) + majorImageVersion (2) + minorImageVersion (2) +
        // majorSubsystemVersion (2) + minorSubsystemVersion (2) + win32VersionValue (4) +
        // sizeOfImage (4) + sizeOfHeaders (4) + checkSum (4) + subsystem (2) + dllCharacteristics (2) +
        // sizeOfStackReserve (8) + sizeOfStackCommit (8) + sizeOfHeapReserve (8) + sizeOfHeapCommit (8) +
        // loaderFlags (4) + numberOfRvaAndSizes (4) + dataDirectories[16] (128)
        struct alignas(1) OptionalHeaderPE32PlusRest {
            uint64_t imageBase;
            uint32_t sectionAlignment;
            uint32_t fileAlignment;
            uint16_t majorOSVersion;
            uint16_t minorOSVersion;
            uint16_t majorImageVersion;
            uint16_t minorImageVersion;
            uint16_t majorSubsystemVersion;
            uint16_t minorSubsystemVersion;
            uint32_t win32VersionValue;
            uint32_t sizeOfImage;
            uint32_t sizeOfHeaders;
            uint32_t checkSum;
            uint16_t subsystem;
            uint16_t dllCharacteristics;
            uint64_t sizeOfStackReserve;
            uint64_t sizeOfStackCommit;
            uint64_t sizeOfHeapReserve;
            uint64_t sizeOfHeapCommit;
            uint32_t loaderFlags;
            uint32_t numberOfRvaAndSizes;
            DataDirectory dataDirectories[16];
        } rest;
        file_.read(reinterpret_cast<char*>(&rest), sizeof(rest));
        if (!file_) {
            return false;
        }
        headerInfo_.imageBase = rest.imageBase;
        headerInfo_.sectionAlignment = rest.sectionAlignment;
        headerInfo_.fileAlignment = rest.fileAlignment;
        headerInfo_.subsystem = rest.subsystem;
        headerInfo_.checkSum = rest.checkSum;
        headerInfo_.exportTableRVA = rest.dataDirectories[0].virtualAddress;
        headerInfo_.importTableRVA = rest.dataDirectories[1].virtualAddress;
        headerInfo_.resourceTableRVA = rest.dataDirectories[2].virtualAddress;
        headerInfo_.debugTableRVA = rest.dataDirectories[3].virtualAddress;
        headerInfo_.tlsTableRVA = rest.dataDirectories[4].virtualAddress;
        headerInfo_.loadConfigTableRVA = rest.dataDirectories[5].virtualAddress;
        headerInfo_.securityTableRVA = rest.dataDirectories[6].virtualAddress;
    } else {
        // PE32 OptionalHeaderPE32 (after OptionalHeaderBase)
        // baseOfData (4) + imageBase (4) + sectionAlignment (4) + fileAlignment (4) +
        // majorOSVersion (2) + minorOSVersion (2) + majorImageVersion (2) + minorImageVersion (2) +
        // majorSubsystemVersion (2) + minorSubsystemVersion (2) + win32VersionValue (4) +
        // sizeOfImage (4) + sizeOfHeaders (4) + checkSum (4) + subsystem (2) + dllCharacteristics (2) +
        // sizeOfStackReserve (4) + sizeOfStackCommit (4) + sizeOfHeapReserve (4) + sizeOfHeapCommit (4) +
        // loaderFlags (4) + numberOfRvaAndSizes (4) + dataDirectories[16] (128)
        struct alignas(1) OptionalHeaderPE32Rest {
            uint32_t baseOfData;
            uint32_t imageBase;
            uint32_t sectionAlignment;
            uint32_t fileAlignment;
            uint16_t majorOSVersion;
            uint16_t minorOSVersion;
            uint16_t majorImageVersion;
            uint16_t minorImageVersion;
            uint16_t majorSubsystemVersion;
            uint16_t minorSubsystemVersion;
            uint32_t win32VersionValue;
            uint32_t sizeOfImage;
            uint32_t sizeOfHeaders;
            uint32_t checkSum;
            uint16_t subsystem;
            uint16_t dllCharacteristics;
            uint32_t sizeOfStackReserve;
            uint32_t sizeOfStackCommit;
            uint32_t sizeOfHeapReserve;
            uint32_t sizeOfHeapCommit;
            uint32_t loaderFlags;
            uint32_t numberOfRvaAndSizes;
            DataDirectory dataDirectories[16];
        } rest;
        file_.read(reinterpret_cast<char*>(&rest), sizeof(rest));
        if (!file_) {
            return false;
        }
        headerInfo_.imageBase = rest.imageBase;
        headerInfo_.sectionAlignment = rest.sectionAlignment;
        headerInfo_.fileAlignment = rest.fileAlignment;
        headerInfo_.subsystem = rest.subsystem;
        headerInfo_.checkSum = rest.checkSum;
        headerInfo_.exportTableRVA = rest.dataDirectories[0].virtualAddress;
        headerInfo_.importTableRVA = rest.dataDirectories[1].virtualAddress;
        headerInfo_.resourceTableRVA = rest.dataDirectories[2].virtualAddress;
        headerInfo_.debugTableRVA = rest.dataDirectories[3].virtualAddress;
        headerInfo_.tlsTableRVA = rest.dataDirectories[4].virtualAddress;
        headerInfo_.loadConfigTableRVA = rest.dataDirectories[5].virtualAddress;
        headerInfo_.securityTableRVA = rest.dataDirectories[6].virtualAddress;
    }

    return true;
}

bool PEHeaderParser::parseSectionTable() {
    headerInfo_.sections.clear();
    headerInfo_.sections.reserve(headerInfo_.numberOfSections);

    // 节表偏移 = PE头偏移 + 4字节签名 + COFF头 + 可选头大小
    // OptionalHeaderBase = 24 bytes
    // PE32 rest: 4 + 4 + 4 + 4 + 2+2+2+2+2+2 + 4+4+4+4+2+2 + 4+4+4+4+4+4 + 128 = 200
    //   total PE32 optional = 24 + 200 = 224
    // PE32+ rest: 8 + 4 + 4 + 2+2+2+2+2+2 + 4+4+4+4+2+2 + 8+8+8+8 + 4+4 + 128 = 216
    //   total PE32+ optional = 24 + 216 = 240
    constexpr size_t PE32_OPTIONAL_SIZE = 224;
    constexpr size_t PE32PLUS_OPTIONAL_SIZE = 240;

    uint32_t optionalHeaderSize = isPE32Plus_ ? PE32PLUS_OPTIONAL_SIZE : PE32_OPTIONAL_SIZE;
    uint32_t sectionOffset = peHeaderOffset_ + 4 + sizeof(COFFHeader) + optionalHeaderSize;

    for (uint16_t i = 0; i < headerInfo_.numberOfSections; ++i) {
        file_.seekg(sectionOffset + i * sizeof(SectionHeader));

        SectionHeader section;
        file_.read(reinterpret_cast<char*>(&section), sizeof(SectionHeader));
        if (!file_) {
            return false;
        }

        PESectionInfo sectionInfo;
        sectionInfo.name = std::string(section.name, strnlen(section.name, 8));
        sectionInfo.virtualAddress = section.virtualAddress;
        sectionInfo.virtualSize = section.virtualSize;
        sectionInfo.rawDataSize = section.sizeOfRawData;
        sectionInfo.pointerToRawData = section.pointerToRawData;
        sectionInfo.characteristics = section.characteristics;

        // 解析节属性
        sectionInfo.isReadable = (section.characteristics & SECTION_READ) != 0;
        sectionInfo.isWriteable = (section.characteristics & SECTION_WRITE) != 0;
        sectionInfo.isExecutable = (section.characteristics & SECTION_EXECUTE) != 0;

        // 计算节熵值（跳过>100MB的节以避免内存问题）
        if (sectionInfo.rawDataSize > 0 && sectionInfo.rawDataSize < 100 * 1024 * 1024) {
            std::vector<uint8_t> sectionData = readSectionData(sectionInfo);
            if (!sectionData.empty()) {
                sectionInfo.entropy = calculateEntropy(sectionData);
            }
        }

        headerInfo_.sections.push_back(sectionInfo);
    }

    return true;
}

const PEHeaderInfo& PEHeaderParser::getHeaderInfo() const {
    return headerInfo_;
}

bool PEHeaderParser::isValid() const {
    return isValid_;
}

std::string PEHeaderParser::getErrorMessage() const {
    return errorMessage_;
}

// ============================================================================
// 节熵值计算
// ============================================================================

std::vector<uint8_t> PEHeaderParser::readSectionData(const PESectionInfo& section) {
    if (!file_.is_open() || section.rawDataSize == 0 || section.pointerToRawData == 0) {
        return {};
    }

    file_.seekg(section.pointerToRawData);
    std::vector<uint8_t> data(section.rawDataSize);
    file_.read(reinterpret_cast<char*>(data.data()), section.rawDataSize);

    if (!file_) {
        return {};
    }

    return data;
}

double PEHeaderParser::calculateEntropy(const std::vector<uint8_t>& data) {
    if (data.empty()) {
        return 0.0;
    }

    // 统计字节频率
    std::array<int, 256> freq = {0};
    for (uint8_t byte : data) {
        freq[byte]++;
    }

    // Shannon熵: H = -Σ p(x) * log2(p(x))
    // Range: 0-8 bits/byte
    // 0.0-6.0: Normal/Compressed
    // 6.0-7.0: Compressed/Packed
    // 7.0-8.0: Encrypted/Packed (highly suspicious)
    double entropy = 0.0;
    size_t total = data.size();

    for (int count : freq) {
        if (count > 0) {
            double probability = static_cast<double>(count) / total;
            entropy -= probability * std::log2(probability);
        }
    }

    return entropy;
}

// ============================================================================
// 工具方法
// ============================================================================

std::string PEHeaderParser::machineTypeToString(MachineType type) {
    switch (type) {
        case MachineType::X86: return "x86";
        case MachineType::x64: return "x64";
        case MachineType::ARM: return "ARM";
        case MachineType::ARM64: return "ARM64";
        case MachineType::IA64: return "IA64";
        default: return "Unknown";
    }
}

std::string PEHeaderParser::subsystemToString(SubsystemType type) {
    switch (type) {
        case SubsystemType::NATIVE: return "Native";
        case SubsystemType::WINDOWS_GUI: return "Windows GUI";
        case SubsystemType::WINDOWS_CUI: return "Windows Console";
        case SubsystemType::EFI_APPLICATION: return "EFI Application";
        case SubsystemType::EFI_BOOT_SERVICE: return "EFI Boot Service";
        case SubsystemType::EFI_RUNTIME: return "EFI Runtime";
        default: return "Unknown";
    }
}

bool PEHeaderParser::isDLL(uint16_t characteristics) {
    return (characteristics & 0x2000) != 0; // IMAGE_FILE_DLL
}
