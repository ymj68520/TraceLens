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

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
