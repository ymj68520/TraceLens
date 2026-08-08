#include "AndroidAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "PathManager/PathManager.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "LogicalDirExtractor.h"
#include "ZipArchiveExtractor.h"
#include "MiuiBackupExtractor.h"
#include "MiuiArtifactParsers.h"
#include "MiuiSecureTemp.h"

namespace fs = std::filesystem;

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

    std::cout << "Android data analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "ANDROID_ANALYSIS_COMPLETE", "Android data analysis completed for: " + imagePath_);
}
