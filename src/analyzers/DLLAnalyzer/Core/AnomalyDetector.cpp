// AnomalyDetector.cpp
// DLL异常检测器实现
// 基于PE文件特征的启发式规则检测

#include "AnomalyDetector.h"
#include <algorithm>
#include <cctype>
#include <format>

using namespace forensics::dll;

// ============================================================================
// 静态成员初始化
// ============================================================================

const std::unordered_set<std::string> AnomalyDetector::SYSTEM_DLLS = {
    "kernel32.dll", "user32.dll", "gdi32.dll", "advapi32.dll",
    "ntdll.dll", "kernelbase.dll", "ws2_32.dll", "wininet.dll",
    "ole32.dll", "oleaut32.dll", "shell32.dll", "shlwapi.dll"
};

const std::unordered_set<std::string> AnomalyDetector::INJECTION_FUNCTIONS = {
    "CreateRemoteThread", "WriteProcessMemory", "VirtualAllocEx",
    "SetWindowsHookEx", "CallNextHookEx", "GetAsyncKeyState",
    "OpenProcess", "ReadProcessMemory"
};

const std::unordered_set<std::string> AnomalyDetector::PRIVILEGE_ESCALATION_FUNCTIONS = {
    "AdjustTokenPrivileges", "SeDebugPrivilege", "LookupPrivilegeValue",
    "ImpersonateLoggedOnUser", "ImpersonateSelf"
};

const std::unordered_set<std::string> AnomalyDetector::ANTI_DEBUG_FUNCTIONS = {
    "IsDebuggerPresent", "CheckRemoteDebuggerPresent",
    "NtQueryInformationProcess", "OutputDebugString",
    "ZwSetInformationThread", "DebugActiveProcess"
};

const std::unordered_set<std::string> AnomalyDetector::PERSISTENCE_FUNCTIONS = {
    "RegCreateKeyEx", "RegSetValueEx", "CreateService",
    "StartService", "WinHttpOpen", "URLDownloadToFile"
};

const std::unordered_set<std::string> AnomalyDetector::PACKER_SIGNATURES = {
    "UPX0", "UPX1", "UPX!", "ASPack", "PECompact",
    ".themida", "VMProtect", ".vmp0", ".vmp1"
};

const std::unordered_set<std::string> AnomalyDetector::STANDARD_SECTION_NAMES = {
    // 标准PE节名
    ".text", ".code", ".data", ".rdata", ".bss", ".idata",
    ".edata", ".pdata", ".reloc", ".rsrc", ".tls", ".debug",
    // 常见节名
    "INIT", "fini", "CRT", "DATA", "text", "data",
    // 只读数据节
    ".rodata", ".const", ".idata", ".eh_frame",
    // 其他常见
    ".plt", ".got", ".got.plt", ".dynamic", ".dynsym"
};

// ============================================================================
// 构造 / 析构
// ============================================================================

AnomalyDetector::AnomalyDetector() = default;

AnomalyDetector::~AnomalyDetector() = default;

// ============================================================================
// 主入口：检测所有异常
// ============================================================================

std::vector<Anomaly> AnomalyDetector::detect(const DLLAnalysisResult& result) {
    std::vector<Anomaly> anomalies;
    int totalScore = 0;

    // 1. 检查高熵节
    Anomaly entropyAnomaly = checkHighEntropySections(result.peHeader.sections);
    if (entropyAnomaly.riskScore > 0) {
        anomalies.push_back(entropyAnomaly);
        totalScore += entropyAnomaly.riskScore;
    }

    // 2. 检查可疑导入
    Anomaly importAnomaly = checkSuspiciousImports(result.imports);
    if (importAnomaly.riskScore > 0) {
        anomalies.push_back(importAnomaly);
        totalScore += importAnomaly.riskScore;
    }

    // 3. 检查RWX权限
    Anomaly rwxAnomaly = checkWriteExecuteInText(result.peHeader.sections);
    if (rwxAnomaly.riskScore > 0) {
        anomalies.push_back(rwxAnomaly);
        totalScore += rwxAnomaly.riskScore;
    }

    // 4. 检查异常节名
    Anomaly sectionAnomaly = checkUnusualSectionNames(result.peHeader.sections);
    if (sectionAnomaly.riskScore > 0) {
        anomalies.push_back(sectionAnomaly);
        totalScore += sectionAnomaly.riskScore;
    }

    // 5. 检查入口点异常
    Anomaly entryAnomaly = checkEntryPointAnomaly(result.peHeader);
    if (entryAnomaly.riskScore > 0) {
        anomalies.push_back(entryAnomaly);
        totalScore += entryAnomaly.riskScore;
    }

    // 更新威胁评分（上限100）
    // 注意：这里不直接修改result，返回的anomalies包含总分信息
    // 实际调用方可以累加anomalies中的riskScore得到总分

    return anomalies;
}

