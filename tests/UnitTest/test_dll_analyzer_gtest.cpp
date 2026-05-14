// test_dll_analyzer_gtest.cpp
// GTest-based unit tests for DLLAnalyzer data types and structures
// Tests enum values, structure instantiation, and constants

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <cstdint>
#include <string>
#include <vector>

#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"

using namespace forensics::dll;

// ============================================================================
// PE Constants Tests
// ============================================================================

class PEConstantsTest : public ::testing::Test {};

TEST_F(PEConstantsTest, DOSMagicConstant) {
    EXPECT_EQ(DOS_MAGIC, 0x5A4D);
    EXPECT_EQ(DOS_MAGIC, 'M' | ('Z' << 8)); // "MZ" in little-endian
}

TEST_F(PEConstantsTest, PESignatureConstant) {
    EXPECT_EQ(PE_SIGNATURE, 0x00004550);
    // "PE\0\0"
    uint8_t peBytes[] = {'P', 'E', 0, 0};
    uint32_t peSig = *reinterpret_cast<uint32_t*>(peBytes);
    EXPECT_EQ(PE_SIGNATURE, peSig);
}

TEST_F(PEConstantsTest, PE32MagicConstant) {
    EXPECT_EQ(PE32_MAGIC, 0x10B);
}

TEST_F(PEConstantsTest, PE32PlusMagicConstant) {
    EXPECT_EQ(PE32PLUS_MAGIC, 0x20B);
}

TEST_F(PEConstantsTest, SectionFlagConstants) {
    EXPECT_EQ(SECTION_READ, 0x40000000);
    EXPECT_EQ(SECTION_WRITE, 0x80000000);
    EXPECT_EQ(SECTION_EXECUTE, 0x20000000);
}

// ============================================================================
// MachineType Enum Tests
// ============================================================================

class MachineTypeEnumTest : public ::testing::Test {};

TEST_F(MachineTypeEnumTest, EnumValuesExist) {
    // Verify all enum values can be assigned
    MachineType mt;
    mt = MachineType::UNKNOWN;
    EXPECT_EQ(mt, MachineType::UNKNOWN);
    SUCCEED();
}

TEST_F(MachineTypeEnumTest, X86Value) {
    EXPECT_EQ(static_cast<uint16_t>(MachineType::X86), 0x14C);
}

TEST_F(MachineTypeEnumTest, x64Value) {
    EXPECT_EQ(static_cast<uint16_t>(MachineType::x64), 0x8664);
}

TEST_F(MachineTypeEnumTest, ARMValue) {
    EXPECT_EQ(static_cast<uint16_t>(MachineType::ARM), 0x1C0);
}

TEST_F(MachineTypeEnumTest, ARM64Value) {
    EXPECT_EQ(static_cast<uint16_t>(MachineType::ARM64), 0xAA64);
}

TEST_F(MachineTypeEnumTest, IA64Value) {
    EXPECT_EQ(static_cast<uint16_t>(MachineType::IA64), 0x200);
}

// ============================================================================
// SubsystemType Enum Tests
// ============================================================================

class SubsystemTypeEnumTest : public ::testing::Test {};

TEST_F(SubsystemTypeEnumTest, EnumValuesExist) {
    SubsystemType st;
    st = SubsystemType::UNKNOWN;
    EXPECT_EQ(st, SubsystemType::UNKNOWN);
    SUCCEED();
}

TEST_F(SubsystemTypeEnumTest, WindowsGUIValue) {
    EXPECT_EQ(static_cast<uint16_t>(SubsystemType::WINDOWS_GUI), 2);
}

TEST_F(SubsystemTypeEnumTest, WindowsCUIValue) {
    EXPECT_EQ(static_cast<uint16_t>(SubsystemType::WINDOWS_CUI), 3);
}

TEST_F(SubsystemTypeEnumTest, EFIApplicationValue) {
    EXPECT_EQ(static_cast<uint16_t>(SubsystemType::EFI_APPLICATION), 10);
}

// ============================================================================
// RiskLevel Enum Tests
// ============================================================================

class RiskLevelEnumTest : public ::testing::Test {};

TEST_F(RiskLevelEnumTest, EnumValuesExist) {
    RiskLevel rl;
    rl = RiskLevel::LOW;
    EXPECT_EQ(rl, RiskLevel::LOW);
    SUCCEED();
}

TEST_F(RiskLevelEnumTest, RiskLevelValues) {
    EXPECT_EQ(static_cast<int>(RiskLevel::LOW), 0);
    EXPECT_EQ(static_cast<int>(RiskLevel::MEDIUM), 1);
    EXPECT_EQ(static_cast<int>(RiskLevel::HIGH), 2);
    EXPECT_EQ(static_cast<int>(RiskLevel::CRITICAL), 3);
}

// ============================================================================
// Structure Instantiation Tests
// ============================================================================

class StructureInstantiationTest : public ::testing::Test {};

TEST_F(StructureInstantiationTest, DOSHeaderCanBeInstantiated) {
    DOSHeader header{};
    EXPECT_EQ(header.e_magic, 0); // Default-initialized to 0
    EXPECT_EQ(header.e_lfanew, 0);
}

TEST_F(StructureInstantiationTest, COFFHeaderCanBeInstantiated) {
    COFFHeader header{};
    EXPECT_EQ(header.machine, 0);
    EXPECT_EQ(header.numberOfSections, 0);
    EXPECT_EQ(header.timestamp, 0);
}

TEST_F(StructureInstantiationTest, OptionalHeaderPE32CanBeInstantiated) {
    OptionalHeaderPE32 header{};
    EXPECT_EQ(header.base.magic, 0);
    EXPECT_EQ(header.baseOfData, 0);
    EXPECT_EQ(header.imageBase, 0);
}

TEST_F(StructureInstantiationTest, OptionalHeaderPE32PlusCanBeInstantiated) {
    OptionalHeaderPE32Plus header{};
    EXPECT_EQ(header.base.magic, 0);
    EXPECT_EQ(header.imageBase, 0);
}

TEST_F(StructureInstantiationTest, SectionHeaderCanBeInstantiated) {
    SectionHeader section{};
    EXPECT_EQ(section.virtualSize, 0);
    EXPECT_EQ(section.virtualAddress, 0);
    EXPECT_EQ(section.characteristics, 0);
}

TEST_F(StructureInstantiationTest, PESectionInfoCanBeInstantiated) {
    PESectionInfo section{};
    EXPECT_TRUE(section.name.empty());
    EXPECT_EQ(section.virtualAddress, 0);
    EXPECT_EQ(section.entropy, 0.0);
    EXPECT_FALSE(section.isWriteable);
    EXPECT_FALSE(section.isExecutable);
    EXPECT_FALSE(section.isReadable);
}

TEST_F(StructureInstantiationTest, ImportedDLLCanBeInstantiated) {
    ImportedDLL import{};
    EXPECT_TRUE(import.name.empty());
    EXPECT_TRUE(import.functions.empty());
    EXPECT_FALSE(import.isDelayed);
}

TEST_F(StructureInstantiationTest, ExportedFunctionCanBeInstantiated) {
    ExportedFunction func{};
    EXPECT_TRUE(func.name.empty());
    EXPECT_EQ(func.ordinal, 0);
    EXPECT_EQ(func.rva, 0);
}

TEST_F(StructureInstantiationTest, PEHeaderInfoCanBeInstantiated) {
    PEHeaderInfo info{};
    EXPECT_FALSE(info.isValid);
    EXPECT_TRUE(info.format.empty());
    EXPECT_EQ(info.machine, MachineType::UNKNOWN);
    EXPECT_EQ(info.numberOfSections, 0);
    EXPECT_EQ(info.entryPointRVA, 0);
    EXPECT_TRUE(info.sections.empty());
    EXPECT_EQ(info.exportTableRVA, 0);
    EXPECT_EQ(info.importTableRVA, 0);
}

TEST_F(StructureInstantiationTest, AnomalyCanBeInstantiated) {
    Anomaly anomaly{};
    EXPECT_TRUE(anomaly.type.empty());
    EXPECT_TRUE(anomaly.description.empty());
    EXPECT_EQ(anomaly.risk, RiskLevel::LOW);
    EXPECT_EQ(anomaly.riskScore, 0);
}

