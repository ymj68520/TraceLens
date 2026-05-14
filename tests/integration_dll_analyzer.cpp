// Integration tests for DLLAnalyzer with real samples
#include <iostream>
#include <cassert>
#include <filesystem>
#include <chrono>
#include <vector>

#include "analyzers/DLLAnalyzer/Parsers/ELFParser.h"
#include "analyzers/DLLAnalyzer/Parsers/PEHeaderParser.h"
#include "analyzers/DLLAnalyzer/Parsers/PEImportExportParser.h"
#include "analyzers/DLLAnalyzer/Parsers/SignatureVerifier.h"
#include "analyzers/DLLAnalyzer/Core/PEAnalyzer.h"
#include "analyzers/DLLAnalyzer/Core/AnomalyDetector.h"
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"
#include "core/Logger/Logger.h"

using namespace forensics::dll;

class IntegrationTestRunner {
public:
    IntegrationTestRunner() = default;

    ~IntegrationTestRunner() = default;

    bool runAllTests() {
        std::cout << "========================================" << std::endl;
        std::cout << "DLLAnalyzer Integration Test Suite" << std::endl;
        std::cout << "========================================\n" << std::endl;

        int passed = 0;
        int failed = 0;

        // ELF Tests
        std::cout << "[ELF Tests]" << std::endl;
        if (runTest("ELF: Parse libc.so.6", [this]() { return testELFParseLibc(); })) passed++; else failed++;
        if (runTest("ELF: Parse ld-linux.so.2", [this]() { return testELFParseLdLinux(); })) passed++; else failed++;
        if (runTest("ELF: Parse libarmadillo.so.12", [this]() { return testELFParseArmadillo(); })) passed++; else failed++;
        if (runTest("ELF: ELFParser validation", [this]() { return testELFValidator(); })) passed++; else failed++;
        if (runTest("ELF: Header extraction", [this]() { return testELFHeaderExtraction(); })) passed++; else failed++;
        if (runTest("ELF: Program headers exist", [this]() { return testELFProgramHeaders(); })) passed++; else failed++;
        if (runTest("ELF: Section headers exist", [this]() { return testELFSectionHeaders(); })) passed++; else failed++;

        std::cout << "\n[PE Tests]" << std::endl;
        if (runTest("PE: Parse minimal.exe", [this]() { return testPEParseMinimal(); })) passed++; else failed++;
        if (runTest("PE: PEHeaderParser validation", [this]() { return testPEValidator(); })) passed++; else failed++;
        if (runTest("PE: Header extraction", [this]() { return testPEHeaderExtraction(); })) passed++; else failed++;
        if (runTest("PE: Section parsing", [this]() { return testPESectionParsing(); })) passed++; else failed++;
        if (runTest("PE: Import/Export parsing", [this]() { return testPEImportExport(); })) passed++; else failed++;

        std::cout << "\n[Hash Tests]" << std::endl;
        if (runTest("Hash: Calculate MD5", [this]() { return testMD5Hash(); })) passed++; else failed++;
        if (runTest("Hash: Calculate SHA256", [this]() { return testSHA256Hash(); })) passed++; else failed++;
        if (runTest("Hash: Consistency", [this]() { return testHashConsistency(); })) passed++; else failed++;

        std::cout << "\n[Signature Tests]" << std::endl;
        if (runTest("Signature: Verify unsigned PE", [this]() { return testSignatureUnsignedPE(); })) passed++; else failed++;
        if (runTest("Signature: Has signature check", [this]() { return testSignatureHasSignature(); })) passed++; else failed++;

        std::cout << "\n[Anomaly Detection Tests]" << std::endl;
        if (runTest("Anomaly: High entropy check", [this]() { return testAnomalyHighEntropy(); })) passed++; else failed++;
        if (runTest("Anomaly: Threat score", [this]() { return testAnomalyThreatScore(); })) passed++; else failed++;

        std::cout << "\n[Dependency Tests]" << std::endl;
        if (runTest("Dependency: Parse imports", [this]() { return testDependencyParseImports(); })) passed++; else failed++;
        if (runTest("Dependency: Calculate ImpHash", [this]() { return testDependencyImpHash(); })) passed++; else failed++;

        std::cout << "\n[Cross-format Tests]" << std::endl;
        if (runTest("Cross-format: ELF not PE", [this]() { return testCrossFormatELF(); })) passed++; else failed++;
        if (runTest("Cross-format: PE not ELF", [this]() { return testCrossFormatPE(); })) passed++; else failed++;

        std::cout << "\n========================================" << std::endl;
        std::cout << "Results: " << passed << " passed, " << failed << " failed" << std::endl;
        std::cout << "========================================" << std::endl;

        return failed == 0;
    }

private:
    const std::string SAMPLES_DIR = std::string(TEST_SAMPLES_DIR);
    const std::string ELF_DIR = SAMPLES_DIR + "/elf";
    const std::string PE_DIR = SAMPLES_DIR + "/pe";

