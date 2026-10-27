#include <gtest/gtest.h>
#include "core/DatabaseManager/SourceIndex.h"
#include "network/HTTPServer/ReportTailResume.h"
#include <fstream>
#include <filesystem>
#include <chrono>
namespace src=forensics::sources;
namespace fs=std::filesystem;
namespace {
struct Database {
    fs::path path;sqlite3* db=nullptr;
    explicit Database(const std::string& suffix) {
        path=fs::temp_directory_path()/("source-index-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count())+suffix);
        if(sqlite3_open(path.string().c_str(),&db)!=SQLITE_OK)throw std::runtime_error("open failed");
        src::sql(db,"CREATE TABLE files(id INTEGER PRIMARY KEY,inode INTEGER,name TEXT,path TEXT,size INTEGER,mtime INTEGER,ctime INTEGER,type TEXT,is_deleted INTEGER,partition_num INTEGER)");
    }
    ~Database(){sqlite3_close(db);std::error_code ec;fs::remove(path,ec);}
    void add(int id,int inode,int deleted) {
        src::sql(db,"INSERT INTO files VALUES("+std::to_string(id)+","+std::to_string(inode)+",'Amcache.hve','/Windows/Amcache.hve',123,100,90,'REG',"+std::to_string(deleted)+",6)");
    }
    std::string identity(int inode) {
        src::Statement s(db,"SELECT source_id FROM files WHERE inode="+std::to_string(inode));
        if(sqlite3_step(s.value)!=SQLITE_ROW || sqlite3_column_type(s.value,0)==SQLITE_NULL)return {};
        return reinterpret_cast<const char*>(sqlite3_column_text(s.value,0));
    }
};
}
TEST(SourceIdentity, SamePathLiveAndDeletedRemainDistinctAfterClassification) {
    Database raw("-raw.db"),derived("-files.db");raw.add(1,89169,0);raw.add(2,120441,1);
    ASSERT_TRUE(src::ensure(raw.db,""));
    const auto live=raw.identity(89169),deleted=raw.identity(120441);
    ASSERT_TRUE(src::validId(live));ASSERT_TRUE(src::validId(deleted));EXPECT_NE(live,deleted);
    derived.add(8,120441,1);derived.add(9,89169,0);
    ASSERT_TRUE(src::copy(raw.db,derived.db,raw.path.string()));
    EXPECT_EQ(live,derived.identity(89169));EXPECT_EQ(deleted,derived.identity(120441));
    const auto locator=src::lookup(derived.db,deleted);
    EXPECT_EQ(locator["partition_num"],6);EXPECT_EQ(locator["inode"],120441);EXPECT_EQ(locator["is_deleted"],1);
    ASSERT_TRUE(src::ensure(raw.db,""));EXPECT_EQ(raw.identity(89169),live);
    src::sql(raw.db,"UPDATE files SET size=124 WHERE inode=89169");
    EXPECT_FALSE(src::ensure(raw.db,"")); // No silent reassignment under the old revision.
}
TEST(SourceIdentity, LogicalEntryDoesNotPretendToBeAHandsetInode) {
    Database raw("-logical.db");raw.add(1,17,0);
    src::sql(raw.db,"CREATE TABLE harmony_source_files(path TEXT PRIMARY KEY,bundle TEXT,app_index INTEGER,original_path TEXT,container TEXT,data_offset INTEGER);"
        "INSERT INTO harmony_source_files VALUES('/Windows/Amcache.hve','test.app',2,'databases/History','app.tar',512)");
    ASSERT_TRUE(src::ensure(raw.db,""));
    const auto locator=src::lookup(raw.db,raw.identity(17));
    EXPECT_TRUE(locator["inode"].is_null());EXPECT_EQ(locator["entry_id"],17);
    EXPECT_EQ(locator["logical_location"]["container"],"app.tar");
}
TEST(SourceIdentity, ChangedLocatorAndMalformedIdsFailClosed) {
    Database raw("-integrity.db");raw.add(1,17,0);ASSERT_TRUE(src::ensure(raw.db,""));
    const auto id=raw.identity(17);
    EXPECT_EQ(src::referencePath(src::reference(id,"/a/History")),"/a/History");
    EXPECT_EQ(src::referenceId(src::reference(id,"/a/History")),id);
    EXPECT_TRUE(src::lookup(raw.db,"not-an-id").is_null());
    src::sql(raw.db,"UPDATE source_objects SET locator_json='{}'");
    EXPECT_THROW(src::lookup(raw.db,id),std::runtime_error);
}

TEST(SourceIdentity, InvalidUtf8NamesRemainReadableAndRetainOriginalBytes) {
    Database raw("-encoding.db"),derived("-encoding-files.db");
    const std::string invalid("\x8c\x03\x1c",3);
    const auto shown=forensics::source_names::component(invalid);
    auto insert=[&](int id,const std::string& name){
        src::Statement s(raw.db,"INSERT INTO files VALUES(?,?,?, ?,123,100,90,'REG',0,6)");
        sqlite3_bind_int(s.value,1,id);sqlite3_bind_int(s.value,2,id);s.bind(3,name);s.bind(4,"/case/"+name);
        ASSERT_EQ(sqlite3_step(s.value),SQLITE_DONE);
    };
    insert(1,invalid);insert(2,shown);insert(3,"中文.txt");
    std::string error;ASSERT_TRUE(src::ensure(raw.db,"",&error))<<error;
    const auto first=src::lookup(raw.db,raw.identity(1)),literal=src::lookup(raw.db,raw.identity(2));
    EXPECT_EQ(first["logical_path"],"/case/"+shown);
    EXPECT_EQ(first["raw_name_hex"],"8c031c");
    EXPECT_EQ(first["name_encoding"],"lossless-component-bytes:v1");
    EXPECT_NE(first["logical_path"],literal["logical_path"]);
    EXPECT_EQ(src::lookup(raw.db,raw.identity(3))["logical_name"],"中文.txt");
    {src::Statement s(raw.db,"SELECT hex(name_bytes) FROM source_name_bytes WHERE raw_record_id=1");
     ASSERT_EQ(sqlite3_step(s.value),SQLITE_ROW);EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(s.value,0)),"8C031C");}
    const auto identity=raw.identity(1);ASSERT_TRUE(src::ensure(raw.db,""));EXPECT_EQ(identity,raw.identity(1));
    {src::Statement s(derived.db,"INSERT INTO files VALUES(1,1,?, ?,123,100,90,'REG',0,6)");s.bind(1,shown);s.bind(2,"/case/"+shown);ASSERT_EQ(sqlite3_step(s.value),SQLITE_DONE);}
    ASSERT_TRUE(src::copy(raw.db,derived.db,raw.path.string()));
    EXPECT_EQ(src::lookup(derived.db,derived.identity(1)),first);
}