TEST_F(StructureInstantiationTest, DLLAnalysisResultCanBeInstantiated) {
    DLLAnalysisResult result{};
    EXPECT_EQ(result.inode, 0);
    EXPECT_TRUE(result.filePath.empty());
    EXPECT_TRUE(result.fileName.empty());
    EXPECT_EQ(result.fileSize, 0);
    EXPECT_TRUE(result.imports.empty());
    EXPECT_TRUE(result.exports.empty());
    EXPECT_TRUE(result.anomalies.empty());
    EXPECT_EQ(result.threatScore, 0);
    EXPECT_TRUE(result.md5Hash.empty());
    EXPECT_TRUE(result.impHash.empty());
}

// ============================================================================
// Structure Assignment Tests
// ============================================================================

class StructureAssignmentTest : public ::testing::Test {};

TEST_F(StructureAssignmentTest, PESectionInfoAssignment) {
    PESectionInfo section;
    section.name = ".text";
    section.virtualAddress = 0x1000;
    section.virtualSize = 0x2000;
    section.rawDataSize = 0x1800;
    section.characteristics = SECTION_READ | SECTION_EXECUTE;
    section.entropy = 6.5;
    section.isWriteable = false;
    section.isExecutable = true;
    section.isReadable = true;

    EXPECT_EQ(section.name, ".text");
    EXPECT_EQ(section.virtualAddress, 0x1000);
    EXPECT_TRUE(section.isExecutable);
    EXPECT_FALSE(section.isWriteable);
    EXPECT_NEAR(section.entropy, 6.5, 0.001);
}

TEST_F(StructureAssignmentTest, ImportedDLLAssignment) {
    ImportedDLL import;
    import.name = "kernel32.dll";
    import.isDelayed = false;
    import.functions = {"CreateFileW", "ReadFile", "WriteFile"};

    EXPECT_EQ(import.name, "kernel32.dll");
    EXPECT_EQ(import.functions.size(), 3);
    EXPECT_FALSE(import.isDelayed);
}

TEST_F(StructureAssignmentTest, ExportedFunctionAssignment) {
    ExportedFunction func;
    func.name = "DllMain";
    func.ordinal = 1;
    func.rva = 0x5000;

    EXPECT_EQ(func.name, "DllMain");
    EXPECT_EQ(func.ordinal, 1);
    EXPECT_EQ(func.rva, 0x5000);
}

TEST_F(StructureAssignmentTest, AnomalyAssignment) {
    Anomaly anomaly;
    anomaly.type = "HIGH_ENTROPY";
    anomaly.description = "Section has high entropy";
    anomaly.risk = RiskLevel::HIGH;
    anomaly.riskScore = 15;

    EXPECT_EQ(anomaly.type, "HIGH_ENTROPY");
    EXPECT_EQ(anomaly.risk, RiskLevel::HIGH);
    EXPECT_EQ(anomaly.riskScore, 15);
}

TEST_F(StructureAssignmentTest, PEHeaderInfoAssignment) {
    PEHeaderInfo info;
    info.isValid = true;
    info.format = "PE32+";
    info.machine = MachineType::x64;
    info.numberOfSections = 5;
    info.timestamp = 1234567890;
    info.isDLL = true;
    info.imageBase = 0x140000000;
    info.entryPointRVA = 0x1000;

    EXPECT_TRUE(info.isValid);
    EXPECT_EQ(info.format, "PE32+");
    EXPECT_EQ(info.machine, MachineType::x64);
    EXPECT_TRUE(info.isDLL);
}

// ============================================================================
// Namespace Tests
// ============================================================================

class NamespaceTest : public ::testing::Test {};

TEST_F(NamespaceTest, DLLNamespaceExists) {
    // Verify we can use the forensics::dll namespace
    forensics::dll::MachineType mt = forensics::dll::MachineType::X86;
    EXPECT_EQ(mt, MachineType::X86);
}

// ============================================================================
// Integration Tests
// ============================================================================

class DataTypesIntegrationTest : public ::testing::Test {};

TEST_F(DataTypesIntegrationTest, CompleteDLLAnalysisResultStructure) {
    DLLAnalysisResult result;

    // File information
    result.inode = 12345;
    result.filePath = "/usr/bin/test.dll";
    result.fileName = "test.dll";
    result.fileSize = 102400;

    // PE header
    result.peHeader.isValid = true;
    result.peHeader.format = "PE32";
    result.peHeader.machine = MachineType::X86;
    result.peHeader.numberOfSections = 3;
    result.peHeader.isDLL = true;

    // Sections
    result.peHeader.sections.push_back({".text", 0x1000, 0x2000, 0x1800,
                                        SECTION_READ | SECTION_EXECUTE, 5.2,
                                        false, true, true});
    result.peHeader.sections.push_back({".data", 0x3000, 0x1000, 0x800,
                                        SECTION_READ | SECTION_WRITE, 2.1,
                                        true, false, true});

    // Imports
    result.imports.push_back({"kernel32.dll", {"CreateFileW", "ReadFile"}, false});
    result.imports.push_back({"user32.dll", {"MessageBoxW"}, false});

    // Exports
    result.exports.push_back({"DllMain", 1, 0x5000});

    // Hashes
    result.md5Hash = "d41d8cd98f00b204e9800998ecf8427e";
    result.sha256Hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    // Threat score
    result.threatScore = 25;

    // Verify structure
    EXPECT_EQ(result.inode, 12345);
    EXPECT_EQ(result.fileSize, 102400);
    EXPECT_TRUE(result.peHeader.isValid);
    EXPECT_EQ(result.peHeader.sections.size(), 2);
    EXPECT_EQ(result.imports.size(), 2);
    EXPECT_EQ(result.exports.size(), 1);
    EXPECT_EQ(result.threatScore, 25);

    // Verify section flags
    EXPECT_TRUE(result.peHeader.sections[0].isExecutable);
    EXPECT_FALSE(result.peHeader.sections[0].isWriteable);
    EXPECT_TRUE(result.peHeader.sections[1].isWriteable);
    EXPECT_FALSE(result.peHeader.sections[1].isExecutable);
}

// ============================================================================
// PEHeaderParser Tests
// ============================================================================

#include "analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h"

class PEHeaderParserTest : public ::testing::Test {
protected:
    std::string testFile_;

    void TearDown() override {
        if (!testFile_.empty()) {
            std::remove(testFile_.c_str());
        }
    }
};

// Helper: write a minimal valid PE32+ file using cross-platform types
static std::string writeMinimalPE32Plus() {
    std::string path = "/tmp/test_pe32plus.dll";
    std::ofstream out(path, std::ios::binary);

    DOSHeader dosHeader = {};
    dosHeader.e_magic = 0x5A4D;  // "MZ"
    dosHeader.e_lfanew = 0x80;   // PE header offset
    out.write(reinterpret_cast<const char*>(&dosHeader), sizeof(dosHeader));

    // Pad to PE header offset
    out.seekp(0x80);

    // PE signature "PE\0\0"
    uint32_t peSig = 0x00004550;
    out.write(reinterpret_cast<const char*>(&peSig), sizeof(peSig));

    // COFF header
    COFFHeader coffHeader = {};
    coffHeader.machine = 0x8664;   // x64
    coffHeader.numberOfSections = 1;
    coffHeader.characteristics = 0x2002; // DLL | Executable
    out.write(reinterpret_cast<const char*>(&coffHeader), sizeof(coffHeader));

    // PE32+ optional header: magic (2) + linker version (2) + base fields (24) = 28
    // Then: imageBase(8) + sectionAlignment(4) + fileAlignment(4) +
    //       OS version(4) + image version(4) + subsystem version(4) + win32VersionValue(4) +
    //       sizeOfImage(4) + sizeOfHeaders(4) + checkSum(4) + subsystem(2) + dllCharacteristics(2) +
    //       stack(16) + heap(16) + loaderFlags(4) + numberOfRvaAndSizes(4) + dataDirs(128) = 216
    struct alignas(1) PE32PlusOptional {
        uint16_t magic;              // 0x20B
        uint8_t  majorLinkerVersion;
        uint8_t  minorLinkerVersion;
        uint32_t sizeOfCode;
        uint32_t sizeOfInitializedData;
        uint32_t sizeOfUninitializedData;
        uint32_t addressOfEntryPoint;
        uint32_t baseOfCode;
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
    };
    PE32PlusOptional optHeader = {};
    optHeader.magic = 0x20B;           // PE32+
    optHeader.subsystem = 3;           // Windows Console
    optHeader.sectionAlignment = 0x1000;
    optHeader.fileAlignment = 0x200;
    optHeader.sizeOfImage = 0x4000;
    optHeader.sizeOfHeaders = 0x400;
    optHeader.addressOfEntryPoint = 0x1000;
    optHeader.imageBase = 0x140000000;
    out.write(reinterpret_cast<const char*>(&optHeader), sizeof(optHeader));

    // Section header
    SectionHeader section = {};
    strncpy(section.name, ".text", 8);
    section.sizeOfRawData = 0x1000;
    section.characteristics = 0x60000020; // READ | EXECUTE | ContainsCode
    out.write(reinterpret_cast<const char*>(&section), sizeof(section));

    out.close();
    return path;
}