// ============================================================================
// 检测规则实现
// ============================================================================

Anomaly AnomalyDetector::checkHighEntropySections(const std::vector<PESectionInfo>& sections) {
    for (const auto& section : sections) {
        // .text节高熵（>7.5）可能是加密/加壳
        if (section.name == ".text" && section.entropy > 7.5) {
            return Anomaly{
                "HIGH_ENTROPY_CODE",
                "Code section .text has high entropy: " + std::to_string(section.entropy),
                RiskLevel::HIGH,
                15
            };
        }
    }
    return {"NONE", "", RiskLevel::LOW, 0};
}

Anomaly AnomalyDetector::checkSuspiciousImports(const std::vector<ImportedDLL>& imports) {
    std::vector<std::string> suspiciousFuncs;

    for (const auto& importedDLL : imports) {
        for (const auto& func : importedDLL.functions) {
            if (INJECTION_FUNCTIONS.count(func) ||
                PRIVILEGE_ESCALATION_FUNCTIONS.count(func) ||
                ANTI_DEBUG_FUNCTIONS.count(func) ||
                PERSISTENCE_FUNCTIONS.count(func)) {
                suspiciousFuncs.push_back(func);
            }
        }
    }

    if (suspiciousFuncs.size() >= 3) {
        return Anomaly{
            "SUSPICIOUS_IMPORTS",
            "Found " + std::to_string(suspiciousFuncs.size()) + " suspicious functions",
            RiskLevel::HIGH,
            20
        };
    }

    return {"NONE", "", RiskLevel::LOW, 0};
}

Anomaly AnomalyDetector::checkWriteExecuteInText(const std::vector<PESectionInfo>& sections) {
    for (const auto& section : sections) {
        // .text节同时具有WRITE+EXECUTE权限
        if (section.name == ".text" && section.isWriteable && section.isExecutable) {
            return Anomaly{
                "RWX_CODE",
                "Code section .text has both WRITE and EXECUTE permissions",
                RiskLevel::HIGH,
                15
            };
        }
    }
    return {"NONE", "", RiskLevel::LOW, 0};
}

Anomaly AnomalyDetector::checkUnusualSectionNames(const std::vector<PESectionInfo>& sections) {
    std::vector<std::string> unusualSections;

    for (const auto& section : sections) {
        // 转换为小写进行检查（节名通常不区分大小写）
        std::string lowerName = section.name;
        std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(),
                      [](unsigned char c) { return std::tolower(c); });

        if (!STANDARD_SECTION_NAMES.count(lowerName)) {
            unusualSections.push_back(section.name);
        }
    }

    if (!unusualSections.empty()) {
        return Anomaly{
            "UNUSUAL_SECTION_NAMES",
            "Found " + std::to_string(unusualSections.size()) + " unusual section name(s)",
            RiskLevel::MEDIUM,
            5
        };
    }

    return {"NONE", "", RiskLevel::LOW, 0};
}

Anomaly AnomalyDetector::checkEntryPointAnomaly(const PEHeaderInfo& header) {
    if (!header.isValid || header.sections.empty()) {
        return {"NONE", "", RiskLevel::LOW, 0};
    }

    // 找到包含入口点的节
    uint32_t entryPoint = header.entryPointRVA;

    for (const auto& section : header.sections) {
        uint32_t sectionStart = section.virtualAddress;
        uint32_t sectionEnd = sectionStart + section.virtualSize;

        // 检查入口点是否在此节范围内
        if (entryPoint >= sectionStart && entryPoint < sectionEnd) {
            // 检查节名是否为标准代码节
            std::string lowerName = section.name;
            std::transform(lowerName.begin(), lowerName.end(), lowerName.begin(),
                          [](unsigned char c) { return std::tolower(c); });

            // 如果入口点在.data/.rdata/.bss等非代码节中，标记为异常
            if (lowerName == ".data" || lowerName == ".rdata" ||
                lowerName == ".bss" || lowerName == ".rodata" ||
                lowerName == ".idata" || lowerName == ".edata") {
                return Anomaly{
                    "ENTRY_POINT_IN_DATA",
                    std::format("Entry point 0x{:X} is in non-code section: {}", entryPoint, section.name),
                    RiskLevel::HIGH,
                    10
                };
            }

            // 入口点在合法代码节，无异常
            return {"NONE", "", RiskLevel::LOW, 0};
        }
    }

    // 入口点不在任何节中（可能是无效的PE）
    return Anomaly{
        "ENTRY_POINT_NOT_FOUND",
        std::format("Entry point RVA 0x{:X} not found in any section", entryPoint),
        RiskLevel::MEDIUM,
        5
    };
}
