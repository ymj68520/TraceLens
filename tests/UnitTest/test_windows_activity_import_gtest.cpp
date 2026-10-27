#include <gtest/gtest.h>
#include "core/DatabaseManager/EventExtractor/WindowsActivityImport.h"
#include "core/DatabaseManager/SQL/event_extractor_sql.h"
#include "core/DatabaseManager/SQL/windows_analysis_sql_tables.h"
#include <chrono>
namespace wa=forensics::windows_activity;namespace src=forensics::sources;
class WindowsActivityImportTest:public testing::Test {
protected:
 std::filesystem::path dir;sqlite3 *events=nullptr,*win=nullptr;
 void SetUp() override{
  dir=std::filesystem::temp_directory_path()/("win-activity-'"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));std::filesystem::create_directories(dir);
  ASSERT_EQ(sqlite3_open((dir/"events.db").c_str(),&events),SQLITE_OK);ASSERT_EQ(sqlite3_open((dir/"windows.db").c_str(),&win),SQLITE_OK);
  src::sql(events,EventExtractorSQL::CREATE_EVENTS_TABLE);src::sql(win,windows_analysis_sql_tables::CREATE_ALL_TABLES);
  src::sql(win,"ALTER TABLE event_logs ADD COLUMN parse_status TEXT DEFAULT 'ok';ALTER TABLE event_logs ADD COLUMN source_path TEXT;ALTER TABLE event_logs ADD COLUMN is_recovered INTEGER DEFAULT 0;ALTER TABLE event_logs ADD COLUMN raw_timestamp TEXT;"
   "ALTER TABLE prefetch_files ADD COLUMN parse_status TEXT DEFAULT 'ok';ALTER TABLE prefetch_files ADD COLUMN all_run_times TEXT;ALTER TABLE prefetch_files ADD COLUMN raw_run_times TEXT;"
   "CREATE TABLE parser_outcomes(source_path TEXT,parser TEXT,status TEXT,diagnostic TEXT,record_count INTEGER,recovered_count INTEGER);");
  src::sql(win,"INSERT INTO event_logs(record_id,event_id,timestamp,source,message,source_path) VALUES(10,1,1700000000,'test','原始事件正文','/Windows/System32/winevt/Logs/test.evtx');"
   "INSERT INTO prefetch_files(file_path,executable_name,run_count,last_run_time,all_run_times,raw_run_times) VALUES('/Windows/Prefetch/A.pf','A.EXE',7,1700000060,'[1700000060,1700000001]','[133444736600000000,133444736010000000]');"
   "INSERT INTO windows_services(service_name,is_running) VALUES('服务',1);INSERT INTO scheduled_tasks(task_name,next_run_time) VALUES('任务',1900000000);");
 }
 void TearDown() override{sqlite3_close(win);sqlite3_close(events);std::filesystem::remove_all(dir);}
 auto run(){return wa::importArtifacts(events,nullptr,(dir/"windows.db").string(),"task");}
 int count(const std::string& table){src::Statement s(events,"SELECT COUNT(*) FROM "+table);EXPECT_EQ(sqlite3_step(s.value),SQLITE_ROW);return sqlite3_column_int(s.value,0);}
};
TEST_F(WindowsActivityImportTest, ExplicitMappingAndRepeatedImportAreIdempotent){
 auto first=run();ASSERT_TRUE(first["success"])<<first;EXPECT_TRUE(first["complete"]);EXPECT_EQ(count("events"),3);EXPECT_EQ(count("windows_activity_records"),4);
 auto second=run();ASSERT_TRUE(second["success"]);EXPECT_TRUE(second["reused"]);EXPECT_EQ(first["result_set_id"],second["result_set_id"]);EXPECT_EQ(count("events"),3);EXPECT_EQ(count("windows_activity_records"),4);
 EXPECT_EQ(first["undated_records"],2);src::Statement s(events,"SELECT COUNT(*) FROM events WHERE timestamp<=0 OR event_type LIKE '%CONFIG'");ASSERT_EQ(sqlite3_step(s.value),SQLITE_ROW);EXPECT_EQ(sqlite3_column_int(s.value,0),0);
}
TEST_F(WindowsActivityImportTest, ChangedContentCreatesNewVersionAndRetainsHistory){
 auto old=run();src::sql(win,"UPDATE event_logs SET message='修正后的原始记录' WHERE id=1");auto current=run();ASSERT_TRUE(current["success"]);EXPECT_NE(old["result_set_id"],current["result_set_id"]);
 EXPECT_EQ(count("windows_activity_sets"),2);EXPECT_EQ(count("windows_activity_records"),8);EXPECT_EQ(count("windows_event_history"),3);EXPECT_EQ(count("events"),3);
 EXPECT_THROW(src::sql(events,"DELETE FROM windows_activity_records"),std::runtime_error);
}
TEST_F(WindowsActivityImportTest, ParserFailureIsUnknownAndRecoveredRecordsStaySeparate){
 src::sql(win,"UPDATE prefetch_files SET parse_status='error';INSERT INTO event_logs(record_id,event_id,timestamp,message,source_path,is_recovered) VALUES(20,2,1700000002,'恢复记录','/log.evtx',1)");
 auto value=run();ASSERT_TRUE(value["success"]);EXPECT_FALSE(value["complete"]);EXPECT_EQ(value["failed_records"],1);EXPECT_EQ(count("events"),2);
 src::Statement s(events,"SELECT event_type FROM events WHERE event_type LIKE '%RECOVERED'");EXPECT_EQ(sqlite3_step(s.value),SQLITE_ROW);
}
TEST_F(WindowsActivityImportTest, MidImportFailureRollsBackWholeProjection){
 auto old=run();src::sql(win,"UPDATE event_logs SET message='changed'");
 src::sql(events,"CREATE TRIGGER reject_import BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'injected failure'); END;");
 auto value=run();EXPECT_FALSE(value["success"]);EXPECT_EQ(count("events"),3);EXPECT_EQ(count("windows_activity_sets"),1);EXPECT_EQ(count("windows_activity_records"),4);EXPECT_EQ(count("windows_event_history"),0);
 src::sql(events,"DROP TRIGGER reject_import");EXPECT_TRUE(run()["success"]);
}
TEST_F(WindowsActivityImportTest, MissingAndIncompatibleTablesRemainVisible){
 src::sql(win,"DROP TABLE browser_history;DROP TABLE browser_logins;CREATE TABLE browser_logins(id INTEGER)");
 auto value=run();ASSERT_TRUE(value["success"]);EXPECT_FALSE(value["complete"]);EXPECT_EQ(value["tables"]["browser_history"]["status"],"missing_table");EXPECT_EQ(value["tables"]["browser_logins"]["status"],"incompatible_schema");
}
TEST_F(WindowsActivityImportTest, OtherTaskCannotReplaceCurrentProjection){
 ASSERT_TRUE(run()["success"]);auto value=wa::importArtifacts(events,nullptr,(dir/"windows.db").string(),"other");EXPECT_FALSE(value["success"]);EXPECT_EQ(count("events"),3);
}
TEST_F(WindowsActivityImportTest, BlobBytesAndEmbeddedNullsParticipateInSourceRevision){
 src::sql(win,"INSERT INTO browser_logins(url,username,date_last_used,encrypted_password) VALUES('https://test','u',1700000000,X'006162')");
 auto first=run();ASSERT_TRUE(first["success"]);
 src::sql(win,"UPDATE browser_logins SET encrypted_password=X'006163'");
 auto second=run();ASSERT_TRUE(second["success"]);EXPECT_NE(first["result_set_id"],second["result_set_id"]);
 src::Statement record(events,"SELECT record_json FROM windows_activity_records WHERE source_table='browser_logins' ORDER BY record_id DESC LIMIT 1");
 ASSERT_EQ(sqlite3_step(record.value),SQLITE_ROW);auto fields=wa::json::parse(reinterpret_cast<const char*>(sqlite3_column_text(record.value,0)));
 EXPECT_EQ(fields["fields"]["encrypted_password"]["bytes"],"006163");
}
TEST_F(WindowsActivityImportTest, EventSeverityFollowsKnownLevelAndUnknownStaysUnknown){
 src::sql(win,"UPDATE event_logs SET level='2'");ASSERT_TRUE(run()["success"]);
 src::Statement s(events,"SELECT severity FROM events WHERE event_type='WINDOWS_EVENT_RECORD'");ASSERT_EQ(sqlite3_step(s.value),SQLITE_ROW);EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(s.value,0)),"ERROR");
 EXPECT_EQ(wa::eventSeverity({{"level","unrecognized"}}),"UNKNOWN");EXPECT_EQ(wa::eventSeverity({{"level",1}}),"CRITICAL");
}
TEST_F(WindowsActivityImportTest, PartialAndMetadataOnlyKeepDifferentCoverageStates){
 src::sql(win,"UPDATE prefetch_files SET parse_status='partial'");auto partial=run();ASSERT_TRUE(partial["success"]);EXPECT_FALSE(partial["complete"]);EXPECT_EQ(partial["failed_records"],0);EXPECT_EQ(partial["partial_records"],1);EXPECT_EQ(count("events"),3);
 src::sql(win,"UPDATE prefetch_files SET parse_status='metadata_only'");auto empty=run();ASSERT_TRUE(empty["success"]);EXPECT_EQ(empty["failed_records"],0);EXPECT_EQ(empty["tables"]["prefetch_files"]["ignored"],1);EXPECT_EQ(count("events"),1);
}