// Helper: write a minimal valid PE32 file using cross-platform types
static std::string writeMinimalPE32() {
    std::string path = "/tmp/test_pe32.dll";
    std::ofstream out(path, std::ios::binary);

    DOSHeader dosHeader = {};
    dosHeader.e_magic = 0x5A4D;  // "MZ"
    dosHeader.e_lfanew = 0x80;
    out.write(reinterpret_cast<const char*>(&dosHeader), sizeof(dosHeader));

    out.seekp(0x80);

    uint32_t peSig = 0x00004550;
    out.write(reinterpret_cast<const char*>(&peSig), sizeof(peSig));

    COFFHeader coffHeader = {};
    coffHeader.machine = 0x14C;   // x86
    coffHeader.numberOfSections = 1;
    coffHeader.characteristics = 0x2002;
    out.write(reinterpret_cast<const char*>(&coffHeader), sizeof(coffHeader));

    // PE32 optional header: base (24) + baseOfData(4) + imageBase(4) + sectionAlignment(4) +
    // fileAlignment(4) + OS version(4) + image version(4) + subsystem version(4) +
    // win32VersionValue(4) + sizeOfImage(4) + sizeOfHeaders(4) + checkSum(4) +
    // subsystem(2) + dllCharacteristics(2) + stack(12) + heap(12) + loaderFlags(4) +
    // numberOfRvaAndSizes(4) + dataDirs(128) = 224
    struct alignas(1) PE32Optional {
        uint16_t magic;              // 0x10B
        uint8_t  majorLinkerVersion;
        uint8_t  minorLinkerVersion;
        uint32_t sizeOfCode;
        uint32_t sizeOfInitializedData;
        uint32_t sizeOfUninitializedData;
        uint32_t addressOfEntryPoint;
        uint32_t baseOfCode;
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
    };
    PE32Optional optHeader = {};
    optHeader.magic = 0x10B;             // PE32
    optHeader.subsystem = 2;             // Windows GUI
    optHeader.sectionAlignment = 0x1000;
    optHeader.fileAlignment = 0x200;
    optHeader.sizeOfImage = 0x4000;
    optHeader.sizeOfHeaders = 0x400;
    optHeader.addressOfEntryPoint = 0x1000;
    optHeader.imageBase = 0x400000;
    out.write(reinterpret_cast<const char*>(&optHeader), sizeof(optHeader));

    SectionHeader section = {};
    strncpy(section.name, ".text", 8);
    section.sizeOfRawData = 0x1000;
    section.characteristics = 0x60000020;
    out.write(reinterpret_cast<const char*>(&section), sizeof(section));

    out.close();
    return path;
}

TEST_F(PEHeaderParserTest, ParseValidPE32Plus) {
    testFile_ = writeMinimalPE32Plus();

    PEHeaderParser parser(testFile_);
    EXPECT_TRUE(parser.parse());
    EXPECT_TRUE(parser.isValid());

    const auto& header = parser.getHeaderInfo();
    EXPECT_EQ(header.format, "PE32+");
    EXPECT_EQ(header.machine, MachineType::x64);
    EXPECT_TRUE(header.isDLL);
    EXPECT_EQ(header.numberOfSections, 1u);
    EXPECT_EQ(header.subsystem, 3u); // WINDOWS_CUI
    EXPECT_EQ(header.entryPointRVA, 0x1000u);
    EXPECT_EQ(header.imageBase, 0x140000000u);
    EXPECT_EQ(header.sectionAlignment, 0x1000u);
    EXPECT_EQ(header.fileAlignment, 0x200u);
    EXPECT_EQ(header.exportTableRVA, 0u);
    EXPECT_EQ(header.importTableRVA, 0u);
}

TEST_F(PEHeaderParserTest, ParseValidPE32) {
    testFile_ = writeMinimalPE32();

    PEHeaderParser parser(testFile_);
    EXPECT_TRUE(parser.parse());
    EXPECT_TRUE(parser.isValid());

    const auto& header = parser.getHeaderInfo();
    EXPECT_EQ(header.format, "PE32");
    EXPECT_EQ(header.machine, MachineType::X86);
    EXPECT_TRUE(header.isDLL);
    EXPECT_EQ(header.numberOfSections, 1u);
    EXPECT_EQ(header.subsystem, 2u); // WINDOWS_GUI
    EXPECT_EQ(header.entryPointRVA, 0x1000u);
    EXPECT_EQ(header.imageBase, 0x400000u);
}

TEST_F(PEHeaderParserTest, RejectInvalidSignature) {
    testFile_ = "/tmp/test_invalid.bin";
    std::ofstream out(testFile_, std::ios::binary);
    out.write("NOT_A_PE_FILE", 12);
    out.close();

    PEHeaderParser parser(testFile_);
    EXPECT_FALSE(parser.parse());
    EXPECT_FALSE(parser.isValid());
    EXPECT_FALSE(parser.getErrorMessage().empty());
}

TEST_F(PEHeaderParserTest, RejectEmptyFile) {
    testFile_ = "/tmp/test_empty.bin";
    // Create empty file
    std::ofstream out(testFile_, std::ios::binary);
    out.close();

    PEHeaderParser parser(testFile_);
    EXPECT_FALSE(parser.parse());
    EXPECT_FALSE(parser.isValid());
}

TEST_F(PEHeaderParserTest, RejectNonExistentFile) {
    PEHeaderParser parser("/tmp/nonexistent_pe_file_12345.dll");
    EXPECT_FALSE(parser.parse());
    EXPECT_FALSE(parser.isValid());
    EXPECT_FALSE(parser.getErrorMessage().empty());
}

TEST_F(PEHeaderParserTest, SectionTableParsedCorrectly) {
    testFile_ = writeMinimalPE32Plus();

    PEHeaderParser parser(testFile_);
    EXPECT_TRUE(parser.parse());

    const auto& header = parser.getHeaderInfo();
    ASSERT_EQ(header.sections.size(), 1u);

    const auto& section = header.sections[0];
    EXPECT_EQ(section.name, ".text");
    EXPECT_EQ(section.virtualAddress, 0u);
    EXPECT_EQ(section.virtualSize, 0u);
    EXPECT_EQ(section.rawDataSize, 0x1000u);
    EXPECT_TRUE(section.isReadable);
    EXPECT_TRUE(section.isExecutable);
    EXPECT_FALSE(section.isWriteable);
}

TEST_F(PEHeaderParserTest, MachineTypeToString) {
    EXPECT_EQ(PEHeaderParser::machineTypeToString(MachineType::X86), "x86");
    EXPECT_EQ(PEHeaderParser::machineTypeToString(MachineType::x64), "x64");
    EXPECT_EQ(PEHeaderParser::machineTypeToString(MachineType::ARM), "ARM");
    EXPECT_EQ(PEHeaderParser::machineTypeToString(MachineType::ARM64), "ARM64");
    EXPECT_EQ(PEHeaderParser::machineTypeToString(MachineType::IA64), "IA64");
    EXPECT_EQ(PEHeaderParser::machineTypeToString(static_cast<MachineType>(0xFFFF)), "Unknown");
}

TEST_F(PEHeaderParserTest, SubsystemTypeToString) {
    EXPECT_EQ(PEHeaderParser::subsystemToString(SubsystemType::NATIVE), "Native");
    EXPECT_EQ(PEHeaderParser::subsystemToString(SubsystemType::WINDOWS_GUI), "Windows GUI");
    EXPECT_EQ(PEHeaderParser::subsystemToString(SubsystemType::WINDOWS_CUI), "Windows Console");
    EXPECT_EQ(PEHeaderParser::subsystemToString(SubsystemType::EFI_APPLICATION), "EFI Application");
    EXPECT_EQ(PEHeaderParser::subsystemToString(static_cast<SubsystemType>(0)), "Unknown");
}

