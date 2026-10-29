// MobileEvidenceAnalysis.h
// 统一取数包 → AndroidAnalysisDatabase（android.db）。
//
// 这是"分析阶段"的唯一入口：只读统一包，不感知 MIUI / Harmony / iOS 等
// 具体来源。新增来源只要产出同一种包，即可复用本分析链路。

#pragma once
#ifndef MOBILE_EVIDENCE_ANALYSIS_H
#define MOBILE_EVIDENCE_ANALYSIS_H

#include <string>
#include <vector>

#include "MobileEvidencePackage.h"

class AndroidAnalysisDatabase;

namespace mobile_evidence {

struct AnalysisOptions {
    // 是否把 coverage 表原样转写到 android_source_coverage，便于既有 UI 展示。
    bool mirrorCoverage = true;
    // 是否写入文件清单（媒体/文档/数据库）到 miui_external_files 等表。
    bool mirrorFiles = true;
};

struct AnalysisResult {
    std::uint64_t contacts = 0;
    std::uint64_t callLogs = 0;
    std::uint64_t sms = 0;
    std::uint64_t notes = 0;
    std::uint64_t installedApps = 0;
    std::uint64_t mobileArtifacts = 0;
    std::uint64_t databaseTables = 0;
    std::uint64_t wifiNetworks = 0;
    std::uint64_t deviceIdentifiers = 0;
    std::uint64_t otherRecords = 0;
    std::uint64_t files = 0;
    std::uint64_t coverageEntries = 0;
};

// 读取统一包并写入分析库。返回 false 表示包无法打开或写库失败。
bool analyzePackage(const Reader& reader, AndroidAnalysisDatabase& database,
                    const AnalysisOptions& options, AnalysisResult& result);

// 直接分析内存中的包。适配器在"取数+分析合一"路径下使用，避免无谓的落盘。
bool analyzePackage(const Package& package, AndroidAnalysisDatabase& database,
                    const AnalysisOptions& options, AnalysisResult& result);

// 便捷重载：从路径打开包再分析。
bool analyzePackage(const std::string& packagePath, AndroidAnalysisDatabase& database,
                    const AnalysisOptions& options, AnalysisResult& result);

}  // namespace mobile_evidence

#endif  // MOBILE_EVIDENCE_ANALYSIS_H
