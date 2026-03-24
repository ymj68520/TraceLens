#include "AndroidAnalyzer.h"
#include "AuditLog/AuditLog.h"

// AndroidAnalyzer Core Implementation

AndroidAnalyzer::AndroidAnalyzer() {
}

AndroidAnalyzer::AndroidAnalyzer(const std::string& imagePath, DatabaseManager* dbManager)
    : imagePath_(imagePath), dbManager_(dbManager) {
}

AndroidAnalyzer::~AndroidAnalyzer() {
}

bool AndroidAnalyzer::initialize() {
    fileExtractor_ = std::make_unique<FileExtractor>(imagePath_, dbManager_->getDbPath());
    if (!fileExtractor_->initialize()) {
        std::cerr << "Failed to initialize FileExtractor" << std::endl;
        AuditLog::instance().log("SYSTEM", "ANDROID_INIT_FAILED", "Failed to initialize Android analyzer for: " + imagePath_);
        return false;
    }

    // Initialize android analysis database
    std::string androidDbPath = outputDbPath_.empty() ? imagePath_ + "_android.db" : outputDbPath_;
    androidDb_ = std::make_unique<AndroidAnalysisDatabase>(androidDbPath);
    if (!androidDb_->initialize()) {
        std::cerr << "Failed to initialize AndroidAnalysisDatabase" << std::endl;
        return false;
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

    // Analyze WeChat
    extractAndParseDB("data/data/com.tencent.mm/MicroMsg/testuser/EnMicroMsg.db", "parseWeChat");

    // Analyze Chrome History
    extractAndParseDB("data/data/com.android.chrome/app_chrome/Default/History", "parseChromeHistory");

    // Analyze System Logs
    analyzeSystemLogs();

    std::cout << "Android data analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "ANDROID_ANALYSIS_COMPLETE", "Android data analysis completed for: " + imagePath_);
}