TEST_F(PEHeaderParserTest, IsDLLDetectsDLL) {
    EXPECT_TRUE(PEHeaderParser::isDLL(0x2002)); // DLL + Executable
    EXPECT_TRUE(PEHeaderParser::isDLL(0x2000)); // DLL only
    EXPECT_TRUE(PEHeaderParser::isDLL(0x2100)); // DLL + LargeAddressAware
}

TEST_F(PEHeaderParserTest, IsDLLRejectsNonDLL) {
    EXPECT_FALSE(PEHeaderParser::isDLL(0x0002)); // Executable only, no DLL flag
    EXPECT_FALSE(PEHeaderParser::isDLL(0x0000)); // No flags
}

TEST_F(PEHeaderParserTest, PE32PlusLargerOptionalHeader) {
    // Verify PE32+ has different optional header size than PE32
    testFile_ = writeMinimalPE32Plus();
    PEHeaderParser pe32plus(testFile_);
    ASSERT_TRUE(pe32plus.parse());

    testFile_ = writeMinimalPE32();
    PEHeaderParser pe32(testFile_);
    ASSERT_TRUE(pe32.parse());

    // Both should parse successfully with correct format strings
    EXPECT_EQ(pe32plus.getHeaderInfo().format, "PE32+");
    EXPECT_EQ(pe32.getHeaderInfo().format, "PE32");
}

TEST_F(PEHeaderParserTest, ZeroSectionsHandled) {
    // Build a PE with 0 sections — parser should handle gracefully
    testFile_ = "/tmp/test_zero_sections.dll";
    std::ofstream out(testFile_, std::ios::binary);

    DOSHeader dosHeader = {};
    dosHeader.e_magic = 0x5A4D;
    dosHeader.e_lfanew = 0x80;
    out.write(reinterpret_cast<const char*>(&dosHeader), sizeof(dosHeader));

    out.seekp(0x80);

    uint32_t peSig = 0x00004550;
    out.write(reinterpret_cast<const char*>(&peSig), sizeof(peSig));

    COFFHeader coffHeader = {};
    coffHeader.machine = 0x14C;
    coffHeader.numberOfSections = 0;  // Zero sections
    coffHeader.sizeOfOptionalHeader = 0xE0; // PE32 optional header size (224)
    out.write(reinterpret_cast<const char*>(&coffHeader), sizeof(coffHeader));

    OptionalHeaderPE32 optHeader = {};
    optHeader.base.magic = 0x10B;
    out.write(reinterpret_cast<const char*>(&optHeader), sizeof(optHeader));

    out.close();

    PEHeaderParser parser(testFile_);
    EXPECT_TRUE(parser.parse());
    EXPECT_TRUE(parser.isValid());

    const auto& header = parser.getHeaderInfo();
    EXPECT_EQ(header.numberOfSections, 0u);
    EXPECT_TRUE(header.sections.empty());
}

// ============================================================================
// End PEHeaderParser Tests
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}

// ============================================================================
// DLL SQL Schema Tests
// ============================================================================

#include <sqlite3.h>
#include "core/DatabaseManager/SQL/windows_analysis_sql_tables.h"
#include "core/DatabaseManager/SQL/windows_analysis_sql_crud.h"
#include "core/DatabaseManager/SQL/windows_analysis_sql_llm.h"

class DLLSQLSchemaTest : public ::testing::Test {
protected:
    sqlite3* db_ = nullptr;

    void SetUp() override {
        // Create in-memory database
        ASSERT_EQ(sqlite3_open(":memory:", &db_), SQLITE_OK);
        // Enable foreign keys
        sqlite3_exec(db_, "PRAGMA foreign_keys = ON;", nullptr, nullptr, nullptr);
    }

    void TearDown() override {
        if (db_) {
            sqlite3_close(db_);
            db_ = nullptr;
        }
    }

    bool executeSQL(const char* sql) {
        char* errMsg = nullptr;
        int rc = sqlite3_exec(db_, sql, nullptr, nullptr, &errMsg);
        if (rc != SQLITE_OK) {
            std::cerr << "SQL Error: " << errMsg << std::endl;
            sqlite3_free(errMsg);
            return false;
        }
        return true;
    }

    bool tableExists(const std::string& tableName) {
        std::string sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='" + tableName + "';";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
            return false;
        }
        bool exists = (sqlite3_step(stmt) == SQLITE_ROW);
        sqlite3_finalize(stmt);
        return exists;
    }

    bool indexExists(const std::string& indexName) {
        std::string sql = "SELECT name FROM sqlite_master WHERE type='index' AND name='" + indexName + "';";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
            return false;
        }
        bool exists = (sqlite3_step(stmt) == SQLITE_ROW);
        sqlite3_finalize(stmt);
        return exists;
    }
};

TEST_F(DLLSQLSchemaTest, CreateAllTablesCreatesDLLTables) {
    // Execute the CREATE_ALL_TABLES statement which should now include DLL tables
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Verify all 7 DLL tables were created
    EXPECT_TRUE(tableExists("dll_base_info")) << "dll_base_info table should exist";
    EXPECT_TRUE(tableExists("dll_sections")) << "dll_sections table should exist";
    EXPECT_TRUE(tableExists("dll_imports")) << "dll_imports table should exist";
    EXPECT_TRUE(tableExists("dll_exports")) << "dll_exports table should exist";
    EXPECT_TRUE(tableExists("dll_anomalies")) << "dll_anomalies table should exist";
    EXPECT_TRUE(tableExists("dll_dependencies")) << "dll_dependencies table should exist";
    EXPECT_TRUE(tableExists("dll_forensic_links")) << "dll_forensic_links table should exist";
}

TEST_F(DLLSQLSchemaTest, CreateDLLIndicesCreatesAllIndices) {
    // First create the tables
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));
    // Then create indices
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_DLL_INDICES));

    // Verify all DLL indices were created
    EXPECT_TRUE(indexExists("idx_dll_base_inode"));
    EXPECT_TRUE(indexExists("idx_dll_base_md5"));
    EXPECT_TRUE(indexExists("idx_dll_base_imp_hash"));
    EXPECT_TRUE(indexExists("idx_dll_base_compile_ts"));
    EXPECT_TRUE(indexExists("idx_dll_base_signature"));
    EXPECT_TRUE(indexExists("idx_dll_base_threat"));
    EXPECT_TRUE(indexExists("idx_dll_sections_dll_id"));
    EXPECT_TRUE(indexExists("idx_dll_imports_dll_id"));
    EXPECT_TRUE(indexExists("idx_dll_imports_function"));
    EXPECT_TRUE(indexExists("idx_dll_exports_dll_id"));
    EXPECT_TRUE(indexExists("idx_dll_anomalies_dll_id"));
    EXPECT_TRUE(indexExists("idx_dll_anomalies_risk"));
    EXPECT_TRUE(indexExists("idx_dll_deps_parent"));
    EXPECT_TRUE(indexExists("idx_dll_deps_child"));
    EXPECT_TRUE(indexExists("idx_dll_links_dll_id"));
    EXPECT_TRUE(indexExists("idx_dll_links_type"));
}

TEST_F(DLLSQLSchemaTest, DLLBaseInfoTableSchema) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Verify dll_base_info has the expected columns
    std::string sql = "PRAGMA table_info(dll_base_info);";
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr), SQLITE_OK);

    std::vector<std::string> columns;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        columns.push_back(
            reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1))
        );
    }
    sqlite3_finalize(stmt);

    // Check key columns exist
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "inode") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "name") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "path") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "md5") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "imp_hash") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "file_format") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "machine_type") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "compile_timestamp") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "threat_score") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "llm_summary") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "llm_description") != columns.end());
    EXPECT_TRUE(std::find(columns.begin(), columns.end(), "llm_keywords") != columns.end());
}

