#include <gtest/gtest.h>
#include "analyzers/WindowsFilesAnalyzer/Parsers/WindowsPrefetchParser.h"
#include "analyzers/WindowsFilesAnalyzer/Parsers/WindowsEventLogParser.h"
#include "analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.h"
#include <filesystem>
#include <fstream>
#include <unistd.h>

namespace fs=std::filesystem;
static fs::path fixture(const char* name) { return fs::path(PARSER_FIXTURE_DIR)/name; }

#ifdef HAVE_LIBSCCA
TEST(PrefetchTruth, PlainAndCompressedHaveKnownFacts) {
    // Keep libevtx loaded: leaked private symbols from a libscca build must not
    // interpose its bfio/date helpers when the full application links both.
    ASSERT_NE(libevtx_get_version(),nullptr);
    for (auto name : {"synthetic_v17.pf", "synthetic_v17_mam.pf"}) {
        PrefetchParser parser(fixture(name).string());
        ASSERT_TRUE(parser.parse()) << parser.getLastError();
        EXPECT_EQ(parser.getVersion(),PrefetchVersion::VERSION_17);
        EXPECT_EQ(parser.getRunCount(),2);
        EXPECT_EQ(parser.getExecutableName(),"SAMPLE.EXE");
        EXPECT_EQ(parser.getPrefetchHash(),"12345678");
        EXPECT_EQ(parser.getLastRunTime(),1747731064);
        ASSERT_EQ(parser.getRawRunTimes().size(),1);
        EXPECT_EQ(parser.getRawRunTimes()[0],133922046640650370ULL);
        EXPECT_TRUE(parser.getExecutablePath().empty());
        EXPECT_EQ(parser.getCreationTime(),0);
        ASSERT_TRUE(parser.parse()); // No duplicated timestamps on reuse.
        EXPECT_EQ(parser.getAllRunTimes().size(),1);
    }
}

TEST(PrefetchTruth, MissingLatestSlotDoesNotPromoteAnOlderExecution) {
    std::vector<unsigned char> data(4096,0);
    auto put32=[&](size_t offset,uint32_t value){for(int i=0;i<4;++i)data[offset+i]=value>>(8*i);};
    auto put64=[&](size_t offset,uint64_t value){for(int i=0;i<8;++i)data[offset+i]=value>>(8*i);};
    put32(0,26);data[4]='S';data[5]='C';data[6]='C';data[7]='A';put32(12,4096);
    const std::string name="SAMPLE.EXE";
    for(size_t i=0;i<name.size();++i)data[16+2*i]=name[i];
    put64(136,133922046640650370ULL);put32(208,5);
    const auto path=fs::temp_directory_path()/("tracelens-pf-slot-"+std::to_string(getpid()));
    {std::ofstream file(path,std::ios::binary);file.write(reinterpret_cast<const char*>(data.data()),data.size());}
    PrefetchParser parser(path.string());ASSERT_TRUE(parser.parse())<<parser.getLastError();
    EXPECT_FALSE(parser.hasLastRunTime());EXPECT_EQ(parser.getAllRunTimes().size(),1);
    fs::remove(path);
}
#endif

TEST(PrefetchTruth, CompressedHeaderDoesNotClaimVersion) {
    const char head[8]={'M','A','M',4,30,0,0,0};
    EXPECT_EQ(PrefetchHelpers::detectVersion(head),PrefetchVersion::UNKNOWN);
    EXPECT_EQ(PrefetchHelpers::filetimeToUnixTime(116444735990000000ULL),-1);
}

TEST(EvtxTruth, LevelAndSidCannotInventFacts) {
    EXPECT_EQ(EvtxHelpers::eventLevelToString(0),"LogAlways");
    EXPECT_EQ(EvtxHelpers::eventLevelToString(3),"Warning");
    EXPECT_EQ(EvtxHelpers::eventLevelToString(4),"Information");
    EXPECT_EQ(EvtxHelpers::eventLevelToString(7),"Unknown");
    EXPECT_EQ(EvtxHelpers::filetimeToUnixTime(116444735990000000ULL),-1);
    EXPECT_TRUE(EvtxHelpers::extractUserDataFromXML("<Event><EventData><Data Name='SubjectUserName'>admin</Data></EventData></Event>").empty());
    EXPECT_EQ(EvtxHelpers::extractUserDataFromXML("<Event><EventData><Data Name='SubjectUserName'>admin</Data><Data Name='SubjectUserSid'>S-1-5-18</Data></EventData></Event>"),"S-1-5-18");
    EXPECT_EQ(EvtxHelpers::extractChannelFromXML("<Event><System><Channel>Security</Channel></System></Event>"),"Security");
    EXPECT_TRUE(EvtxHelpers::extractChannelFromXML("<Event/>").empty());
}

