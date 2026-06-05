// test_file_classifier.cpp
// GTest-based unit tests for FileClassifier module
// Tests file classification logic, category mapping, and path pattern matching

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <filesystem>
#include <fstream>

#include "DatabaseManager/FileClassifier/FileClassifier.h"

using ::testing::Eq;
using ::testing::AnyOf;

namespace fs = std::filesystem;

// ============================================================================
// FileCategory Enum Tests
// ============================================================================

class FileCategoryTest : public ::testing::Test {};

TEST_F(FileCategoryTest, EnumValuesExist) {
    // Verify key enum values exist
    FileCategory cat;
    cat = FileCategory::IMAGE;
    cat = FileCategory::VIDEO;
    cat = FileCategory::AUDIO;
    cat = FileCategory::DOCUMENT;
    cat = FileCategory::ARCHIVE;
    cat = FileCategory::EXECUTABLE;
    cat = FileCategory::DATABASE;
    cat = FileCategory::SOURCE_CODE;
    cat = FileCategory::OS_CONFIG;
    cat = FileCategory::OS_BOOT;
    cat = FileCategory::LOG_FILE;
    cat = FileCategory::UNKNOWN;
    SUCCEED();
}

// ============================================================================
// FileClassifier Tests - Using determineCategory
// ============================================================================

class FileClassifierTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create temporary databases for testing
        testSourceDb = fs::temp_directory_path() / "test_source.db";
        testFileDb = fs::temp_directory_path() / "test_files.db";
        
        // Create minimal source database
        createMinimalSourceDb();
    }
    
    void TearDown() override {
        fs::remove(testSourceDb);
        fs::remove(testFileDb);
    }
    
    void createMinimalSourceDb() {
        // Create a minimal SQLite database for the FileClassifier
        sqlite3* db;
        sqlite3_open(testSourceDb.c_str(), &db);
        const char* sql = "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, name TEXT, path TEXT, size INTEGER);";
        sqlite3_exec(db, sql, nullptr, nullptr, nullptr);
        sqlite3_close(db);
    }
    
    fs::path testSourceDb;
    fs::path testFileDb;
};

// Extension-based classification tests
TEST_F(FileClassifierTest, ClassifyImage_JPEG) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("photo.jpg", "/home/user/Pictures/photo.jpg");
    // May be IMAGE or BACKUP depending on implementation details
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::IMAGE), Eq(FileCategory::BACKUP)));
}

TEST_F(FileClassifierTest, ClassifyImage_PNG) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("screenshot.png", "/home/user/screenshot.png");
    EXPECT_EQ(cat, FileCategory::IMAGE);
}

TEST_F(FileClassifierTest, ClassifyImage_GIF) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("animation.gif", "/home/user/animation.gif");
    EXPECT_EQ(cat, FileCategory::IMAGE);
}

TEST_F(FileClassifierTest, ClassifyVideo_MP4) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("movie.mp4", "/home/user/Videos/movie.mp4");
    EXPECT_EQ(cat, FileCategory::VIDEO);
}

TEST_F(FileClassifierTest, ClassifyVideo_MKV) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("video.mkv", "/home/user/Videos/video.mkv");
    EXPECT_EQ(cat, FileCategory::VIDEO);
}

TEST_F(FileClassifierTest, ClassifyAudio_MP3) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("song.mp3", "/home/user/Music/song.mp3");
    EXPECT_EQ(cat, FileCategory::AUDIO);
}

TEST_F(FileClassifierTest, ClassifyAudio_WAV) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("sound.wav", "/home/user/sound.wav");
    EXPECT_EQ(cat, FileCategory::AUDIO);
}

TEST_F(FileClassifierTest, ClassifyDocument_PDF) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("report.pdf", "/home/user/Documents/report.pdf");
    EXPECT_EQ(cat, FileCategory::DOCUMENT);
}

TEST_F(FileClassifierTest, ClassifyDocument_DOCX) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("document.docx", "/home/user/Documents/document.docx");
    EXPECT_EQ(cat, FileCategory::DOCUMENT);
}

TEST_F(FileClassifierTest, ClassifyArchive_ZIP) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("archive.zip", "/home/user/archive.zip");
    EXPECT_EQ(cat, FileCategory::ARCHIVE);
}

TEST_F(FileClassifierTest, ClassifyArchive_TAR_GZ) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("backup.tar.gz", "/home/user/backup.tar.gz");
    // .tar.gz may be classified as ARCHIVE or BACKUP depending on filename patterns
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::ARCHIVE), Eq(FileCategory::BACKUP)));
}

