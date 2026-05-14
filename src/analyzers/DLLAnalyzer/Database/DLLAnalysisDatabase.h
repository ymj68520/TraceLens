// DLLAnalysisDatabase.h
// 数据库操作接口

#pragma once
#ifndef DLL_ANALYSIS_DATABASE_H
#define DLL_ANALYSIS_DATABASE_H

#include <string>
#include <vector>
#include <optional>
#include <sqlite3.h>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

class DLLAnalysisDatabase {
public:
    explicit DLLAnalysisDatabase(const std::string& dbPath);
    ~DLLAnalysisDatabase();

    // 禁止拷贝
    DLLAnalysisDatabase(const DLLAnalysisDatabase&) = delete;
    DLLAnalysisDatabase& operator=(const DLLAnalysisDatabase&) = delete;

    // 初始化数据库
    bool initialize();

    // ========================================================================
    // DLL基础信息操作
    // ========================================================================

    // 插入新的DLL记录，返回自增ID
    int64_t insertDLLBaseInfo(const DLLAnalysisResult& result);

    // 更新DLL分析结果
    bool updateDLLAnalysis(int64_t dllId, const DLLAnalysisResult& result);

    // 更新威胁评分
    bool updateThreatScore(int64_t dllId, int score);

    // ========================================================================
    // 节表操作
    // ========================================================================

    bool insertSections(int64_t dllId, const std::vector<PESectionInfo>& sections);
    std::vector<PESectionInfo> getSections(int64_t dllId);

    // ========================================================================
    // 导入/导出操作
    // ========================================================================

    bool insertImports(int64_t dllId, const std::vector<ImportedDLL>& imports);
    bool insertExports(int64_t dllId, const std::vector<ExportedFunction>& exports);

    std::vector<ImportedDLL> getImports(int64_t dllId);
    std::vector<ExportedFunction> getExports(int64_t dllId);

    // ========================================================================
    // 异常检测操作
    // ========================================================================

    bool insertAnomaly(int64_t dllId, const Anomaly& anomaly);
    std::vector<Anomaly> getAnomalies(int64_t dllId);

    // ========================================================================
    // 依赖关系操作
    // ========================================================================

    bool insertDependency(int64_t parentId, int64_t childId, int depth);
    std::vector<std::pair<int64_t, int64_t>> getDependencies(int64_t parentId);

    // ========================================================================
    // 取证关联操作
    // ========================================================================

    bool insertForensicLink(int64_t dllId, const std::string& linkType,
                           const std::string& sourceId, const std::string& sourceData);
    std::vector<std::tuple<std::string, std::string, std::string>>
    getForensicLinks(int64_t dllId);

    // ========================================================================
    // 查询操作
    // ========================================================================

    std::optional<DLLAnalysisResult> getDLLByInode(int64_t inode);
    std::optional<DLLAnalysisResult> getDLLByPath(const std::string& path);
    std::optional<DLLAnalysisResult> getDLLById(int64_t dllId);

    std::vector<DLLAnalysisResult> getDLLsByThreatScore(int minScore);
    std::vector<DLLAnalysisResult> getSuspiciousDLLs(int limit = 100);
    std::vector<DLLAnalysisResult> getAllDLLs(int limit = 1000);

    // ========================================================================
    // 统计操作
    // ========================================================================

    size_t getDLLCount();
    size_t getSuspiciousCount();
    int getAverageThreatScore();

private:
    bool executeSQL(const char* sql, ...);
    bool createTables();
    bool createIndices();

    // 辅助方法：从row读取DLLAnalysisResult
    DLLAnalysisResult readDLLFromRow(sqlite3_stmt* stmt);

    // 工具方法
    static std::string machineTypeToString(MachineType type);
    static MachineType machineTypeFromString(const std::string& str);

    std::string dbPath_;
    sqlite3* db_;
};

} // namespace dll
} // namespace forensics

#endif // DLL_ANALYSIS_DATABASE_H