TEST(PrefetchTruth, FailedParseClearsOldFacts) {
    const auto path=fs::temp_directory_path()/("tracelens-pf-"+std::to_string(getpid()));
    fs::copy_file(fixture("synthetic_v17.pf"),path,fs::copy_options::overwrite_existing);
    PrefetchParser parser(path.string());
    parser.parse();
    { std::ofstream file(path,std::ios::binary|std::ios::trunc); file << "MAM"; }
    EXPECT_FALSE(parser.parse());
    EXPECT_TRUE(parser.getAllRunTimes().empty());
    EXPECT_TRUE(parser.getExecutableName().empty());
    EXPECT_FALSE(parser.getLastError().empty());
    fs::remove(path);
}

TEST(ParserStorage, UnknownIsNullAndOldRowsAreNotReinterpreted) {
    const auto path=fs::temp_directory_path()/("tracelens-parser-"+std::to_string(getpid())+".db");
    fs::remove(path);
    sqlite3* db=nullptr; ASSERT_EQ(sqlite3_open(path.c_str(),&db),SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,"CREATE TABLE prefetch_files(id INTEGER PRIMARY KEY, file_path TEXT, executable_name TEXT, executable_path TEXT, prefetch_hash TEXT, run_count INTEGER,last_run_time INTEGER,creation_time INTEGER,referenced_files TEXT,referenced_directories TEXT); INSERT INTO prefetch_files(file_path,run_count) VALUES('legacy',658809);",nullptr,nullptr,nullptr),SQLITE_OK);
    sqlite3_close(db);
    {
        WindowsAnalysisDatabase store(path.string()); ASSERT_TRUE(store.initialize());
        PrefetchInfo missing; missing.filePath="broken"; missing.parseError="PREFETCH_PARSE_FAILED";
        ASSERT_TRUE(store.insertPrefetchInfo(missing));
        PrefetchInfo zero; zero.filePath="valid_zero"; zero.parseStatus="ok"; zero.runCount=0;
        ASSERT_TRUE(store.insertPrefetchInfo(zero));
        auto rows=store.queryPrefetchFiles("file_path='broken'"); ASSERT_EQ(rows.size(),1);
        EXPECT_FALSE(rows[0].runCount.has_value()); EXPECT_FALSE(rows[0].lastRunTime.has_value());
        auto old=store.queryPrefetchFiles("file_path='legacy'"); ASSERT_EQ(old.size(),1);
        EXPECT_EQ(old[0].parseStatus,"legacy_unverified"); EXPECT_EQ(*old[0].runCount,658809);
        EventLogEntry unknown; unknown.logSource="test";
        ASSERT_TRUE(store.insertEventLogEntry(unknown));
        auto events=store.queryEventLogs(); ASSERT_EQ(events.size(),1);
        EXPECT_EQ(events[0].eventId,-1); EXPECT_FALSE(events[0].timestampKnown);
        EXPECT_TRUE(events[0].message.empty());
        ASSERT_TRUE(store.initialize()); // Additive migration is idempotent.
    }
    ASSERT_EQ(sqlite3_open(path.c_str(),&db),SQLITE_OK);
    sqlite3_stmt* statement=nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db,"SELECT run_count,last_run_time FROM prefetch_files WHERE file_path='broken'",-1,&statement,nullptr),SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement),SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_type(statement,0),SQLITE_NULL); EXPECT_EQ(sqlite3_column_type(statement,1),SQLITE_NULL);
    sqlite3_finalize(statement); sqlite3_close(db); fs::remove(path);
}
