#include "AndroidAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "PathManager/PathManager.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "LogicalDirExtractor.h"
#include "ZipArchiveExtractor.h"
#include "MiuiBackupExtractor.h"
#include "MiuiBackupManifest.h"
#include "MiuiArtifactParsers.h"
#include "MiuiSecureTemp.h"
#include "AndroidLLMAnalysisService.h"
#include "ConfigManager/ConfigManager.h"

namespace fs = std::filesystem;

// Detect whether a directory is actually a MIUI offline backup folder, even
// when the caller picked the generic "dir" source. A MIUI backup is identified
// by a descript.xml whose root tag is <MIUI-backup> plus at least one .bak
// file. Returns true and (optionally) parses the manifest when it is.
static bool dirLooksLikeMiuiBackup(const std::string& dirPath, BackupMeta* outManifest = nullptr) {
    std::error_code ec;
    if (!fs::is_directory(dirPath, ec)) return false;
    const fs::path manifestPath = fs::path(dirPath) / "descript.xml";
    if (!fs::exists(manifestPath, ec)) return false;

    BackupMeta manifest;
    if (!parseMiuiManifest(dirPath, manifest)) return false;

    // Require at least one .bak file referenced by the manifest to avoid
    // matching an unrelated descript.xml.
    bool hasBak = false;
    for (const auto& pkg : manifest.packages) {
        if (!pkg.bakFile.empty() && fs::exists(fs::path(dirPath) / pkg.bakFile, ec)) {
            hasBak = true;
            break;
        }
    }
    if (!hasBak) return false;

    if (outManifest) *outManifest = std::move(manifest);
    return true;
}

// AndroidAnalyzer Core Implementation

AndroidAnalyzer::AndroidAnalyzer() {
}

AndroidAnalyzer::AndroidAnalyzer(const std::string& imagePath, DatabaseManager* dbManager)
    : imagePath_(imagePath), dbManager_(dbManager) {
}

AndroidAnalyzer::~AndroidAnalyzer() {
    fileExtractor_.reset();
    if (!secureTemporaryRoot_.empty()) {
        std::error_code error;
        fs::remove_all(secureTemporaryRoot_, error);
    }
}

bool AndroidAnalyzer::initialize() {
    // Auto-promote a generic directory source to MIUI backup mode when the
    // folder is in fact a MIUI backup (descript.xml + .bak files). This keeps
    // analysis correct regardless of which source the user picked in the UI —
    // a MIUI backup folder selected as "Android 目录" still parses correctly.
    if (sourceMode_ == AndroidSourceMode::LogicalDir &&
        dirLooksLikeMiuiBackup(imagePath_, nullptr)) {
        std::cout << "[Android] Source directory is a MIUI backup; "
                     "auto-selecting miui-backup mode." << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_SOURCE_PROMOTED",
            "Logical dir auto-promoted to miui-backup: " + imagePath_);
        sourceMode_ = AndroidSourceMode::MiuiBackup;
    }

    // Pick a file-access backend based on the source mode. All nine call sites
    // in this module go through fileExtractor_->extractFileByPath(...), so the
    // backend is transparent to the parsing logic.
    switch (sourceMode_) {
        case AndroidSourceMode::MiuiBackup: {
            auto miui = std::make_unique<MiuiBackupExtractor>(imagePath_);
            if (!backupPassword_.empty()) miui->setBackupPassword(backupPassword_);
            fileExtractor_ = std::move(miui);
            break;
        }
        case AndroidSourceMode::LogicalDir:
            fileExtractor_ = std::make_unique<LogicalDirExtractor>(imagePath_);
            break;
        case AndroidSourceMode::Zip:
            fileExtractor_ = std::make_unique<ZipArchiveExtractor>(imagePath_);
            break;
        case AndroidSourceMode::TSK:
        default:
            // Legacy path: requires a populated _raw.db produced by the TSK
            // ImageAnalyzer stage.
            if (!dbManager_) {
                std::cerr << "TSK source mode requires a DatabaseManager (_raw.db)" << std::endl;
                return false;
            }
            fileExtractor_ = std::make_unique<FileExtractor>(imagePath_, dbManager_->getDbPath());
            break;
    }

    if (!fileExtractor_->initialize()) {
        std::cerr << "Failed to initialize file extractor (source mode "
                  << (sourceMode_ == AndroidSourceMode::TSK ? "TSK" :
                      sourceMode_ == AndroidSourceMode::LogicalDir ? "dir" :
                      sourceMode_ == AndroidSourceMode::Zip ? "zip" : "miui-backup")
                  << ")" << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_INIT_FAILED", "Failed to initialize Android analyzer for: " + imagePath_);
        return false;
    }

    if (sourceMode_ == AndroidSourceMode::MiuiBackup) {
        auto* miui = dynamic_cast<MiuiBackupExtractor*>(fileExtractor_.get());
        if (!miui || miui->temporaryRoot().empty()) return false;
        secureTemporaryRoot_ = miui->temporaryRoot().string();
    } else {
        const bool sourceIsDirectory = sourceMode_ == AndroidSourceMode::LogicalDir;
        fs::path evidenceRoot;
        fs::path root;
        if (!miui_secure_temp::evidenceRootForSource(imagePath_, sourceIsDirectory, evidenceRoot) ||
            !miui_secure_temp::createDirectory(evidenceRoot, "tracelens-android", root)) {
            std::cerr << "Failed to create evidence-disjoint Android temporary root" << std::endl;
            return false;
        }
        secureTemporaryRoot_ = root.string();
    }

    // Initialize android analysis database
    std::string androidDbPath = outputDbPath_.empty() ? imagePath_ + "_android.db" : outputDbPath_;
    androidDb_ = std::make_unique<AndroidAnalysisDatabase>(androidDbPath);
    if (!androidDb_->initialize()) {
        std::cerr << "Failed to initialize AndroidAnalysisDatabase" << std::endl;
        return false;
    }

    if (sourceMode_ == AndroidSourceMode::MiuiBackup) {
        if (auto* miui = dynamic_cast<MiuiBackupExtractor*>(fileExtractor_.get())) {
            if (!persistMiuiBackupAnalysis(*miui, *androidDb_)) {
                std::cerr << "Failed to persist MIUI backup analysis" << std::endl;
                return false;
            }
        }
    }

    AuditLog::instance().log("SYSTEM", "ANDROID_INIT", "Android analyzer initialized for: " + imagePath_);
    return true;
}