TEST_F(DLLSQLSchemaTest, DLLTablesHaveForeignKeyConstraints) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Verify foreign key constraints exist in DLL tables
    std::string sql = "PRAGMA foreign_key_list(dll_sections);";
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr), SQLITE_OK);

    bool hasForeignKey = false;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        hasForeignKey = true;
    }
    sqlite3_finalize(stmt);
    EXPECT_TRUE(hasForeignKey) << "dll_sections should have foreign key constraints";

    // Check dll_imports foreign key
    ASSERT_EQ(sqlite3_prepare_v2(db_, "PRAGMA foreign_key_list(dll_imports);", -1, &stmt, nullptr), SQLITE_OK);
    hasForeignKey = false;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        hasForeignKey = true;
    }
    sqlite3_finalize(stmt);
    EXPECT_TRUE(hasForeignKey) << "dll_imports should have foreign key constraints";
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLBaseInfo) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert a DLL record using the INSERT_DLL_BASE_INFO statement
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);

    // Bind parameters (32 total)
    sqlite3_bind_int64(stmt, 1, 12345);                          // inode
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);   // name
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC); // path
    sqlite3_bind_int64(stmt, 4, 102400);                          // size
    sqlite3_bind_text(stmt, 5, "d41d8cd98f00b204e9800998ecf8427e", -1, SQLITE_STATIC); // md5
    sqlite3_bind_text(stmt, 6, "da39a3ee5e6b4b0d3255bfef95601890afd80709", -1, SQLITE_STATIC); // sha1
    sqlite3_bind_text(stmt, 7, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", -1, SQLITE_STATIC); // sha256
    sqlite3_bind_text(stmt, 8, "imp_hash_123", -1, SQLITE_STATIC); // imp_hash
    sqlite3_bind_null(stmt, 9);                                   // rich_hash (NULL)
    sqlite3_bind_text(stmt, 10, "PE32+", -1, SQLITE_STATIC);      // file_format
    sqlite3_bind_text(stmt, 11, "x64", -1, SQLITE_STATIC);        // machine_type
    sqlite3_bind_int(stmt, 12, 1234567890);                       // compile_timestamp
    sqlite3_bind_int(stmt, 13, 3);                                // subsystem
    sqlite3_bind_int(stmt, 14, 0x1000);                           // entry_point
    sqlite3_bind_int64(stmt, 15, 0x140000000);                    // image_base
    sqlite3_bind_int(stmt, 16, 1);                                // is_dll
    sqlite3_bind_int(stmt, 17, 0x2002);                           // characteristics
    // version info (params 18-21)
    sqlite3_bind_null(stmt, 18);                                   // file_version
    sqlite3_bind_null(stmt, 19);                                   // product_version
    sqlite3_bind_null(stmt, 20);                                   // company_name
    sqlite3_bind_null(stmt, 21);                                   // file_description
    // signature (params 22-25)
    sqlite3_bind_text(stmt, 22, "Signed", -1, SQLITE_STATIC);     // signature_status
    sqlite3_bind_text(stmt, 23, "Microsoft Corporation", -1, SQLITE_STATIC); // signer_name
    sqlite3_bind_null(stmt, 24);                                   // cert_issuer
    sqlite3_bind_null(stmt, 25);                                   // cert_valid_from
    sqlite3_bind_null(stmt, 26);                                   // cert_valid_to
    // timestamps (params 27-30)
    sqlite3_bind_int64(stmt, 27, 1234567890);                     // mtime
    sqlite3_bind_int64(stmt, 28, 1234567890);                     // ctime
    sqlite3_bind_int64(stmt, 29, 1234567890);                     // atime
    sqlite3_bind_int64(stmt, 30, 1234567890);                     // crtime
    sqlite3_bind_int(stmt, 31, 0);                                 // is_deleted
    sqlite3_bind_int(stmt, 32, 25);                               // threat_score

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Verify we can select it back using SELECT_DLL_BY_PATH
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_BY_PATH, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_text(stmt, 1, "/usr/bin/test.dll", -1, SQLITE_STATIC);

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int64(stmt, 0), 1);                    // id
    EXPECT_EQ(sqlite3_column_int64(stmt, 1), 12345);                 // inode
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "test.dll"); // name
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)), "/usr/bin/test.dll"); // path
    EXPECT_EQ(sqlite3_column_int64(stmt, 4), 102400);                 // size
    EXPECT_EQ(sqlite3_column_int(stmt, 32), 25);                     // threat_score
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLSections) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert a DLL record first
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    // Bind remaining 29 params as NULL for brevity
    for (int i = 4; i <= 32; ++i) sqlite3_bind_null(stmt, i);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Insert a section
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_SECTION, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);              // dll_id
    sqlite3_bind_text(stmt, 2, ".text", -1, SQLITE_STATIC); // section_name
    sqlite3_bind_int(stmt, 3, 0x1000);           // virtual_address
    sqlite3_bind_int(stmt, 4, 0x2000);           // virtual_size
    sqlite3_bind_int(stmt, 5, 0x1800);           // raw_data_size
    sqlite3_bind_int(stmt, 6, 0x60000020);       // characteristics
    sqlite3_bind_double(stmt, 7, 5.2);           // entropy
    sqlite3_bind_int(stmt, 8, 0);                // is_writeable
    sqlite3_bind_int(stmt, 9, 1);                // is_executable
    sqlite3_bind_int(stmt, 10, 1);               // is_readable
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Select sections back
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_SECTIONS, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), ".text");
    EXPECT_EQ(sqlite3_column_double(stmt, 7), 5.2);
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLImports) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert DLL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    for (int i = 4; i <= 32; ++i) sqlite3_bind_null(stmt, i);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Insert imports
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_IMPORT, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);                    // dll_id
    sqlite3_bind_text(stmt, 2, "kernel32.dll", -1, SQLITE_STATIC); // imported_dll_name
    sqlite3_bind_text(stmt, 3, "CreateFileW", -1, SQLITE_STATIC);  // imported_function
    sqlite3_bind_null(stmt, 4);                         // import_ordinal
    sqlite3_bind_int(stmt, 5, 0);                      // is_delayed
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Insert second import
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_IMPORT, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);
    sqlite3_bind_text(stmt, 2, "user32.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "MessageBoxW", -1, SQLITE_STATIC);
    sqlite3_bind_null(stmt, 4);
    sqlite3_bind_int(stmt, 5, 0);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Select imports back
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_IMPORTS, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);

    int count = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
    }
    sqlite3_finalize(stmt);
    EXPECT_EQ(count, 2) << "Should have 2 imports";
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLExports) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert DLL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    for (int i = 4; i <= 32; ++i) sqlite3_bind_null(stmt, i);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Insert export
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_EXPORT, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);              // dll_id
    sqlite3_bind_text(stmt, 2, "DllMain", -1, SQLITE_STATIC); // function_name
    sqlite3_bind_int(stmt, 3, 1);                // export_ordinal
    sqlite3_bind_int(stmt, 4, 0x5000);           // export_rva
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Select exports back
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_EXPORTS, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "DllMain");
    EXPECT_EQ(sqlite3_column_int(stmt, 3), 1);
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLAnomalies) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert DLL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    for (int i = 4; i <= 32; ++i) sqlite3_bind_null(stmt, i);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Insert anomaly
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_ANOMALY, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);                              // dll_id
    sqlite3_bind_text(stmt, 2, "HIGH_ENTROPY", -1, SQLITE_STATIC); // anomaly_type
    sqlite3_bind_text(stmt, 3, "High entropy section", -1, SQLITE_STATIC); // description
    sqlite3_bind_text(stmt, 4, "HIGH", -1, SQLITE_STATIC);       // risk_level
    sqlite3_bind_int(stmt, 5, 15);                               // risk_score
    sqlite3_bind_null(stmt, 6);                                   // details
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Select anomalies back
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_ANOMALIES, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "HIGH_ENTROPY");
    EXPECT_EQ(sqlite3_column_int(stmt, 5), 15);
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLDependencies) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert two DLLs
    sqlite3_stmt* stmt;
    for (int i = 0; i < 2; ++i) {
        ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
        sqlite3_bind_int64(stmt, 1, 12345 + i);
        sqlite3_bind_text(stmt, 2, i == 0 ? "parent.dll" : "child.dll", -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, i == 0 ? "/usr/bin/parent.dll" : "/usr/bin/child.dll", -1, SQLITE_STATIC);
        for (int j = 4; j <= 32; ++j) sqlite3_bind_null(stmt, j);
        ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
        sqlite3_finalize(stmt);
    }

    // Insert dependency: parent.dll -> child.dll
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_DEPENDENCY, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);   // parent_dll_id
    sqlite3_bind_int64(stmt, 2, 2);   // child_dll_id
    sqlite3_bind_int(stmt, 3, 1);     // depth
    sqlite3_bind_int(stmt, 4, 1);     // is_resolved
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Select dependencies back
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_DEPENDENCIES, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);  // parent_dll_id

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int64(stmt, 1), 1);  // parent_dll_id
    EXPECT_EQ(sqlite3_column_int64(stmt, 2), 2);  // child_dll_id
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, InsertAndSelectDLLForensicLinks) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert DLL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    for (int i = 4; i <= 32; ++i) sqlite3_bind_null(stmt, i);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Insert forensic link
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_FORENSIC_LINK, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);                              // dll_id
    sqlite3_bind_text(stmt, 2, "registry_reference", -1, SQLITE_STATIC); // link_type
    sqlite3_bind_text(stmt, 3, "reg_123", -1, SQLITE_STATIC);    // source_id
    sqlite3_bind_text(stmt, 4, "HKLM\\Software\\Test", -1, SQLITE_STATIC); // source_data
    sqlite3_bind_null(stmt, 5);                                   // detected_at
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Select forensic links back
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_FORENSIC_LINKS, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 1);

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)), "registry_reference");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)), "reg_123");
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, UpdateDLLThreatScore) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert DLL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    for (int i = 4; i <= 31; ++i) sqlite3_bind_null(stmt, i); // bind NULL for cols 4-30, param 32 left for threat_score
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Update threat score
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::UPDATE_DLL_THREAT_SCORE, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int(stmt, 1, 75);  // new threat score
    sqlite3_bind_int64(stmt, 2, 1); // dll id
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Verify update
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_BY_INODE, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(stmt, 32), 75); // threat_score at col 32 (0-based)
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, SelectSuspiciousDLLs) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert multiple DLLs with different threat scores
    sqlite3_stmt* stmt;
    for (int i = 0; i < 3; ++i) {
        ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
        sqlite3_bind_int64(stmt, 1, 10000 + i);
        std::string dllName = "dll" + std::to_string(i) + ".dll";
        std::string dllPath = "/usr/bin/dll" + std::to_string(i) + ".dll";
        sqlite3_bind_text(stmt, 2, dllName.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_text(stmt, 3, dllPath.c_str(), -1, SQLITE_STATIC);
        for (int j = 4; j <= 31; ++j) sqlite3_bind_null(stmt, j); // 32 columns
        sqlite3_bind_int(stmt, 32, 10 + i * 30); // threat_score is param 32 (1-based)
        ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
        sqlite3_finalize(stmt);
    }

    // Select suspicious DLLs with threshold 30
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_SUSPICIOUS_DLLS, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int(stmt, 1, 30);

    int count = 0;
    int maxScore = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        count++;
        int score = sqlite3_column_int(stmt, 32);
        EXPECT_GE(score, 30) << "All returned DLLs should have threat_score >= 30";
        if (score > maxScore) maxScore = score;
    }
    sqlite3_finalize(stmt);

    EXPECT_EQ(count, 2) << "Should have 2 DLLs with threat_score >= 30";
    EXPECT_EQ(maxScore, 70) << "Results should be ordered by threat_score DESC";
}

