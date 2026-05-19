// DependencyAnalyzer.h
// DLL依赖关系分析器
// 用于构建DLL依赖树、关联取证数据、识别DLL劫持

#pragma once
#ifndef DEPENDENCY_ANALYZER_H
#define DEPENDENCY_ANALYZER_H

#include <string>
#include <vector>
#include <unordered_set>
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"
#include "analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h"

namespace forensics {
namespace dll {

/**
 * @brief DLL依赖分析器
 *
 * 职责：
 *   - 递归构建DLL依赖树
 *   - 关联Prefetch、注册表等取证数据
 *   - 识别DLL劫持和异常加载
 *   - 检测循环依赖
 */
class DependencyAnalyzer {
public:
    /**
     * @brief 依赖树节点
     */
    struct DependencyNode {
        std::string dllPath{""};              // DLL完整路径
        std::string dllName{""};              // DLL文件名
        int depth{0};                        // 在树中的深度（0=根节点）
        bool isSystem{false};                    // 是否为系统DLL
        bool isSuspicious{false};                // 是否为可疑DLL（路径或名称异常）
        std::vector<std::string> loadSources; // 加载来源（Prefetch/Registry/EventLog）
        std::vector<DependencyNode> children; // 子依赖
    };

    DependencyAnalyzer();
    ~DependencyAnalyzer();

    // 禁止拷贝
    DependencyAnalyzer(const DependencyAnalyzer&) = delete;
    DependencyAnalyzer& operator=(const DependencyAnalyzer&) = delete;

    /**
     * @brief 构建DLL依赖树
     * @param dllPath 起始DLL路径
     * @param maxDepth 最大递归深度（默认5）
     * @return 依赖树根节点
     */
    DependencyNode buildDependencyTree(const std::string& dllPath,
                                       int maxDepth = 5);

    /**
     * @brief 获取递归依赖列表（按顺序）
     * @param dllPath 起始DLL路径
     * @return 依赖DLL路径列表（可能包含重复）
     */
    std::vector<std::string> getRecursiveDependencies(const std::string& dllPath);

    /**
     * @brief 获取所有唯一依赖（去重集合）
     * @param dllPath 起始DLL路径
     * @return 不重复的依赖DLL路径集合
     */
    std::unordered_set<std::string> getAllDependencies(const std::string& dllPath);

    // =========================================================================
    // 取证关联方法
    // =========================================================================

    /**
     * @brief 获取Prefetch文件中引用的DLL列表
     * @param dllPath DLL路径
     * @return Prefetch引用列表
     */
    std::vector<std::string> getPrefetchReferences(const std::string& dllPath);

    /**
     * @brief 获取注册表中引用的DLL列表
     * @param dllPath DLL路径
     * @return 注册表引用列表
     */
    std::vector<std::string> getRegistryReferences(const std::string& dllPath);

    /**
     * @brief 获取事件日志中引用的DLL列表
     * @param dllPath DLL路径
     * @return 事件日志引用列表
     */
    std::vector<std::string> getEventLogReferences(const std::string& dllPath);

    // =========================================================================
    // Windows 取证数据库集成
    // =========================================================================

    /**
     * @brief 设置 Windows 取证数据库（只读）
     * @param windowsDb Windows 取证数据库指针
     */
    void setWindowsDatabase(const WindowsAnalysisDatabase* windowsDb);

    // =========================================================================
    // 测试辅助方法（公开以便单元测试）
    // =========================================================================

    /**
     * @brief 检查是否为已知系统DLL
     * @param dllName DLL文件名（不区分大小写）
     * @return true如果是系统DLL
     */
    bool isSystemDLL(const std::string& dllName) const;

    /**
     * @brief 检查路径是否可疑
     * @param dllPath DLL完整路径
     * @return true如果路径可疑（Temp、临时目录、用户目录等）
     */
    bool isSuspiciousPath(const std::string& dllPath) const;

    /**
     * @brief 检查是否存在循环依赖
     * @param dllPath 当前DLL路径
     * @param visited 已访问的DLL集合
     * @return true如果存在循环依赖
     */
    bool checkCircularDependency(const std::string& dllPath,
                                  const std::unordered_set<std::string>& visited) const;

    /**
     * @brief 规范化路径用于匹配（小写化 + 统一分隔符）
     * @param path 原始路径
     * @return 规范化后的路径
     */
    static std::string normalizePath(const std::string& path);

    /**
     * @brief 从路径提取文件名
     * @param fullPath 完整路径
     * @return 文件名（小写）
     */
    static std::string extractFileName(const std::string& fullPath);

private:

    /**
     * @brief 递归构建依赖树（内部方法）
     * @param dllPath 当前DLL路径
     * @param maxDepth 最大深度
     * @param currentDepth 当前深度
     * @param visited 已访问集合（用于循环检测）
     * @return 依赖树节点
     */
    DependencyNode buildDependencyTreeRecursive(const std::string& dllPath,
                                                int maxDepth,
                                                int currentDepth,
                                                std::unordered_set<std::string>& visited);

    /**
     * @brief 获取DLL的直接依赖（解析导入表）
     * @param dllPath DLL路径
     * @return 直接依赖的DLL名称列表
     */
    std::vector<std::string> getDirectDependencies(const std::string& dllPath) const;

    // 已知系统DLL白名单
    static const std::unordered_set<std::string> KNOWN_SYSTEM_DLLS;

    // 系统目录路径
    static const std::vector<std::string> SYSTEM_PATHS;

    // 可疑目录路径
    static const std::vector<std::string> SUSPICIOUS_PATHS;

    // Windows 取证数据库（只读，用于取证关联）
    const WindowsAnalysisDatabase* windowsDb_{nullptr};
};

} // namespace dll
} // namespace forensics

#endif // DEPENDENCY_ANALYZER_H
