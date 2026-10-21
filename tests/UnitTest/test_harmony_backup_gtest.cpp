#include <gtest/gtest.h>
#include "analyzers/AndroidAnalyzer/HarmonyBackupExtractor.h"
#include "analyzers/AndroidAnalyzer/HarmonyArtifactParsers.h"
#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "core/DatabaseManager/HarmonySourceIndex.h"
#include <archive.h>
#include <archive_entry.h>
#include <fstream>
#include <unistd.h>

namespace fs = std::filesystem;
using json = nlohmann::json;
namespace {
class HarmonyBackupTest : public ::testing::Test {
protected:
    fs::path temp,root,app;
    void SetUp() override {
        char pattern[]="/tmp/harmony-test-XXXXXX";temp=mkdtemp(pattern);root=temp/"evidence";
        app=root/"files/BASIC/com.huawei.hmos.calendardata";fs::create_directories(app);
        write(root/".info.json",json({{"BackupFileHeaderInfo",{{"deviceModel","fixture"},{"backupTime",1700000000000LL}}},
            {"BackupFileModuleInfo",json::array({{{"moduleName","com.huawei.hmos.calendardata"},{"appIndex",0},{"appName","Calendar"}}})}}).dump());
    }
    void TearDown() override {fs::remove_all(temp);}
    static void write(const fs::path& p,const std::string& b) {std::ofstream f(p,std::ios::binary);f.write(b.data(),b.size());}
    void archiveFiles(const std::vector<std::pair<std::string,std::string>>& entries) {
        auto* a=archive_write_new();archive_write_set_format_gnutar(a);
        ASSERT_EQ(archive_write_open_filename(a,(app/"part.0.tarx").c_str()),ARCHIVE_OK);
        for(const auto& [name,bytes]:entries) {
            auto* e=archive_entry_new();archive_entry_set_pathname(e,name.c_str());archive_entry_set_filetype(e,AE_IFREG);
            archive_entry_set_perm(e,0600);archive_entry_set_size(e,bytes.size());archive_entry_set_mtime(e,1700000000,0);
            ASSERT_EQ(archive_write_header(a,e),ARCHIVE_OK);ASSERT_EQ(archive_write_data(a,bytes.data(),bytes.size()),bytes.size());archive_entry_free(e);
        }
        archive_write_close(a);archive_write_free(a);
        write(app/"manage.jsonx",json::array({{{"fileName","part.0.tar"},{"isBigFile",false},
            {"information",{{"path","/data/storage/el2/base/.backup/part.0.tar"},{"stat",{{"st_size",fs::file_size(app/"part.0.tarx")}}}}}}}).dump());
    }
    std::string dbBytes() {
        sqlite3* db=nullptr;auto p=temp/"input.db";sqlite3_open(p.c_str(),&db);
        sqlite3_exec(db,"CREATE TABLE Events(_id INTEGER PRIMARY KEY,title TEXT,dtstart INTEGER);"
            "INSERT INTO Events VALUES(7,'test event',1700000000000);",nullptr,nullptr,nullptr);sqlite3_close(db);
        std::ifstream f(p,std::ios::binary);return {std::istreambuf_iterator<char>(f),{}};
    }
};
TEST_F(HarmonyBackupTest, GnuLongNamesRoundTripAndScopedIndexReload) {
    const std::string name="/data/storage/el2/base/files/"+std::string(180,'a')+".txt";
    archiveFiles({{name,"long-name payload"},{"/data/storage/el2/base/files/x.txt","second file"}});
    HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize())<<source.error();ASSERT_EQ(source.entries().size(),2);
    auto path=HarmonyBackupExtractor::scopedPath("com.huawei.hmos.calendardata",0,name);
    ASSERT_TRUE(source.extractFileByPath(path,(temp/"output.txt").string()))<<source.error();
    std::ifstream f(temp/"output.txt");std::string bytes((std::istreambuf_iterator<char>(f)),{});EXPECT_EQ(bytes,"long-name payload");
    sqlite3* db=nullptr;sqlite3_open(":memory:",&db);ASSERT_TRUE(source.saveIndex(db));
    HarmonyBackupExtractor reloaded(root);ASSERT_TRUE(reloaded.loadIndex(db));EXPECT_EQ(reloaded.entries().size(),2);sqlite3_close(db);
    EXPECT_FALSE(source.extractFileByPath(path,(root/"overwrite.txt").string()));
}
TEST_F(HarmonyBackupTest, RejectsTraversalAndDoesNotResolveAcrossApplications) {
    EXPECT_TRUE(HarmonyBackupExtractor::scopedPath("a",0,"/data/storage/../../escape").empty());
    EXPECT_TRUE(HarmonyBackupExtractor::scopedPath("../a",0,"/data/storage/el2/x").empty());
    EXPECT_EQ(HarmonyBackupExtractor::scopedPath("a",0,"/data/storage/el2/perf:0.jpg"),
              "/harmony/a/0/data/storage/el2/perf%3A0.jpg");
    EXPECT_NE(HarmonyBackupExtractor::scopedPath("a",0,"/data/storage/el2/x"),HarmonyBackupExtractor::scopedPath("b",0,"/data/storage/el2/x"));
    archiveFiles({{"/data/storage/el2/x","abc"}});HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize());
    EXPECT_FALSE(source.extractFileByPath("/harmony/other/0/data/storage/el2/x",(temp/"out").string()));
}
TEST_F(HarmonyBackupTest, DetectsSourceChanges) {
    archiveFiles({{"/data/storage/el2/x","abc"}});HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize());
    std::ofstream f(app/"part.0.tarx",std::ios::app);f<<"changed";f.close();
    EXPECT_FALSE(source.extractFileByPath(source.entries().begin()->first,(temp/"out").string()));
    EXPECT_EQ(source.error(),"EVIDENCE_CHANGED_AFTER_INDEX");
}
TEST_F(HarmonyBackupTest, RejectsAmbiguousClonedAppOwnership) {
    archiveFiles({{"/data/storage/el2/x","abc"}});
    auto info=json::parse(std::ifstream(root/".info.json"));
    auto clone=info["BackupFileModuleInfo"][0];clone["appIndex"]=1;
    info["BackupFileModuleInfo"].push_back(clone);write(root/".info.json",info.dump());
    HarmonyBackupExtractor source(root);EXPECT_FALSE(source.initialize());
    EXPECT_EQ(source.error(),"AMBIGUOUS_HARMONY_MODULE");
}
TEST_F(HarmonyBackupTest, CopyIndexPreservesTheSourceDatabase) {
    archiveFiles({{"/data/storage/el2/x","abc"}});HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize());
    sqlite3 *input=nullptr,*output=nullptr;
    const auto path=temp/"raw.db";ASSERT_EQ(sqlite3_open(path.c_str(),&input),SQLITE_OK);
    ASSERT_EQ(sqlite3_open(":memory:",&output),SQLITE_OK);ASSERT_TRUE(source.saveIndex(input));
    ASSERT_TRUE(copyHarmonySourceIndex(input,output,path.string()));
    ASSERT_TRUE(copyHarmonySourceIndex(input,output,path.string()));
    for(auto* db:{input,output}) {
        sqlite3_stmt* count=nullptr;ASSERT_EQ(sqlite3_prepare_v2(db,"SELECT COUNT(*) FROM harmony_source_files",-1,&count,nullptr),SQLITE_OK);
        ASSERT_EQ(sqlite3_step(count),SQLITE_ROW);EXPECT_EQ(sqlite3_column_int(count,0),1);sqlite3_finalize(count);
    }
    sqlite3_close(output);sqlite3_close(input);
}
TEST_F(HarmonyBackupTest, ParsesCalendarWithRowProvenanceAndIdempotentResults) {
    archiveFiles({{"/data/storage/el2/database/entry/rdb/calendardata.db",dbBytes()}});
    HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize())<<source.error();
    AndroidAnalysisDatabase result((temp/"result.db").string());ASSERT_TRUE(result.initialize());
    fs::create_directories(temp/"work");ASSERT_TRUE(analyzeHarmonyBackup(source,result,temp/"work"));
    ASSERT_TRUE(analyzeHarmonyBackup(source,result,temp/"work"));
    sqlite3_stmt* s=nullptr;sqlite3_prepare_v2(result.handle(),"SELECT kind,source_key,timestamp_seconds,length(source_db_sha256) FROM mobile_artifacts",-1,&s,nullptr);
    ASSERT_EQ(sqlite3_step(s),SQLITE_ROW);EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(s,0)),"calendar");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(s,1)),"{\"_id\":7}");EXPECT_EQ(sqlite3_column_int64(s,2),1700000000);EXPECT_EQ(sqlite3_column_int(s,3),64);
    EXPECT_EQ(sqlite3_step(s),SQLITE_DONE);sqlite3_finalize(s);
}
TEST_F(HarmonyBackupTest, MissingDecryptedPayloadIsReportedNotParsed) {
    archiveFiles({{"/data/storage/el2/x","abc"}});
    auto j=json::parse(std::ifstream(app/"manage.jsonx"));j.push_back({{"fileName","missing"},{"isBigFile",true},
        {"information",{{"path","/data/storage/el2/missing.db"},{"stat",{{"st_size",4096}}}}}});write(app/"manage.jsonx",j.dump());
    HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize());
    bool missing=false;for(const auto& x:source.coverage()) if(x["status"]=="NOT_FOUND") missing=true;EXPECT_TRUE(missing);
}
TEST_F(HarmonyBackupTest, UnavailableSearchIndexDoesNotHideBusinessRecords) {
    (void)dbBytes();
    sqlite3* input=nullptr;sqlite3_open((temp/"input.db").c_str(),&input);
    ASSERT_EQ(sqlite3_exec(input,"PRAGMA writable_schema=ON; INSERT INTO sqlite_master(type,name,tbl_name,rootpage,sql) "
        "VALUES('table','search_index','search_index',0,'CREATE VIRTUAL TABLE search_index USING unavailable_fts(content)');"
        "PRAGMA writable_schema=OFF;",nullptr,nullptr,nullptr),SQLITE_OK);
    sqlite3_close(input);
    std::ifstream f(temp/"input.db",std::ios::binary);std::string bytes((std::istreambuf_iterator<char>(f)),{});
    archiveFiles({{"/data/storage/el2/database/entry/rdb/calendardata.db",bytes}});
    HarmonyBackupExtractor source(root);ASSERT_TRUE(source.initialize());
    AndroidAnalysisDatabase result((temp/"result.db").string());ASSERT_TRUE(result.initialize());fs::create_directories(temp/"work");
    ASSERT_TRUE(analyzeHarmonyBackup(source,result,temp/"work"));
    sqlite3_stmt* count=nullptr;sqlite3_prepare_v2(result.handle(),"SELECT COUNT(*) FROM mobile_artifacts WHERE kind='calendar'",-1,&count,nullptr);
    ASSERT_EQ(sqlite3_step(count),SQLITE_ROW);EXPECT_EQ(sqlite3_column_int(count,0),1);sqlite3_finalize(count);
    sqlite3_prepare_v2(result.handle(),"SELECT row_count,open_status FROM app_db_inventory WHERE table_name='search_index'",-1,&count,nullptr);
    ASSERT_EQ(sqlite3_step(count),SQLITE_ROW);EXPECT_EQ(sqlite3_column_type(count,0),SQLITE_NULL);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(count,1)),"unsupported_table");sqlite3_finalize(count);
}
TEST(HarmonyRealBackup, OptionalExternalSample) {
    const char* sample = std::getenv("TRACELENS_HARMONY_TEST_SOURCE");
    const char* output = std::getenv("TRACELENS_HARMONY_TEST_OUTPUT");
    if (!sample || !output) GTEST_SKIP() << "External evidence is opt-in and never checked into the repository";
    fs::path dest(output);fs::create_directories(dest/"work");
    HarmonyBackupExtractor source(sample);ASSERT_TRUE(source.initialize()) << source.error();
    AndroidAnalysisDatabase db((dest/"android.db").string());ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(analyzeHarmonyBackup(source,db,dest/"work"));
    sqlite3_stmt* s=nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db.handle(),"SELECT kind,COUNT(*) FROM mobile_artifacts GROUP BY kind",-1,&s,nullptr),SQLITE_OK);
    while(sqlite3_step(s)==SQLITE_ROW) std::cout << reinterpret_cast<const char*>(sqlite3_column_text(s,0)) << ": " << sqlite3_column_int64(s,1) << std::endl;
    sqlite3_finalize(s);
    EXPECT_GT(source.entries().size(),0);
}
}