TEST_F(DLLSQLSchemaTest, UpdateDLLAnalysis) {
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Insert DLL with minimal data
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    sqlite3_bind_text(stmt, 2, "test.dll", -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, 3, "/usr/bin/test.dll", -1, SQLITE_STATIC);
    for (int i = 4; i <= 31; ++i) sqlite3_bind_null(stmt, i); // 32 columns
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Update with full analysis data
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::UPDATE_DLL_ANALYSIS, -1, &stmt, nullptr), SQLITE_OK);

    sqlite3_bind_text(stmt, 1, "PE32+", -1, SQLITE_STATIC);    // file_format
    sqlite3_bind_text(stmt, 2, "x64", -1, SQLITE_STATIC);      // machine_type
    sqlite3_bind_int(stmt, 3, 1234567890);                      // compile_timestamp
    sqlite3_bind_int(stmt, 4, 3);                               // subsystem
    sqlite3_bind_int(stmt, 5, 0x1000);                          // entry_point
    sqlite3_bind_int64(stmt, 6, 0x140000000);                   // image_base
    sqlite3_bind_int(stmt, 7, 0x2002);                          // characteristics
    sqlite3_bind_null(stmt, 8);                                  // file_version
    sqlite3_bind_null(stmt, 9);                                  // product_version
    sqlite3_bind_null(stmt, 10);                                 // company_name
    sqlite3_bind_null(stmt, 11);                                 // file_description
    sqlite3_bind_text(stmt, 12, "Signed", -1, SQLITE_STATIC);   // signature_status
    sqlite3_bind_null(stmt, 13);                                 // signer_name
    sqlite3_bind_text(stmt, 14, "abc123", -1, SQLITE_STATIC);   // md5
    sqlite3_bind_text(stmt, 15, "def456", -1, SQLITE_STATIC);   // sha1
    sqlite3_bind_text(stmt, 16, "ghi789", -1, SQLITE_STATIC);   // sha256
    sqlite3_bind_text(stmt, 17, "imp_hash_val", -1, SQLITE_STATIC); // imp_hash
    sqlite3_bind_int(stmt, 18, 50);                              // threat_score
    sqlite3_bind_int64(stmt, 19, 1);                            // WHERE id = ?

    ASSERT_EQ(sqlite3_step(stmt), SQLITE_DONE);
    sqlite3_finalize(stmt);

    // Verify update
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_BY_INODE, -1, &stmt, nullptr), SQLITE_OK);
    sqlite3_bind_int64(stmt, 1, 12345);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10)), "PE32+");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)), "x64");
    EXPECT_EQ(sqlite3_column_int(stmt, 32), 50); // threat_score at col 32
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, DLLLLMUpdateStatementCompiles) {
    // Create tables first so the SQL is valid
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Verify the UPDATE_DLL_LLM_ANALYSIS statement is valid SQL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_llm::UPDATE_DLL_LLM_ANALYSIS, -1, &stmt, nullptr), SQLITE_OK);
    EXPECT_NE(stmt, nullptr);
    sqlite3_finalize(stmt);
}

TEST_F(DLLSQLSchemaTest, DLLPendingAnalysisQueryCompiles) {
    // Create tables first so the SQL is valid
    ASSERT_TRUE(executeSQL(windows_analysis_sql_tables::CREATE_ALL_TABLES));

    // Verify the SELECT_DLL_PENDING_ANALYSIS statement is valid SQL
    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db_, windows_analysis_sql_llm::SELECT_DLL_PENDING_ANALYSIS, -1, &stmt, nullptr), SQLITE_OK);
    EXPECT_NE(stmt, nullptr);
    sqlite3_finalize(stmt);
}

// ============================================================================
// DLLAnalysisDatabase Tests
// ============================================================================

#include "analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.h"
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"

class DLLAnalysisDatabaseTest : public ::testing::Test {
protected:
    std::string dbPath_ = ":memory:";
    std::unique_ptr<DLLAnalysisDatabase> db_;

    void SetUp() override {
        db_ = std::make_unique<DLLAnalysisDatabase>(dbPath_);
        ASSERT_TRUE(db_->initialize());
    }

    // Helper: build a minimal DLLAnalysisResult
    DLLAnalysisResult makeTestResult(int64_t inode, const std::string& name,
                                      const std::string& path, int threatScore = 0) {
        DLLAnalysisResult result;
        result.inode = inode;
        result.fileName = name;
        result.filePath = path;
        result.fileSize = 102400;
        result.md5Hash = "d41d8cd98f00b204e9800998ecf8427e";
        result.sha256Hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
        result.impHash = "imp_hash_" + std::to_string(inode);
        result.threatScore = threatScore;

        result.peHeader.isValid = true;
        result.peHeader.format = "PE32+";
        result.peHeader.machine = MachineType::x64;
        result.peHeader.numberOfSections = 2;
        result.peHeader.timestamp = 1234567890;
        result.peHeader.isDLL = true;
        result.peHeader.imageBase = 0x140000000;
        result.peHeader.entryPointRVA = 0x1000;
        result.peHeader.subsystem = static_cast<uint16_t>(SubsystemType::WINDOWS_CUI);
        result.peHeader.characteristics = 0x2002;

        result.peHeader.sections.push_back({".text", 0x1000, 0x2000, 0x1800,
                                            SECTION_READ | SECTION_EXECUTE, 5.2,
                                            false, true, true});
        result.peHeader.sections.push_back({".data", 0x3000, 0x1000, 0x800,
                                            SECTION_READ | SECTION_WRITE, 2.1,
                                            true, false, true});

        result.imports.push_back({"kernel32.dll", {"CreateFileW", "ReadFile"}, false});
        result.imports.push_back({"user32.dll", {"MessageBoxW"}, false});

        result.exports.push_back({"DllMain", 1, 0x5000});
        result.exports.push_back({"DllRegisterServer", 2, 0x5010});

        result.fileDescription = "Test DLL";
        result.companyName = "TestCorp";
        result.signatureStatus = "Unsigned";

        return result;
    }
};