void AndroidAnalyzer::analyzeAndroidData() {
    std::cout << "Starting Android data analysis..." << std::endl;
    AuditLog::instance().log("SYSTEM", "ANDROID_ANALYSIS_START", "Starting Android data analysis: " + imagePath_);

    // Analyze system directory
    analyzeSystemDirectory(imagePath_ + "/system");

    // Analyze installed packages
    parseInstalledPackages("data/system/packages.xml");

    // Analyze Usage Stats
    parseUsageStats("data/system/usagestats/daily");

    // Analyze WiFi Config
    // Try modern XML first, then legacy conf
    // We try to extract both, parseWifiConfig handles extraction failure gracefully
    parseWifiConfig("data/misc/wifi/WifiConfigStore.xml") ||
    parseWifiConfig("data/misc/wifi/wpa_supplicant.conf");

    // Analyze SMS/MMS
    extractAndParseDB("data/data/com.android.providers.telephony/databases/mmssms.db", "parseSMS");

    // Analyze Contacts
    extractAndParseDB("data/data/com.android.providers.contacts/databases/contacts2.db", "parseContacts");

    // Analyze Call Logs
    extractAndParseDB("data/data/com.android.providers.contacts/databases/calllog.db", "parseCallLog");

    // Analyze WhatsApp
    extractAndParseDB("data/data/com.whatsapp/databases/msgstore.db", "parseWhatsApp");

    // Analyze Telegram
    extractAndParseDB("data/data/org.telegram.messenger/files/cache4.db", "parseTelegram");

    // Analyze WeChat (enhanced parsing with decryption support)
    if (sourceMode_ == AndroidSourceMode::MiuiBackup) {
        auto* miui = dynamic_cast<MiuiBackupExtractor*>(fileExtractor_.get());
        std::vector<std::string> wechatMembers;
        std::unordered_set<std::string> allMembers;
        if (miui) {
            miui->enumerateEntryDetails([&](const std::string& memberName, const std::string&,
                                             const TarEntry& entry) {
                allMembers.insert(memberName);
                if (!entry.isRegularFile() || !isMiuiWeChatDatabaseMember(memberName)) {
                    return;
                }
                wechatMembers.push_back(memberName);
            });
        }
        std::sort(wechatMembers.begin(), wechatMembers.end());
        if (wechatMembers.empty()) {
            std::cout << "WeChat database not present in MIUI backup" << std::endl;
        }
        for (const std::string& memberName : wechatMembers) {
            const std::string tempPath = makeAnalysisTempPath(memberName);
            std::vector<std::string> stagedPaths;
            bool staged = miui && miui->extractTarMember(memberName, tempPath);
            if (staged) {
                stagedPaths.push_back(tempPath);
                for (const char* suffix : {"-wal", "-shm", "-journal"}) {
                    const std::string sidecar = memberName + suffix;
                    if (allMembers.find(sidecar) == allMembers.end()) continue;
                    const std::string sidecarPath = tempPath + suffix;
                    if (miui->extractTarMember(sidecar, sidecarPath)) {
                        stagedPaths.push_back(sidecarPath);
                    }
                }
                parseWeChatEnhanced(tempPath, wechatPassword_);
            } else {
                std::cout << "Failed to extract WeChat database member: " << memberName << std::endl;
            }
            for (const std::string& path : stagedPaths) std::filesystem::remove(path);
        }
    } else {
        const std::string wechatDbPath = "data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db";
        const std::string tempPath = makeAnalysisTempPath(wechatDbPath);
        std::vector<std::string> stagedPaths;
        if (stageSqliteBundle(wechatDbPath, tempPath, stagedPaths)) {
            parseWeChatEnhanced(tempPath, wechatPassword_);
        } else {
            std::cout << "Failed to extract WeChat database: " << wechatDbPath << std::endl;
        }
        for (const std::string& path : stagedPaths) {
            std::filesystem::remove(path);
        }
    }

    // Analyze Chrome History
    extractAndParseDB("data/data/com.android.chrome/app_chrome/Default/History", "parseChromeHistory");

    // Analyze System Logs
    analyzeSystemLogs();

    // ---- Logical-extraction artifacts (Phase 2) ----
    // These are surfaced from app-specific files that the generic TSK pipeline
    // does not target: per-app Android IDs, plaintext note-taking app DBs, and
    // an inventory of SQLCipher-encrypted app DBs with key hints.
    analyzeDeviceIdentifiers();
    analyzeAppNotes();
    analyzeEncryptedAppDatabases();

    // Phase 3: AI-powered LLM analysis of all Android artifacts. Mirrors the
    // final phase of LinuxFilesAnalyzer / WindowsFilesAnalyzer. Auto-skipped
    // when no LLM endpoint is configured or skipAI_ is set.
    analyzeWithLLM();

    std::cout << "Android data analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "ANDROID_ANALYSIS_COMPLETE", "Android data analysis completed for: " + imagePath_);
}