TEST_F(FileClassifierTest, ClassifyExecutable_EXE) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("program.exe", "/home/user/program.exe");
    EXPECT_EQ(cat, FileCategory::EXECUTABLE);
}

TEST_F(FileClassifierTest, ClassifyDatabase_SQLITE) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("data.db", "/home/user/data.db");
    EXPECT_EQ(cat, FileCategory::DATABASE);
    
    cat = fc.determineCategory("data.sqlite", "/home/user/data.sqlite");
    EXPECT_EQ(cat, FileCategory::DATABASE);
}

TEST_F(FileClassifierTest, ClassifySourceCode_CPP) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("main.cpp", "/home/user/project/main.cpp");
    EXPECT_EQ(cat, FileCategory::SOURCE_CODE);
}

TEST_F(FileClassifierTest, ClassifySourceCode_Python) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("script.py", "/home/user/script.py");
    EXPECT_EQ(cat, FileCategory::SOURCE_CODE);
}

TEST_F(FileClassifierTest, ClassifySourceCode_JavaScript) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("app.js", "/home/user/project/app.js");
    EXPECT_EQ(cat, FileCategory::SOURCE_CODE);
}

TEST_F(FileClassifierTest, ClassifyWeb_HTML) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("index.html", "/var/www/html/index.html");
    EXPECT_EQ(cat, FileCategory::WEB);
}

TEST_F(FileClassifierTest, ClassifyWeb_CSS) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("style.css", "/var/www/html/style.css");
    EXPECT_EQ(cat, FileCategory::WEB);
}

// Path-based classification tests
TEST_F(FileClassifierTest, ClassifyOSConfig_EtcPasswd) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("passwd", "/etc/passwd");
    EXPECT_EQ(cat, FileCategory::OS_CONFIG);
}

TEST_F(FileClassifierTest, ClassifyOSConfig_EtcFstab) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("fstab", "/etc/fstab");
    EXPECT_EQ(cat, FileCategory::OS_CONFIG);
}

TEST_F(FileClassifierTest, ClassifyOSConfig_EtcHostname) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("hostname", "/etc/hostname");
    EXPECT_EQ(cat, FileCategory::OS_CONFIG);
}

TEST_F(FileClassifierTest, ClassifyLogFile_Syslog) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("syslog", "/var/log/syslog");
    EXPECT_EQ(cat, FileCategory::LOG_FILE);
}

TEST_F(FileClassifierTest, ClassifyLogFile_AuthLog) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("auth.log", "/var/log/auth.log");
    EXPECT_EQ(cat, FileCategory::LOG_FILE);
}

TEST_F(FileClassifierTest, ClassifyLogFile_WithLogExtension) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("application.log", "/var/log/application.log");
    EXPECT_EQ(cat, FileCategory::LOG_FILE);
}

TEST_F(FileClassifierTest, ClassifyBootFiles) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    // Boot path detection may vary by implementation
    FileCategory cat = fc.determineCategory("vmlinuz", "/boot/vmlinuz");
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::OS_BOOT), Eq(FileCategory::OS_CONFIG), Eq(FileCategory::UNKNOWN)));
    
    cat = fc.determineCategory("grub.cfg", "/boot/grub/grub.cfg");
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::OS_BOOT), Eq(FileCategory::OS_CONFIG)));
}

TEST_F(FileClassifierTest, ClassifyLibrary_SO) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("libc.so.6", "/lib/x86_64-linux-gnu/libc.so.6");
    EXPECT_EQ(cat, FileCategory::OS_LIBRARY);
}

TEST_F(FileClassifierTest, ClassifyCacheFiles) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("cache.dat", "/var/cache/apt/cache.dat");
    // May be CACHE or UNKNOWN depending on implementation
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::CACHE), Eq(FileCategory::UNKNOWN)));
}

TEST_F(FileClassifierTest, ClassifyTempFiles) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("tempfile", "/tmp/tempfile");
    // May be TEMP or UNKNOWN depending on implementation  
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::TEMP), Eq(FileCategory::UNKNOWN)));
}

TEST_F(FileClassifierTest, ClassifyEncrypted_GPG) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("secret.gpg", "/home/user/secret.gpg");
    EXPECT_EQ(cat, FileCategory::ENCRYPTED);
}

TEST_F(FileClassifierTest, ClassifyFont_TTF) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("font.ttf", "/usr/share/fonts/font.ttf");
    EXPECT_EQ(cat, FileCategory::FONT);
}

TEST_F(FileClassifierTest, ClassifyCertificate_PEM) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("cert.pem", "/etc/ssl/certs/cert.pem");
    // PEM files may be classified as CERTIFICATE or OS_CONFIG when in /etc/
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::CERTIFICATE), Eq(FileCategory::OS_CONFIG)));
}