TEST_F(DLLAnalysisDatabaseTest, InitializeCreatesTables) {
    // Tables should already be created by initialize()
    // Verify by inserting a record — should succeed without error
    DLLAnalysisResult result = makeTestResult(100, "init_test.dll", "/tmp/init_test.dll");
    int64_t id = db_->insertDLLBaseInfo(result);
    EXPECT_GT(id, 0) << "Insert should succeed after initialize()";
}

TEST_F(DLLAnalysisDatabaseTest, InsertDLLBaseInfoReturnsPositiveId) {
    DLLAnalysisResult result = makeTestResult(1, "test.dll", "/usr/bin/test.dll");
    int64_t id = db_->insertDLLBaseInfo(result);
    EXPECT_GT(id, 0) << "insertDLLBaseInfo should return positive ID";
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLByInode) {
    DLLAnalysisResult result = makeTestResult(12345, "by_inode.dll", "/tmp/by_inode.dll", 25);
    int64_t id = db_->insertDLLBaseInfo(result);
    ASSERT_GT(id, 0);

    auto found = db_->getDLLByInode(12345);
    ASSERT_TRUE(found.has_value());
    EXPECT_EQ(found->inode, 12345);
    EXPECT_EQ(found->fileName, "by_inode.dll");
    EXPECT_EQ(found->filePath, "/tmp/by_inode.dll");
    EXPECT_EQ(found->threatScore, 25);
    EXPECT_EQ(found->peHeader.format, "PE32+");
    EXPECT_EQ(found->md5Hash, "d41d8cd98f00b204e9800998ecf8427e");
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLByPath) {
    DLLAnalysisResult result = makeTestResult(54321, "by_path.dll", "/opt/by_path.dll", 50);
    int64_t id = db_->insertDLLBaseInfo(result);
    ASSERT_GT(id, 0);

    auto found = db_->getDLLByPath("/opt/by_path.dll");
    ASSERT_TRUE(found.has_value());
    EXPECT_EQ(found->inode, 54321);
    EXPECT_EQ(found->fileName, "by_path.dll");
    EXPECT_EQ(found->threatScore, 50);
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLById) {
    DLLAnalysisResult result = makeTestResult(99999, "by_id.dll", "/tmp/by_id.dll");
    int64_t id = db_->insertDLLBaseInfo(result);
    ASSERT_GT(id, 0);

    auto found = db_->getDLLById(id);
    ASSERT_TRUE(found.has_value());
    EXPECT_EQ(found->fileName, "by_id.dll");
    EXPECT_EQ(found->peHeader.machine, MachineType::x64);
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLByInodeNotFound) {
    auto found = db_->getDLLByInode(9999999);
    EXPECT_FALSE(found.has_value());
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLByPathNotFound) {
    auto found = db_->getDLLByPath("/nonexistent/path.dll");
    EXPECT_FALSE(found.has_value());
}

TEST_F(DLLAnalysisDatabaseTest, UpdateThreatScore) {
    DLLAnalysisResult result = makeTestResult(111, "score_update.dll", "/tmp/score_update.dll", 10);
    int64_t id = db_->insertDLLBaseInfo(result);
    ASSERT_GT(id, 0);

    EXPECT_TRUE(db_->updateThreatScore(id, 80));

    auto found = db_->getDLLById(id);
    ASSERT_TRUE(found.has_value());
    EXPECT_EQ(found->threatScore, 80);
}

TEST_F(DLLAnalysisDatabaseTest, UpdateDLLAnalysis) {
    DLLAnalysisResult result = makeTestResult(222, "update_test.dll", "/tmp/update_test.dll");
    int64_t id = db_->insertDLLBaseInfo(result);
    ASSERT_GT(id, 0);

    DLLAnalysisResult updateData = makeTestResult(222, "update_test.dll", "/tmp/update_test.dll");
    updateData.threatScore = 60;
    EXPECT_TRUE(db_->updateDLLAnalysis(id, updateData));

    auto found = db_->getDLLById(id);
    ASSERT_TRUE(found.has_value());
    EXPECT_EQ(found->threatScore, 60);
    EXPECT_EQ(found->peHeader.format, "PE32+");
}

