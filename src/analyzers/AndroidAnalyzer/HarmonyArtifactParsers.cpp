// HarmonyArtifactParsers.cpp
// 鸿蒙备份的分析阶段入口。
//
// 解析规则在 MobileEvidenceHarmonyAdapter 中实现并产出统一取数包；本文件
// 只负责把包写进 android.db。两条链路（直接分析 / 先取数再分析）因此共用
// 同一份规则，不会各自漂移。

#include "HarmonyArtifactParsers.h"
#include "HarmonyBackupExtractor.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileEvidenceAnalysis.h"
#include "MobileEvidenceHarmonyAdapter.h"
#include "MobileEvidencePackage.h"
#include "MobileBackupSchema.h"

#include <sqlite3.h>

#include <iostream>
#include <stdexcept>

bool analyzeHarmonyBackup(HarmonyBackupExtractor& source, AndroidAnalysisDatabase& output,
                          const std::filesystem::path& temporaryRoot) {
    mobile_evidence::Package package;
    try {
        mobile_evidence::HarmonyAdapterOptions options;
        if (!mobile_evidence::buildPackageFromHarmony(source, temporaryRoot, options, package)) {
            return false;
        }
    } catch (const std::exception& e) {
        std::cerr << "Harmony extraction failed: " << e.what() << std::endl;
        throw;
    }

    if (!output.beginTransaction()) return false;
    try {
        // Re-running the same source replaces derived records; never accumulate
        // duplicates. The mobile_* schema must exist before the DELETE runs:
        // analysis creates it lazily, which would be too late here.
        if (sqlite3_exec(output.handle(), mobile_backup_schema::DDL,
                         nullptr, nullptr, nullptr) != SQLITE_OK) {
            throw std::runtime_error("HARMONY_SCHEMA_FAILED");
        }
        if (sqlite3_exec(output.handle(),
                         "DELETE FROM mobile_artifacts; DELETE FROM installed_apps; "
                         "DELETE FROM app_db_inventory; DELETE FROM android_source_coverage; "
                         "DELETE FROM android_source_provenance;",
                         nullptr, nullptr, nullptr) != SQLITE_OK) {
            throw std::runtime_error("HARMONY_RESULT_RESET_FAILED");
        }

        mobile_evidence::AnalysisOptions analysisOptions;
        analysisOptions.mirrorFiles = false;  // 鸿蒙无外部存储清单
        mobile_evidence::AnalysisResult result;
        if (!mobile_evidence::analyzePackage(package, output, analysisOptions, result)) {
            throw std::runtime_error("HARMONY_RESULT_WRITE_FAILED");
        }

        for (const auto& provenance : source.usedSourceProvenance()) {
            if (!output.insertSourceProvenance(provenance)) {
                throw std::runtime_error("provenance_write_failed");
            }
        }
        if (!output.commitTransaction()) throw std::runtime_error("harmony_commit_failed");
        return true;
    } catch (...) {
        output.rollbackTransaction();
        throw;
    }
}