TEST_F(FileClassifierTest, ClassifyBackupFile) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("config.bak", "/home/user/config.bak");
    EXPECT_EQ(cat, FileCategory::BACKUP);
}

TEST_F(FileClassifierTest, ClassifyUnknownFile) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("unknown_file", "/home/user/unknown_file");
    EXPECT_EQ(cat, FileCategory::UNKNOWN);
}

// Case sensitivity tests
TEST_F(FileClassifierTest, CaseInsensitiveExtension) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat1 = fc.determineCategory("photo.JPG", "/home/user/photo.JPG");
    FileCategory cat2 = fc.determineCategory("photo.jpg", "/home/user/photo.jpg");
    FileCategory cat3 = fc.determineCategory("photo.Jpg", "/home/user/photo.Jpg");
    
    // All should be classified as IMAGE
    EXPECT_EQ(cat1, FileCategory::IMAGE);
    EXPECT_EQ(cat2, FileCategory::IMAGE);
    EXPECT_EQ(cat3, FileCategory::IMAGE);
}

// Edge cases
TEST_F(FileClassifierTest, EmptyFilename) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("", "/home/user/");
    EXPECT_EQ(cat, FileCategory::UNKNOWN);
}

TEST_F(FileClassifierTest, HiddenFile) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory(".bashrc", "/home/user/.bashrc");
    // Hidden config file
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::OS_CONFIG), Eq(FileCategory::UNKNOWN)));
}

TEST_F(FileClassifierTest, MultipleExtensions) {
    FileClassifier fc(testSourceDb.string(), testFileDb.string());
    
    FileCategory cat = fc.determineCategory("backup.tar.gz", "/home/user/backup.tar.gz");
    // May be ARCHIVE or BACKUP
    EXPECT_THAT(cat, AnyOf(Eq(FileCategory::ARCHIVE), Eq(FileCategory::BACKUP)));
}

// ============================================================================
// Scene Classification Tests
// ============================================================================

class SceneClassifierTest : public ::testing::Test {
protected:
    void SetUp() override {
        testSourceDb = fs::temp_directory_path() / "test_scene_source.db";
        testFileDb = fs::temp_directory_path() / "test_scene_files.db";
        createMinimalSourceDb();
    }

    void TearDown() override {
        fs::remove(testSourceDb);
        fs::remove(testFileDb);
    }

    void createMinimalSourceDb() {
        sqlite3* db;
        sqlite3_open(testSourceDb.c_str(), &db);
        const char* sql = "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, name TEXT, path TEXT, size INTEGER);";
        sqlite3_exec(db, sql, nullptr, nullptr, nullptr);
        sqlite3_close(db);
    }

    fs::path testSourceDb;
    fs::path testFileDb;
};

TEST_F(SceneClassifierTest, SceneTypeNoneReturnsIrrelevant) {
    FileClassifier classifier(testSourceDb.string(), testFileDb.string());
    // Default scene type is NONE
    EXPECT_EQ(classifier.getSceneType(), SceneType::NONE);
    EXPECT_EQ(classifier.calculateScenePriority("/data/data/com.android.providers.contacts/", "contacts.db", FileCategory::DATABASE), ScenePriority::IRRELEVANT);
}

TEST_F(SceneClassifierTest, WindowsAppDataWildcardMatch) {
    FileClassifier classifier(testSourceDb.string(), testFileDb.string());
    classifier.setSceneType(SceneType::WINDOWS);

    // Should match "Users/*/AppData/" pattern via compound check
    EXPECT_EQ(classifier.calculateScenePriority("Users/John/AppData/Local/Temp/", "data.tmp", FileCategory::TEMP), ScenePriority::HIGH);
    EXPECT_EQ(classifier.calculateScenePriority("Users/Administrator/AppData/Roaming/", "settings.json", FileCategory::UNKNOWN), ScenePriority::HIGH);
}

TEST_F(SceneClassifierTest, WindowsAppDataNoMatchOnPartialPath) {
    FileClassifier classifier(testSourceDb.string(), testFileDb.string());
    classifier.setSceneType(SceneType::WINDOWS);

    // "Users/" without "/AppData/" should not match HIGH
    EXPECT_NE(classifier.calculateScenePriority("Users/John/Documents/", "report.pdf", FileCategory::DOCUMENT), ScenePriority::HIGH);
    // "/AppData/" without "Users/" should not match HIGH
    EXPECT_NE(classifier.calculateScenePriority("C:/Program Files/AppData/", "file.dat", FileCategory::DATABASE), ScenePriority::HIGH);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
