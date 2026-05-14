// DependencyAnalyzer.cpp
// DLL依赖关系分析器实现

#include "analyzers/DLLAnalyzer/Core/DependencyAnalyzer.h"
#include <algorithm>
#include <cctype>
#include <filesystem>
#include <functional>

namespace forensics {
namespace dll {

// ============================================================================
// 静态常量初始化
// ============================================================================

const std::unordered_set<std::string> DependencyAnalyzer::KNOWN_SYSTEM_DLLS = {
    // 核心系统DLL
    "kernel32.dll", "ntdll.dll", "user32.dll", "gdi32.dll",
    "advapi32.dll", "shell32.dll", "shlwapi.dll", "comdlg32.dll",
    "ws2_32.dll", "wsock32.dll", "winmm.dll", "version.dll",

    // 安全相关
    "crypt32.dll", "secur32.dll", "schannel.dll", "wincrypt.dll",

    // 其他常见系统DLL
    "ole32.dll", "oleaut32.dll", "uuid.dll", "combase.dll",
    "msvcrt.dll", "msvcp140.dll", "vcruntime140.dll",

    // 低级Windows API
    "userenv.dll", "profapi.dll", "setupapi.dll", "cfgmgr32.dll",
    "devobj.dll", "ntdllp.dll",

    // 其他
    "rpcrt4.dll", "rpcns4.dll", "samlib.dll", "netapi32.dll",
    "iphlpapi.dll", "winhttp.dll", "wininet.dll", "urlmon.dll"
};

const std::vector<std::string> DependencyAnalyzer::SYSTEM_PATHS = {
    "C:\\Windows\\System32\\",
    "C:\\Windows\\SysWOW64\\",
    "C:\\Windows\\WinSxS\\",
    "C:\\Windows\\assembly\\",
    "C:\\Windows\\Microsoft.NET\\"
};

const std::vector<std::string> DependencyAnalyzer::SUSPICIOUS_PATHS = {
    "C:\\Temp\\",
    "C:\\Windows\\Temp\\",
    "C:\\Users\\Public\\",
    "C:\\AppData\\",
    "C:\\Users\\",
    "C:\\Documents and Settings\\",
    "C:\\RECYCLER\\",
    "C:\\$Recycle.Bin\\"
};

// ============================================================================
// 构造函数和析构函数
// ============================================================================

DependencyAnalyzer::DependencyAnalyzer() = default;

DependencyAnalyzer::~DependencyAnalyzer() = default;

// ============================================================================
// 公有方法
// ============================================================================

DependencyAnalyzer::DependencyNode DependencyAnalyzer::buildDependencyTree(
    const std::string& dllPath,
    int maxDepth) {

    std::unordered_set<std::string> visited;
    return buildDependencyTreeRecursive(dllPath, maxDepth, 0, visited);
}

std::vector<std::string> DependencyAnalyzer::getRecursiveDependencies(
    const std::string& dllPath) {

    std::unordered_set<std::string> uniqueSet;
    std::vector<std::string> result;

    // 使用getAllDependencies获取去重集合，然后转为列表
    auto allDeps = getAllDependencies(dllPath);
    result.assign(allDeps.begin(), allDeps.end());

    return result;
}

std::unordered_set<std::string> DependencyAnalyzer::getAllDependencies(
    const std::string& dllPath) {

    std::unordered_set<std::string> visited;
    std::unordered_set<std::string> allDeps;

    // 递归收集所有依赖
    std::function<void(const std::string&, int)> collectDeps =
        [&](const std::string& currentDll, int depth) {
            if (depth <= 0 || visited.count(currentDll)) {
                return;
            }

            visited.insert(currentDll);
            auto directDeps = getDirectDependencies(currentDll);

            for (const auto& dep : directDeps) {
                if (!isSystemDLL(dep)) { // 排除系统DLL以避免无限递归
                    allDeps.insert(dep);
                    collectDeps(dep, depth - 1);
                }
            }
        };

    // 从depth=5开始收集（避免过深）
    collectDeps(dllPath, 5);

    return allDeps;
}

std::vector<std::string> DependencyAnalyzer::getPrefetchReferences(
    const std::string& dllPath) {

    // TODO: 与Prefetch分析器集成
    // 当前返回空列表（占位实现）
    (void)dllPath;
    return {};
}

std::vector<std::string> DependencyAnalyzer::getRegistryReferences(
    const std::string& dllPath) {

    // TODO: 与注册表分析器集成
    // 当前返回空列表（占位实现）
    (void)dllPath;
    return {};
}

std::vector<std::string> DependencyAnalyzer::getEventLogReferences(
    const std::string& dllPath) {

    // TODO: 与事件日志分析器集成
    // 当前返回空列表（占位实现）
    (void)dllPath;
    return {};
}

// ============================================================================
// 私有辅助方法
// ============================================================================

bool DependencyAnalyzer::isSystemDLL(const std::string& dllName) const {
    // 转换为小写进行比较
    std::string lowerName = dllName;
    std::transform(lowerName.begin(), lowerName.end(),
                   lowerName.begin(), ::tolower);

    return KNOWN_SYSTEM_DLLS.count(lowerName) > 0;
}

bool DependencyAnalyzer::isSuspiciousPath(const std::string& dllPath) const {
    std::string lowerPath = dllPath;
    std::transform(lowerPath.begin(), lowerPath.end(),
                   lowerPath.begin(), ::tolower);

    // 统一路径分隔符（将反斜杠替换为正斜杠）
    std::replace(lowerPath.begin(), lowerPath.end(), '\\', '/');

    for (const auto& suspiciousPath : SUSPICIOUS_PATHS) {
        // 标准化可疑路径（小写化 + 统一分隔符）
        std::string normalizedSuspicious = suspiciousPath;
        std::transform(normalizedSuspicious.begin(), normalizedSuspicious.end(),
                      normalizedSuspicious.begin(), ::tolower);
        std::replace(normalizedSuspicious.begin(), normalizedSuspicious.end(), '\\', '/');

        if (lowerPath.find(normalizedSuspicious) == 0) {
            return true;
        }
    }

    return false;
}

bool DependencyAnalyzer::checkCircularDependency(
    const std::string& dllPath,
    const std::unordered_set<std::string>& visited) const {

    std::string lowerPath = dllPath;
    std::transform(lowerPath.begin(), lowerPath.end(),
                   lowerPath.begin(), ::tolower);

    return visited.count(lowerPath) > 0;
}

DependencyAnalyzer::DependencyNode DependencyAnalyzer::buildDependencyTreeRecursive(
    const std::string& dllPath,
    int maxDepth,
    int currentDepth,
    std::unordered_set<std::string>& visited) {

    DependencyNode node;

    // 提取DLL名称
    node.dllPath = dllPath;
    node.dllName = std::filesystem::path(dllPath).filename().string();
    node.depth = currentDepth;
    node.isSystem = isSystemDLL(node.dllName);
    node.isSuspicious = isSuspiciousPath(dllPath);

    // 达到最大深度，停止递归
    if (currentDepth >= maxDepth) {
        return node;
    }

    // 检查循环依赖
    if (checkCircularDependency(dllPath, visited)) {
        return node;
    }

    // 标记为已访问
    visited.insert(dllPath);

    // 获取直接依赖
    auto dependencies = getDirectDependencies(dllPath);

    // 递归构建子节点
    for (const auto& dep : dependencies) {
        // 避免递归系统DLL
        if (isSystemDLL(dep)) {
            continue;
        }

        // 检查循环
        if (checkCircularDependency(dep, visited)) {
            continue;
        }

        // 递归构建
        auto childNode = buildDependencyTreeRecursive(dep, maxDepth, currentDepth + 1, visited);
        node.children.push_back(childNode);
    }

    return node;
}

std::vector<std::string> DependencyAnalyzer::getDirectDependencies(
    const std::string& dllPath) const {

    // TODO: 实际解析DLL的导入表
    // 当前返回空列表（占位实现）
    // 实际实现应该：
    // 1. 使用PEHeaderParser或PEImportExportParser解析DLL
    // 2. 提取导入表
    // 3. 返回导入的DLL名称列表

    (void)dllPath;
    return {};
}

} // namespace dll
} // namespace forensics