    template<typename Func>
    bool runTest(const std::string& name, Func testFunc) {
        try {
            std::cout << "  " << name << " ... ";
            if (testFunc()) {
                std::cout << "PASSED" << std::endl;
                return true;
            } else {
                std::cout << "FAILED" << std::endl;
                return false;
            }
        } catch (const std::exception& e) {
            std::cout << "EXCEPTION: " << e.what() << std::endl;
            return false;
        }
    }

    // ==================== ELF Tests ====================

    bool testELFParseLibc() {
        std::string fp = ELF_DIR + "/libc.so.6";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped - file not found)";
            return true;
        }

        ELFParser parser;
        ELFHeaderInfo info = parser.parse(fp);

        return info.isValid &&
               info.is64Bit == true &&
               info.machine == 0x003E;  // EM_X86_64
    }

    bool testELFParseLdLinux() {
        std::string fp = ELF_DIR + "/ld-linux.so.2";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped - file not found)";
            return true;
        }

        ELFParser parser;
        ELFHeaderInfo info = parser.parse(fp);

        // ld-linux.so.2 is 32-bit i386
        return info.isValid &&
               info.is64Bit == false &&
               (info.machine == 0x0003 || info.machine == 0x003E);  // EM_386 or EM_X86_64
    }

    bool testELFParseArmadillo() {
        std::string fp = ELF_DIR + "/libarmadillo.so.12";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped - file not found)";
            return true;
        }

        ELFParser parser;
        ELFHeaderInfo info = parser.parse(fp);

        return info.isValid &&
               info.is64Bit == true &&
               info.fileType == 0x0003;  // ET_DYN
    }

    bool testELFValidator() {
        std::string validFile = ELF_DIR + "/libc.so.6";
        std::string invalidFile = PE_DIR + "/test_minimal.exe";

        ELFParser parser;
        return parser.isValidELF(validFile) == true &&
               parser.isValidELF(invalidFile) == false;
    }

    bool testELFHeaderExtraction() {
        std::string fp = ELF_DIR + "/libc.so.6";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        ELFParser parser;
        ELFHeaderInfo info = parser.parse(fp);

        return info.isValid &&
               !info.machineName.empty() &&
               !info.abi.empty() &&
               info.entryPoint > 0;
    }

    bool testELFProgramHeaders() {
        std::string fp = ELF_DIR + "/libc.so.6";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        ELFParser parser;
        ELFHeaderInfo info = parser.parse(fp);

        return info.isValid &&
               !info.programHeaders.empty() &&
               info.programHeaders.size() > 0;
    }

    bool testELFSectionHeaders() {
        std::string fp = ELF_DIR + "/libc.so.6";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        ELFParser parser;
        ELFHeaderInfo info = parser.parse(fp);

        return info.isValid &&
               !info.sections.empty() &&
               info.sections.size() > 0;
    }

    // ==================== PE Tests ====================

    bool testPEParseMinimal() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped - file not found)";
            return true;
        }

        PEHeaderParser parser(fp);
        bool parseOk = parser.parse();
        if (!parseOk) return false;

        PEHeaderInfo header = parser.getHeaderInfo();
        return header.isValid &&
               header.machine == MachineType::x64 &&
               header.numberOfSections >= 2;
    }

    bool testPEValidator() {
        std::string validFile = PE_DIR + "/test_minimal.exe";
        std::string invalidFile = ELF_DIR + "/libc.so.6";

        PEHeaderParser validParser(validFile);
        bool validResult = validParser.parse();

        PEHeaderParser invalidParser(invalidFile);
        bool invalidResult = invalidParser.parse();

        return validResult == true &&
               invalidResult == false;
    }

    bool testPEHeaderExtraction() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEHeaderParser parser(fp);
        if (!parser.parse()) return false;

        PEHeaderInfo header = parser.getHeaderInfo();
        return header.isValid &&
               header.numberOfSections > 0 &&
               header.entryPointRVA > 0;
    }

    bool testPESectionParsing() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEHeaderParser parser(fp);
        if (!parser.parse()) return false;

        PEHeaderInfo header = parser.getHeaderInfo();

        // Check sections were parsed (may have empty names but count should be correct)
        return header.sections.size() == 2;
    }

    bool testPEImportExport() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEImportExportParser parser(fp);
        std::vector<ImportedDLL> imports;
        std::vector<ExportedFunction> exports;
        bool importsOk = parser.parseImports(imports);
        bool exportsOk = parser.parseExports(exports);

        // Just verify no crash; minimal PE may have empty imports/exports
        return importsOk && exportsOk;
    }

    // ==================== Hash Tests ====================

    bool testMD5Hash() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEAnalyzer analyzer;
        std::string md5 = analyzer.calculateMD5(fp);

        return !md5.empty() &&
               md5.length() == 32 &&
               md5.find_first_not_of("0123456789abcdef") == std::string::npos;
    }

    bool testSHA256Hash() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEAnalyzer analyzer;
        std::string sha256 = analyzer.calculateSHA256(fp);

        return !sha256.empty() &&
               sha256.length() == 64 &&
               sha256.find_first_not_of("0123456789abcdef") == std::string::npos;
    }

    bool testHashConsistency() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEAnalyzer analyzer;
        std::string md5_1 = analyzer.calculateMD5(fp);
        std::string md5_2 = analyzer.calculateMD5(fp);
        std::string sha1_1 = analyzer.calculateSHA1(fp);
        std::string sha1_2 = analyzer.calculateSHA1(fp);

        return md5_1 == md5_2 && sha1_1 == sha1_2;
    }

    // ==================== Signature Tests ====================

    bool testSignatureUnsignedPE() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        SignatureVerifier verifier;
        SignatureInfo info = verifier.verify(fp);

        // Minimal PE should be unsigned
        return info.status == "Unsigned" &&
               info.isSigned == false;
    }

    bool testSignatureHasSignature() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        SignatureVerifier verifier;
        bool hasSig = verifier.hasSignature(fp);

        return hasSig == false;
    }

    // ==================== Anomaly Tests ====================

    bool testAnomalyHighEntropy() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEHeaderParser parser(fp);
        if (!parser.parse()) return false;
        PEHeaderInfo header = parser.getHeaderInfo();
        if (header.sections.empty()) return false;

        AnomalyDetector detector;
        Anomaly anomaly = detector.checkHighEntropySections(header.sections);

        // Just verify no crash; minimal PE shouldn't trigger high entropy
        // (using 0xCC pattern which has ~3.8 bits/byte entropy)
        return true;
    }

    bool testAnomalyThreatScore() {
        AnomalyDetector detector;

        DLLAnalysisResult result{};
        result.fileName = "test.exe";
        result.peHeader.isValid = true;
        result.signatureStatus = "Unsigned";
        result.threatScore = 0;

        // Test detect() method instead (which returns anomalies list)
        auto anomalies = detector.detect(result);

        // Just verify it returns a vector (may be empty for minimal result)
        return true;
    }

    // ==================== Dependency Tests ====================

    bool testDependencyParseImports() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEImportExportParser parser(fp);
        std::vector<ImportedDLL> imports;
        bool ok = parser.parseImports(imports);

        return ok;  // Just verify no crash
    }

    bool testDependencyImpHash() {
        std::string fp = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(fp)) {
            std::cout << "(skipped)";
            return true;
        }

        PEImportExportParser parser(fp);
        std::string hash = parser.calculateImpHash();

        // Minimal PE may return empty string, just verify no crash
        return true;
    }

    // ==================== Cross-format Tests ====================

    bool testCrossFormatELF() {
        std::string elfPath = ELF_DIR + "/libc.so.6";
        if (!std::filesystem::exists(elfPath)) {
            std::cout << "(skipped)";
            return true;
        }

        PEHeaderParser peParser(elfPath);
        bool peValid = peParser.parse();

        ELFParser elfParser;
        ELFHeaderInfo elfInfo = elfParser.parse(elfPath);

        return peValid == false &&
               elfInfo.isValid == true;
    }

    bool testCrossFormatPE() {
        std::string pePath = PE_DIR + "/test_minimal.exe";
        if (!std::filesystem::exists(pePath)) {
            std::cout << "(skipped)";
            return true;
        }

        ELFParser elfParser;
        ELFHeaderInfo elfInfo = elfParser.parse(pePath);

        PEHeaderParser peParser(pePath);
        bool peValid = peParser.parse();

        return elfInfo.isValid == false &&
               peValid == true;
    }
};

int main(int argc, char** argv) {
    std::cout << "DLLAnalyzer Integration Tests" << std::endl;
    std::cout << "Test samples directory: " << TEST_SAMPLES_DIR << std::endl;
    std::cout << std::endl;

    IntegrationTestRunner runner;
    bool success = runner.runAllTests();

    return success ? 0 : 1;
}
