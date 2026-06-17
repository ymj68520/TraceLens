// FileClassifier_SceneRules.cpp
// Scene-type detection and per-OS scene-rule scoring
// Part of FileClassifier implementation; methods belong to the FileClassifier
// class declared in FileClassifier.h. Split from FileClassifier.cpp.

#include "FileClassifier.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include "AuditLog/AuditLog.h"
#include "EncryptionUtils.h"
#include "ConfigManager/ConfigManager.h"
#include <iostream>
#include <sstream>
#include <iomanip>
#include <sqlite3.h>
#include <algorithm>
#include <cctype>

void FileClassifier::markSceneFiles() {
    // TODO: Implement in Task 3 - integrate scene marking into classifyFiles
    // This method will be called from classifyAndExtract() after classifyFiles()
}

void FileClassifier::setSceneType(SceneType scene) {
    sceneType_ = scene;
}

SceneType FileClassifier::getSceneType() const {
    return sceneType_;
}

std::string FileClassifier::getSceneTypeName(SceneType scene) const {
    switch (scene) {
        case SceneType::ANDROID: return "android";
        case SceneType::WINDOWS: return "windows";
        case SceneType::LINUX: return "linux";
        case SceneType::SERVER_CLOUD: return "server_cloud";
        default: return "";
    }
}

int FileClassifier::calculateScenePriority(const std::string& path, const std::string& filename, FileCategory category) {
    int priority = ScenePriority::IRRELEVANT;
    bool relevant = false;

    switch (sceneType_) {
        case SceneType::ANDROID:
            applyAndroidSceneRules(path, filename, priority, relevant);
            break;
        case SceneType::WINDOWS:
            applyWindowsSceneRules(path, filename, priority, relevant);
            break;
        case SceneType::LINUX:
            applyLinuxSceneRules(path, filename, priority, relevant);
            break;
        case SceneType::SERVER_CLOUD:
            applyServerCloudSceneRules(path, filename, priority, relevant);
            break;
        default:
            break;
    }

    return priority;
}

bool FileClassifier::isSceneRelevant(const std::string& path, const std::string& filename) {
    int priority = calculateScenePriority(path, filename, determineCategory(filename, path));
    return priority >= ScenePriority::MEDIUM;
}

void FileClassifier::applyAndroidSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Android critical system provider paths (check first for precise matching)
    static const std::vector<std::string> criticalAppPaths = {
        "com.android.providers.contacts",
        "com.android.providers.telephony"
    };

    for (const auto& appPath : criticalAppPaths) {
        if (path.find(appPath) != std::string::npos) {
            priority = ScenePriority::CRITICAL;
            relevant = true;
            return;
        }
    }

    // Android third-party application paths
    static const std::vector<std::string> appPaths = {
        "com.tencent.mm",
        "org.telegram.messenger",
        "com.whatsapp"
    };

    for (const auto& appPath : appPaths) {
        if (path.find(appPath) != std::string::npos) {
            priority = ScenePriority::HIGH;
            relevant = true;
            return;
        }
    }

    // Android critical paths (fallback for broader path matching)
    static const std::vector<std::pair<std::string, int>> criticalPaths = {
        {"/data/data/", ScenePriority::CRITICAL},
        {"/data/system/", ScenePriority::CRITICAL},
        {"/data/misc/", ScenePriority::HIGH},
        {"/system/build.prop", ScenePriority::HIGH},
        {"/data/app/", ScenePriority::HIGH},
        {"/data/user/", ScenePriority::HIGH}
    };

    for (const auto& [criticalPath, p] : criticalPaths) {
        if (path.find(criticalPath) != std::string::npos) {
            priority = p;
            relevant = (p >= ScenePriority::MEDIUM);
            return;
        }
    }
}

void FileClassifier::applyWindowsSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Windows critical paths
    static const std::vector<std::pair<std::string, int>> criticalPaths = {
        {"Windows/System32/config/", ScenePriority::CRITICAL},
        {"Windows/System32/winevt/", ScenePriority::CRITICAL},
        {"Windows/Prefetch/", ScenePriority::HIGH},
        {"$Recycle.Bin/", ScenePriority::HIGH}
    };

    for (const auto& [criticalPath, p] : criticalPaths) {
        if (path.find(criticalPath) != std::string::npos) {
            priority = p;
            relevant = (p >= ScenePriority::MEDIUM);
            return;
        }
    }

    // Check for user AppData paths (wildcard glob "Users/*/AppData/" cannot be
    // used with std::string::find() since '*' is treated as a literal character).
    // Instead, check that both "Users/" and "/AppData/" appear in the path.
    if (path.find("Users/") != std::string::npos &&
        path.find("/AppData/") != std::string::npos) {
        priority = ScenePriority::HIGH;
        relevant = true;
        return;
    }

    // Windows critical files
    static const std::vector<std::string> criticalFiles = {
        "SAM", "SYSTEM", "SOFTWARE", "SECURITY", "NTUSER.DAT"
    };

    for (const auto& file : criticalFiles) {
        if (filename == file) {
            priority = ScenePriority::CRITICAL;
            relevant = true;
            return;
        }
    }
}

void FileClassifier::applyLinuxSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Linux critical paths
    static const std::vector<std::pair<std::string, int>> criticalPaths = {
        {"/var/log/", ScenePriority::CRITICAL},
        {"/etc/", ScenePriority::CRITICAL},
        {"/home/", ScenePriority::HIGH},
        {"/root/", ScenePriority::HIGH},
        {"/var/spool/cron/", ScenePriority::CRITICAL},
        {"/var/lib/docker/", ScenePriority::HIGH}
    };

    for (const auto& [criticalPath, p] : criticalPaths) {
        if (path.find(criticalPath) != std::string::npos) {
            priority = p;
            relevant = (p >= ScenePriority::MEDIUM);
            return;
        }
    }

    // Linux critical files
    static const std::vector<std::string> criticalFiles = {
        "passwd", "shadow", "group", "sudoers", "crontab",
        "authorized_keys", "id_rsa", ".bash_history"
    };

    for (const auto& file : criticalFiles) {
        if (filename == file) {
            priority = ScenePriority::CRITICAL;
            relevant = true;
            return;
        }
    }
}

void FileClassifier::applyServerCloudSceneRules(const std::string& path, const std::string& filename, int& priority, bool& relevant) {
    // Inherit Linux rules
    applyLinuxSceneRules(path, filename, priority, relevant);

    // Cloud-specific paths
    static const std::vector<std::pair<std::string, int>> cloudPaths = {
        {"/var/log/nginx/", ScenePriority::CRITICAL},
        {"/var/log/apache2/", ScenePriority::CRITICAL},
        {"/var/lib/mysql/", ScenePriority::HIGH},
        {"/etc/docker/", ScenePriority::HIGH},
        {"/etc/kubernetes/", ScenePriority::HIGH}
    };

    for (const auto& [cloudPath, p] : cloudPaths) {
        if (path.find(cloudPath) != std::string::npos) {
            priority = std::max(priority, p);
            relevant = (priority >= ScenePriority::MEDIUM);
            return;
        }
    }
}