void AndroidAnalyzer::analyzeWithLLM() {
    // Skip condition 1: user explicitly requested --no-ai.
    if (skipAI_) {
        std::cout << "AI analysis skipped (--no-ai)." << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_LLM_SKIPPED", "AI analysis skipped via --no-ai flag");
        return;
    }

    // Skip condition 2: no LLM endpoint configured → auto-skip. The local LLM
    // servers (LM Studio / Ollama / vLLM) the C++ LLMClient targets do not
    // require an API key (no Authorization header is sent), so the gate is the
    // base URL rather than the key. This keeps Android consistent with the
    // Linux/Windows analyzers' gate after their key-based check was relaxed.
    try {
        auto& configManager = forensics::ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }
        if (configManager.getTextBaseUrl().empty() && configManager.getLLMBaseUrl().empty()) {
            std::cout << "AI analysis skipped (no LLM_BASE_URL configured). "
                      << "Structured analysis results in android tables are unaffected." << std::endl;
            AuditLog::instance().log("SYSTEM", "ANDROID_LLM_SKIPPED",
                "No LLM_BASE_URL configured, skipping LLM analysis");
            return;
        }
    } catch (const std::exception& e) {
        std::cout << "AI analysis skipped (config read failed: " << e.what() << ")." << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_LLM_SKIPPED",
            "Config read failed, skipping LLM analysis: " + std::string(e.what()));
        return;
    }

    if (outputDbPath_.empty()) {
        std::cerr << "Warning: Cannot run Android LLM analysis, output database path is empty" << std::endl;
        return;
    }

    try {
        std::cout << "Running AI analysis on Android artifacts..." << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_LLM_ANALYSIS_START",
            "Starting LLM analysis for Android artifacts: " + imagePath_);

        forensics::AndroidLLMAnalysisService llmService;
        if (!llmService.initialize()) {
            std::cerr << "Warning: Failed to initialize Android LLM analysis service" << std::endl;
            AuditLog::instance().log("SYSTEM", "ANDROID_LLM_INIT_FAILED",
                "Failed to initialize LLM service for: " + imagePath_);
            return;
        }

        forensics::AndroidLLMAnalysisService::AnalysisOptions options;
        options.maxArtifacts = 1000;
        options.includeMessages = true;
        options.includeContacts = true;
        options.includeMiui = true;
        options.includeWechatEvidence = true;
        options.includeSystem = true;

        auto progressCallback = [](const std::string& artifactType, int current, int total, const std::string& details) {
            std::cout << "  [" << artifactType << "] " << current << "/" << total << " - " << details << std::endl;
        };

        int analyzed = llmService.analyzeAndroidArtifacts(outputDbPath_, options, progressCallback);
        std::cout << "AI analysis completed for " << analyzed << " Android artifacts." << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_LLM_ANALYSIS_COMPLETE",
            "LLM analysis completed for " + std::to_string(analyzed) + " artifacts from: " + imagePath_);

    } catch (const std::exception& e) {
        std::cerr << "Error during Android LLM analysis: " << e.what() << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_LLM_ANALYSIS_ERROR",
            "LLM analysis error for " + imagePath_ + ": " + e.what());
    }
}