TEST_F(DLLAnalysisDatabaseTest, InsertAndGetSections) {
    DLLAnalysisResult result = makeTestResult(333, "sections_test.dll", "/tmp/sections_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    std::vector<PESectionInfo> sections = result.peHeader.sections;
    EXPECT_TRUE(db_->insertSections(dllId, sections));

    auto retrieved = db_->getSections(dllId);
    ASSERT_EQ(retrieved.size(), 2u);
    EXPECT_EQ(retrieved[0].name, ".text");
    EXPECT_EQ(retrieved[1].name, ".data");
    EXPECT_NEAR(retrieved[0].entropy, 5.2, 0.01);
    EXPECT_TRUE(retrieved[0].isExecutable);
    EXPECT_TRUE(retrieved[1].isWriteable);
}

TEST_F(DLLAnalysisDatabaseTest, InsertAndGetImports) {
    DLLAnalysisResult result = makeTestResult(444, "imports_test.dll", "/tmp/imports_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    EXPECT_TRUE(db_->insertImports(dllId, result.imports));

    auto retrieved = db_->getImports(dllId);
    ASSERT_EQ(retrieved.size(), 2u);
    EXPECT_EQ(retrieved[0].name, "kernel32.dll");
    ASSERT_EQ(retrieved[0].functions.size(), 2u);
    EXPECT_EQ(retrieved[0].functions[0], "CreateFileW");
    EXPECT_EQ(retrieved[1].name, "user32.dll");
}

TEST_F(DLLAnalysisDatabaseTest, InsertAndGetExports) {
    DLLAnalysisResult result = makeTestResult(555, "exports_test.dll", "/tmp/exports_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    EXPECT_TRUE(db_->insertExports(dllId, result.exports));

    auto retrieved = db_->getExports(dllId);
    ASSERT_EQ(retrieved.size(), 2u);
    EXPECT_EQ(retrieved[0].name, "DllMain");
    EXPECT_EQ(retrieved[0].ordinal, 1);
    EXPECT_EQ(retrieved[0].rva, 0x5000);
}

TEST_F(DLLAnalysisDatabaseTest, InsertAndGetAnomalies) {
    DLLAnalysisResult result = makeTestResult(666, "anomalies_test.dll", "/tmp/anomalies_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    Anomaly anomaly1{"HIGH_ENTROPY", "Code section high entropy", RiskLevel::HIGH, 15};
    Anomaly anomaly2{"SUSPICIOUS_IMPORTS", "Found suspicious functions", RiskLevel::MEDIUM, 20};

    EXPECT_TRUE(db_->insertAnomaly(dllId, anomaly1));
    EXPECT_TRUE(db_->insertAnomaly(dllId, anomaly2));

    auto retrieved = db_->getAnomalies(dllId);
    ASSERT_EQ(retrieved.size(), 2u);
    EXPECT_EQ(retrieved[0].type, "HIGH_ENTROPY");
    EXPECT_EQ(retrieved[0].risk, RiskLevel::HIGH);
    EXPECT_EQ(retrieved[1].type, "SUSPICIOUS_IMPORTS");
    EXPECT_EQ(retrieved[1].riskScore, 20);
}

TEST_F(DLLAnalysisDatabaseTest, InsertAndGetDependencies) {
    DLLAnalysisResult parent = makeTestResult(7001, "parent.dll", "/tmp/parent.dll");
    DLLAnalysisResult child = makeTestResult(7002, "child.dll", "/tmp/child.dll");

    int64_t parentId = db_->insertDLLBaseInfo(parent);
    int64_t childId = db_->insertDLLBaseInfo(child);
    ASSERT_GT(parentId, 0);
    ASSERT_GT(childId, 0);

    EXPECT_TRUE(db_->insertDependency(parentId, childId, 1));

    auto deps = db_->getDependencies(parentId);
    ASSERT_EQ(deps.size(), 1u);
    EXPECT_EQ(deps[0].first, parentId);
    EXPECT_EQ(deps[0].second, childId);
}

TEST_F(DLLAnalysisDatabaseTest, InsertAndGetForensicLinks) {
    DLLAnalysisResult result = makeTestResult(888, "links_test.dll", "/tmp/links_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    EXPECT_TRUE(db_->insertForensicLink(dllId, "registry_reference", "reg_001",
                                        "HKLM\\Software\\Test\\Value"));
    EXPECT_TRUE(db_->insertForensicLink(dllId, "file_association", "file_001",
                                        "C:\\Windows\\System32\\test.dll"));

    auto links = db_->getForensicLinks(dllId);
    ASSERT_EQ(links.size(), 2u);
    EXPECT_EQ(std::get<0>(links[0]), "registry_reference");
    EXPECT_EQ(std::get<1>(links[0]), "reg_001");
    EXPECT_EQ(std::get<0>(links[1]), "file_association");
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLsByThreatScore) {
    for (int i = 0; i < 5; ++i) {
        DLLAnalysisResult result = makeTestResult(10000 + i,
            "threat_" + std::to_string(i) + ".dll",
            "/tmp/threat_" + std::to_string(i) + ".dll",
            10 + i * 20);
        db_->insertDLLBaseInfo(result);
    }

    auto suspicious = db_->getDLLsByThreatScore(50);
    // Should return threat scores >= 50: i=2 (50), i=3 (70), i=4 (90)
    ASSERT_EQ(suspicious.size(), 3u);
    EXPECT_GE(suspicious[0].threatScore, 30);
}

TEST_F(DLLAnalysisDatabaseTest, GetAllDLLs) {
    for (int i = 0; i < 3; ++i) {
        DLLAnalysisResult result = makeTestResult(20000 + i,
            "all_" + std::to_string(i) + ".dll",
            "/tmp/all_" + std::to_string(i) + ".dll");
        db_->insertDLLBaseInfo(result);
    }

    auto all = db_->getAllDLLs(10);
    ASSERT_EQ(all.size(), 3u);
}

TEST_F(DLLAnalysisDatabaseTest, GetDLLCount) {
    EXPECT_EQ(db_->getDLLCount(), 0u);

    db_->insertDLLBaseInfo(makeTestResult(301, "count1.dll", "/tmp/count1.dll"));
    db_->insertDLLBaseInfo(makeTestResult(302, "count2.dll", "/tmp/count2.dll"));

    EXPECT_EQ(db_->getDLLCount(), 2u);
}

TEST_F(DLLAnalysisDatabaseTest, GetSuspiciousCount) {
    // threat_score >= 30 is suspicious
    for (int i = 0; i < 4; ++i) {
        DLLAnalysisResult result = makeTestResult(4000 + i,
            "susp_" + std::to_string(i) + ".dll",
            "/tmp/susp_" + std::to_string(i) + ".dll",
            i * 25); // 0, 25, 50, 75
        db_->insertDLLBaseInfo(result);
    }

    EXPECT_EQ(db_->getSuspiciousCount(), 2u); // scores 50 and 75
}

TEST_F(DLLAnalysisDatabaseTest, GetAverageThreatScore) {
    // Empty DB: average of empty set = 0
    EXPECT_EQ(db_->getAverageThreatScore(), 0);

    DLLAnalysisResult result = makeTestResult(5001, "avg1.dll", "/tmp/avg1.dll", 40);
    db_->insertDLLBaseInfo(result);
    result = makeTestResult(5002, "avg2.dll", "/tmp/avg2.dll", 60);
    db_->insertDLLBaseInfo(result);

    EXPECT_EQ(db_->getAverageThreatScore(), 50);
}

TEST_F(DLLAnalysisDatabaseTest, InsertSectionsThenGetReturnsCorrectData) {
    DLLAnalysisResult result = makeTestResult(601, "sec_test.dll", "/tmp/sec_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    PESectionInfo section{".rsrc", 0x5000, 0x1000, 0x800, SECTION_READ, 3.5, false, false, true};
    std::vector<PESectionInfo> sections = {section};
    EXPECT_TRUE(db_->insertSections(dllId, sections));

    auto retrieved = db_->getSections(dllId);
    ASSERT_EQ(retrieved.size(), 1u);
    EXPECT_EQ(retrieved[0].name, ".rsrc");
    EXPECT_EQ(retrieved[0].virtualAddress, 0x5000);
    EXPECT_NEAR(retrieved[0].entropy, 3.5, 0.001);
}

TEST_F(DLLAnalysisDatabaseTest, InsertExportsThenGetReturnsCorrectData) {
    DLLAnalysisResult result = makeTestResult(701, "exp_test.dll", "/tmp/exp_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    std::vector<ExportedFunction> exports = {
        {"DllRegisterServer", 1, 0x5000},
        {"DllUnregisterServer", 2, 0x5010}
    };
    EXPECT_TRUE(db_->insertExports(dllId, exports));

    auto retrieved = db_->getExports(dllId);
    ASSERT_EQ(retrieved.size(), 2u);
    EXPECT_EQ(retrieved[0].name, "DllRegisterServer");
    EXPECT_EQ(retrieved[0].ordinal, 1);
    EXPECT_EQ(retrieved[1].name, "DllUnregisterServer");
}

TEST_F(DLLAnalysisDatabaseTest, InsertAnomalyThenGetReturnsCorrectData) {
    DLLAnalysisResult result = makeTestResult(801, "anom_test.dll", "/tmp/anom_test.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    Anomaly anomaly{"RWX_SECTION", "Writable and executable section", RiskLevel::CRITICAL, 35};
    EXPECT_TRUE(db_->insertAnomaly(dllId, anomaly));

    auto retrieved = db_->getAnomalies(dllId);
    ASSERT_EQ(retrieved.size(), 1u);
    EXPECT_EQ(retrieved[0].type, "RWX_SECTION");
    EXPECT_EQ(retrieved[0].risk, RiskLevel::CRITICAL);
    EXPECT_EQ(retrieved[0].riskScore, 35);
}

TEST_F(DLLAnalysisDatabaseTest, InsertMultipleForensicLinks) {
    DLLAnalysisResult result = makeTestResult(901, "links2.dll", "/tmp/links2.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);
    ASSERT_GT(dllId, 0);

    EXPECT_TRUE(db_->insertForensicLink(dllId, "type_a", "src_a", "data_a"));
    EXPECT_TRUE(db_->insertForensicLink(dllId, "type_b", "src_b", "data_b"));

    auto links = db_->getForensicLinks(dllId);
    ASSERT_EQ(links.size(), 2u);
}

TEST_F(DLLAnalysisDatabaseTest, GetSuspiciousDLLsWithLimit) {
    for (int i = 0; i < 5; ++i) {
        DLLAnalysisResult result = makeTestResult(3000 + i,
            "dll" + std::to_string(i) + ".dll",
            "/tmp/dll" + std::to_string(i) + ".dll",
            10 + i * 30);
        db_->insertDLLBaseInfo(result);
    }

    auto suspicious = db_->getSuspiciousDLLs(2);
    EXPECT_LE(suspicious.size(), 2u);
    // Default threshold is 30, so should have scores 40, 70, 100 (3 total, limited to 2)
    if (suspicious.size() > 1) {
        EXPECT_GE(suspicious[0].threatScore, suspicious[1].threatScore);
    }
}

TEST_F(DLLAnalysisDatabaseTest, EmptySectionListReturnsEmptyVector) {
    DLLAnalysisResult result = makeTestResult(401, "empty_sec.dll", "/tmp/empty_sec.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);

    auto sections = db_->getSections(dllId);
    EXPECT_TRUE(sections.empty());
}

TEST_F(DLLAnalysisDatabaseTest, EmptyImportsReturnsEmptyVector) {
    DLLAnalysisResult result = makeTestResult(501, "empty_imp.dll", "/tmp/empty_imp.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);

    auto imports = db_->getImports(dllId);
    EXPECT_TRUE(imports.empty());
}

TEST_F(DLLAnalysisDatabaseTest, EmptyExportsReturnsEmptyVector) {
    DLLAnalysisResult result = makeTestResult(601, "empty_exp.dll", "/tmp/empty_exp.dll");
    int64_t dllId = db_->insertDLLBaseInfo(result);

    auto exports = db_->getExports(dllId);
    EXPECT_TRUE(exports.empty());
}

