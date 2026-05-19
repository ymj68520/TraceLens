// DependencyAnalyzer.cpp
// DLL依赖关系分析器实现

#include "analyzers/DLLAnalyzer/Core/DependencyAnalyzer.h"
#include "analyzers/DLLAnalyzer/Parsers/PEImportExportParser.h"
#include "analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h"
#include "analyzers/WindowsFilesAnalyzer/Common/WindowsDataTypes.h"
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

    // 如果没有关联的 Windows DB，返回空列表
    if (!windowsDb_) {
        return {};
    }

    std::vector<std::string> references;
    std::string targetDll = extractFileName(dllPath);

    // 查询所有 Prefetch 文件
    auto prefetchFiles = windowsDb_->queryPrefetchFiles("");

    for (const auto& prefetch : prefetchFiles) {
        // 检查 referencedFiles 中是否包含目标 DLL
        for (const auto& refFile : prefetch.referencedFiles) {
            if (extractFileName(refFile) == targetDll) {
                references.push_back("Prefetch:" + prefetch.executableName +
                                    " (Hash:" + prefetch.prefetchHash +
                                    ", Runs:" + std::to_string(prefetch.runCount) + ")");
                break; // 每个 Prefetch 只记录一次
            }
        }
    }

    return references;
}

std::vector<std::string> DependencyAnalyzer::getRegistryReferences(
    const std::string& dllPath) {

    // 如果没有关联的 Windows DB，返回空列表
    if (!windowsDb_) {
        return {};
    }

    std::vector<std::string> references;
    std::string targetDll = extractFileName(dllPath);
    std::string targetDllLower = targetDll;
    std::transform(targetDllLower.begin(), targetDllLower.end(),
                   targetDllLower.begin(), ::tolower);

    // 查询所有注册表值
    auto registryValues = windowsDb_->queryRegistryValues("");

    for (const auto& regValue : registryValues) {
        // 检查注册表值数据中是否包含目标 DLL 名称
        // 重点关注以下注册表位置：
        // - AppInit_DLLs
        // - KnownDLLs
        // - Shell Extensions
        // - Services ImagePath
        std::string valueDataLower = regValue.valueData;
        std::transform(valueDataLower.begin(), valueDataLower.end(),
                       valueDataLower.begin(), ::tolower);

        if (valueDataLower.find(targetDllLower) != std::string::npos) {
            references.push_back("Registry:" + regValue.keyPath + "\\" + regValue.valueName +
                                " (Type:" + regValue.valueType + ")");
        }
    }

    return references;
}

std::vector<std::string> DependencyAnalyzer::getEventLogReferences(
    const std::string& dllPath) {

    // 如果没有关联的 Windows DB，返回空列表
    if (!windowsDb_) {
        return {};
    }

    std::vector<std::string> references;
    std::string targetDll = extractFileName(dllPath);
    std::string targetDllLower = targetDll;
    std::transform(targetDllLower.begin(), targetDllLower.end(),
                   targetDllLower.begin(), ::tolower);

    // 查询事件日志中与 DLL 加载相关的事件
    // Event ID 7 (Image loaded) 是最相关的
    // 也查询其他可能包含 DLL 路径的事件
    auto eventLogs = windowsDb_->queryEventLogs("");

    for (const auto& event : eventLogs) {
        // 在事件消息中搜索 DLL 文件名
        std::string messageLower = event.message;
        std::transform(messageLower.begin(), messageLower.end(),
                       messageLower.begin(), ::tolower);

        if (messageLower.find(targetDllLower) != std::string::npos) {
            references.push_back("EventLog:" + event.logSource +
                                " (ID:" + std::to_string(event.eventId) +
                                ", Time:" + std::to_string(event.timestamp) + ")");
        }
    }

    return references;
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

    // 使用PEImportExportParser解析DLL的导入表
    PEImportExportParser parser(dllPath);
    if (!parser.isValid()) {
        return {};
    }

    std::vector<ImportedDLL> imports;
    if (!parser.parseImports(imports)) {
        return {};
    }

    // 提取导入的DLL名称
    std::vector<std::string> dependencies;
    dependencies.reserve(imports.size());

    for (const auto& importedDLL : imports) {
        dependencies.push_back(importedDLL.name);
    }

    return dependencies;
}

// ============================================================================
// Windows 取证数据库集成
// ============================================================================

void DependencyAnalyzer::setWindowsDatabase(const WindowsAnalysisDatabase* windowsDb) {
    windowsDb_ = windowsDb;
}

std::string DependencyAnalyzer::normalizePath(const std::string& path) {
    std::string normalized = path;
    std::transform(normalized.begin(), normalized.end(),
                   normalized.begin(), ::tolower);
    std::replace(normalized.begin(), normalized.end(), '\\', '/');
    return normalized;
}

std::string DependencyAnalyzer::extractFileName(const std::string& fullPath) {
    return std::filesystem::path(fullPath).filename().string();
}

} // namespace dll
} // namespace forensics
