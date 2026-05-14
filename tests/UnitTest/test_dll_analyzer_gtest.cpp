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
