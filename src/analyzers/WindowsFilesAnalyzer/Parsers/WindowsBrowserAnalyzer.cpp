// WindowsBrowserAnalyzer.cpp
// Dedicated browser data analysis implementation for Windows forensics
// This file provides the analyzeBrowserData() method for WindowsFilesAnalyzer

#include "WindowsFilesAnalyzer.h"
#include "WindowsBrowserParser.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <filesystem>

namespace fs = std::filesystem;

void WindowsFilesAnalyzer::analyzeBrowserData() {
    std::cout << "Analyzing Browser Data (Comprehensive)..." << std::endl;
    AuditLog::instance().log("SYSTEM", "BROWSER_ANALYSIS_START",
        "Starting comprehensive browser data analysis with detailed extraction");

    WindowsBrowserParser browserParser;
    browserParser.setExtractDirectory(extractDir_);

    int totalHistory = 0;
    int totalDownloads = 0;
    int totalBookmarks = 0;
    int totalCookies = 0;
    int totalLogins = 0;

    // ============================================================================
    // Chrome Browser Analysis
    // ============================================================================
    std::cout << "  Processing Google Chrome..." << std::endl;
    std::vector<FileRecord> chromeHistory = queryFilesByPattern(
        "%/AppData/Local/Google/Chrome/User Data/%/History");
    
    for (const auto& file : chromeHistory) {
        std::string profileName = BrowserHelpers::extractProfileName(file.path);
        std::string extractPath = getExtractPath("browser/chrome/" + std::to_string(file.inode) + "_History");
        
        if (extractFileToPath(file.inode, extractPath)) {
            if (browserParser.parseChrome(extractPath, profileName)) {
                std::cout << "    ✓ Parsed Chrome profile: " << profileName << std::endl;
            }
        }
    }

    // Extract Chrome Cookies
    std::vector<FileRecord> chromeCookies = queryFilesByPattern(
        "%/AppData/Local/Google/Chrome/User Data/%/Cookies");
    for (const auto& file : chromeCookies) {
        std::string profileName = BrowserHelpers::extractProfileName(file.path);
        std::string extractPath = getExtractPath("browser/chrome/" + std::to_string(file.inode) + "_Cookies");
        if (extractFileToPath(file.inode, extractPath)) {
            // Parser will handle cookies during parseProfile
        }
    }

    // Extract Chrome Bookmarks
    std::vector<FileRecord> chromeBookmarks = queryFilesByPattern(
        "%/AppData/Local/Google/Chrome/User Data/%/Bookmarks");
    for (const auto& file : chromeBookmarks) {
        std::string extractPath = getExtractPath("browser/chrome/" + std::to_string(file.inode) + "_Bookmarks");
        extractFileToPath(file.inode, extractPath);
        // Parser will handle bookmarks during parseProfile
    }

    // ============================================================================
    // Microsoft Edge Browser Analysis
    // ============================================================================
    std::cout << "  Processing Microsoft Edge..." << std::endl;
    std::vector<FileRecord> edgeHistory = queryFilesByPattern(
        "%/AppData/Local/Microsoft/Edge/User Data/%/History");
    
    for (const auto& file : edgeHistory) {
        std::string profileName = BrowserHelpers::extractProfileName(file.path);
        std::string extractPath = getExtractPath("browser/edge/" + std::to_string(file.inode) + "_History");
        
        if (extractFileToPath(file.inode, extractPath)) {
            if (browserParser.parseEdge(extractPath, profileName)) {
                std::cout << "    ✓ Parsed Edge profile: " << profileName << std::endl;
            }
        }
    }

    // Extract Edge Cookies
    std::vector<FileRecord> edgeCookies = queryFilesByPattern(
        "%/AppData/Local/Microsoft/Edge/User Data/%/Cookies");
    for (const auto& file : edgeCookies) {
        std::string extractPath = getExtractPath("browser/edge/" + std::to_string(file.inode) + "_Cookies");
        extractFileToPath(file.inode, extractPath);
    }

    // ============================================================================
    // Firefox Browser Analysis
    // ============================================================================
    std::cout << "  Processing Mozilla Firefox..." << std::endl;
    std::vector<FileRecord> firefoxPlaces = queryFilesByPattern(
        "%/AppData/Roaming/Mozilla/Firefox/Profiles/%/places.sqlite");
    
    for (const auto& file : firefoxPlaces) {
        std::string profileName = BrowserHelpers::extractProfileName(file.path);
        std::string extractPath = getExtractPath("browser/firefox/" + std::to_string(file.inode) + "_places.sqlite");
        
        if (extractFileToPath(file.inode, extractPath)) {
            if (browserParser.parseFirefox(extractPath, profileName)) {
                std::cout << "    ✓ Parsed Firefox profile: " << profileName << std::endl;
            }
        }
    }

    // Extract Firefox Cookies
    std::vector<FileRecord> firefoxCookies = queryFilesByPattern(
        "%/AppData/Roaming/Mozilla/Firefox/Profiles/%/cookies.sqlite");
    for (const auto& file : firefoxCookies) {
        std::string extractPath = getExtractPath("browser/firefox/" + std::to_string(file.inode) + "_cookies.sqlite");
        extractFileToPath(file.inode, extractPath);
    }

    // ============================================================================
    // Store All Parsed Data to Database (Using Detailed Tables)
    // ============================================================================
    std::cout << "  Storing browser data to database..." << std::endl;

    windowsDb_->beginTransaction();

    // Store browser history (detailed)
    if (windowsDb_->insertBrowserHistories(browserParser.getHistory())) {
        totalHistory = browserParser.getHistory().size();
    }

    // Store browser downloads (detailed)
    if (windowsDb_->insertBrowserDownloads(browserParser.getDownloads())) {
        totalDownloads = browserParser.getDownloads().size();
    }

    // Store browser bookmarks (detailed)
    if (windowsDb_->insertBrowserBookmarks(browserParser.getBookmarks())) {
        totalBookmarks = browserParser.getBookmarks().size();
    }

    // Store browser cookies (detailed)
    if (windowsDb_->insertBrowserCookies(browserParser.getCookies())) {
        totalCookies = browserParser.getCookies().size();
    }

    // Store browser logins (detailed)
    if (windowsDb_->insertBrowserLogins(browserParser.getLogins())) {
        totalLogins = browserParser.getLogins().size();
    }

    windowsDb_->commitTransaction();

    // ============================================================================
    // Summary Statistics
    // ============================================================================
    std::cout << "\n  Browser Analysis Summary:" << std::endl;
    std::cout << "    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" << std::endl;
    std::cout << "    📜 History entries:   " << totalHistory << std::endl;
    std::cout << "    📥 Download entries:  " << totalDownloads << std::endl;
    std::cout << "    🔖 Bookmark entries:  " << totalBookmarks << std::endl;
    std::cout << "    🍪 Cookie entries:    " << totalCookies << std::endl;
    std::cout << "    🔑 Login entries:     " << totalLogins << std::endl;
    std::cout << "    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" << std::endl;

    AuditLog::instance().log("SYSTEM", "BROWSER_ANALYSIS_COMPLETE",
        "Browser analysis completed successfully: " +
        std::to_string(totalHistory) + " history, " +
        std::to_string(totalDownloads) + " downloads, " +
        std::to_string(totalBookmarks) + " bookmarks, " +
        std::to_string(totalCookies) + " cookies, " +
        std::to_string(totalLogins) + " logins");
}