TEST(SourceIdentity, EmbeddedNulAndLongNamesCannotLoseBytesOrOverflowPayloadName) {
    Database raw("-nul.db");const std::string name("a\0b",3);
    src::Statement s(raw.db,"INSERT INTO files VALUES(1,1,?, ?,12,0,0,'REG',0,1)");s.bind(1,name);s.bind(2,"/"+name);
    ASSERT_EQ(sqlite3_step(s.value),SQLITE_DONE);ASSERT_TRUE(src::ensure(raw.db,""));
    const auto locator=src::lookup(raw.db,raw.identity(1));EXPECT_EQ(locator["raw_name_hex"],"610062");
    EXPECT_EQ(locator["raw_path_hex"],"2f610062");
    EXPECT_LT(forensics::source_names::component(std::string(250,'\xff')).size(),255u);
}

TEST(ReportTailResume, CheckpointAndWatermarksDoNotInvalidateUnchangedAnalyzedRecords) {
    Database files("-resume-files.db"),events("-resume-events.db");files.add(1,17,0);
    const auto image=files.path.string()+".E01";{std::ofstream out(image);out<<"source";}
    ASSERT_TRUE(src::ensure(files.db,image));
    src::sql(files.db,"PRAGMA journal_mode=WAL; ALTER TABLE files ADD COLUMN ingested_at INTEGER; ALTER TABLE files ADD COLUMN llm_analyzed_at INTEGER;");
    src::sql(events.db,"PRAGMA journal_mode=WAL; CREATE TABLE events(data TEXT,ingested_at INTEGER);INSERT INTO events VALUES('record',NULL)");
    const auto expected=forensics::report_tail::ingestionFingerprint(events.path.string(),files.path.string());
    ASSERT_FALSE(expected.empty());
    src::sql(files.db,"UPDATE files SET ingested_at=123,llm_analyzed_at=456; PRAGMA wal_checkpoint(TRUNCATE)");
    src::sql(events.db,"UPDATE events SET ingested_at=789; PRAGMA wal_checkpoint(TRUNCATE)");
    EXPECT_TRUE(forensics::report_tail::unchangedInputs(image,files.path.string(),events.path.string(),expected));
    src::sql(files.db,"UPDATE files SET size=124 WHERE id=1");
    EXPECT_FALSE(forensics::report_tail::unchangedInputs(image,files.path.string(),events.path.string(),expected));
    fs::remove(image);
}

TEST(ReportTailResume, ChangedImageEventsAndMissingInputsCannotSkipThePipeline) {
    Database files("-changed-files.db"),events("-changed-events.db");files.add(1,17,0);
    const auto image=files.path.string()+".E01";{std::ofstream out(image);out<<"source";}
    ASSERT_TRUE(src::ensure(files.db,image));src::sql(events.db,"CREATE TABLE events(data TEXT);INSERT INTO events VALUES('original')");
    const auto expected=forensics::report_tail::ingestionFingerprint(events.path.string(),files.path.string());
    EXPECT_FALSE(forensics::report_tail::unchangedInputs(image,files.path.string(),events.path.string(),""));
    src::sql(events.db,"UPDATE events SET data='changed'");
    EXPECT_FALSE(forensics::report_tail::unchangedInputs(image,files.path.string(),events.path.string(),expected));
    src::sql(events.db,"UPDATE events SET data='original'");
    {std::ofstream out(image,std::ios::app);out<<"changed";}
    EXPECT_FALSE(forensics::report_tail::unchangedInputs(image,files.path.string(),events.path.string(),expected));
    fs::remove(image);
    EXPECT_FALSE(forensics::report_tail::unchangedInputs(image,files.path.string(),events.path.string(),expected));
}
