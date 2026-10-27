#pragma once
#include "DatabaseManager/SourceIndex.h"
#include <algorithm>
#include <memory>
#include <set>
#include <cctype>

// The events table is the current timeline projection. Immutable source rows
// and superseded event projections are retained here for historical references.
namespace forensics::windows_activity {
using sources::json;using sources::Statement;
inline constexpr const char* version="windows-activity:v1";
inline void done(sqlite3* db,sqlite3_stmt* s){if(sqlite3_step(s)!=SQLITE_DONE)throw std::runtime_error(sqlite3_errmsg(db));}
inline void schema(sqlite3* db){sources::sql(db,R"SQL(
 CREATE TABLE IF NOT EXISTS windows_activity_sets(result_set_id TEXT PRIMARY KEY,task_id TEXT NOT NULL,source_revision TEXT NOT NULL,import_version TEXT NOT NULL,coverage_json TEXT NOT NULL,created_at INTEGER NOT NULL);
 CREATE TABLE IF NOT EXISTS windows_activity_records(record_id INTEGER PRIMARY KEY AUTOINCREMENT,result_set_id TEXT NOT NULL,source_table TEXT NOT NULL,source_row_id INTEGER NOT NULL,record_hash TEXT NOT NULL,record_json TEXT NOT NULL,UNIQUE(result_set_id,source_table,source_row_id));
 CREATE TABLE IF NOT EXISTS windows_activity_current(task_id TEXT PRIMARY KEY,result_set_id TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS windows_event_history(import_key TEXT PRIMARY KEY,result_set_id TEXT NOT NULL,event_json TEXT NOT NULL);
 CREATE TABLE IF NOT EXISTS windows_activity_import_runs(id INTEGER PRIMARY KEY,task_id TEXT NOT NULL,status TEXT NOT NULL,result_set_id TEXT,coverage_json TEXT NOT NULL,created_at INTEGER NOT NULL);
 CREATE TRIGGER IF NOT EXISTS windows_records_no_update BEFORE UPDATE ON windows_activity_records BEGIN SELECT RAISE(ABORT,'immutable Windows source record'); END;
 CREATE TRIGGER IF NOT EXISTS windows_records_no_delete BEFORE DELETE ON windows_activity_records BEGIN SELECT RAISE(ABORT,'immutable Windows source record'); END;
 CREATE TRIGGER IF NOT EXISTS windows_sets_no_update BEFORE UPDATE ON windows_activity_sets BEGIN SELECT RAISE(ABORT,'immutable Windows result set'); END;
 CREATE TRIGGER IF NOT EXISTS windows_sets_no_delete BEFORE DELETE ON windows_activity_sets BEGIN SELECT RAISE(ABORT,'immutable Windows result set'); END;
 )SQL");}
inline std::string str(const json& r,const std::string& k){return r.contains(k)&&r[k].is_string()?r[k].get<std::string>():"";}
inline int64_t number(const json& r,const std::string& k){return r.contains(k)&&r[k].is_number_integer()?r[k].get<int64_t>():0;}
inline std::string eventSeverity(const json& fields){
    auto level=str(fields,"level");std::transform(level.begin(),level.end(),level.begin(),[](unsigned char c){return std::tolower(c);});
    if(level.empty() && fields.contains("level") && fields["level"].is_number_integer())level=fields["level"].dump();
    if(level=="1" || level=="critical")return "CRITICAL";
    if(level=="2" || level=="error")return "ERROR";
    if(level=="3" || level=="warning")return "WARNING";
    if(level=="0" || level=="4" || level=="5" || level=="logalways" || level=="information" || level=="informational" || level=="verbose")return "INFO";
    return "UNKNOWN";
}
inline json sourceFields(sqlite3_stmt* statement){
    json result=json::object();
    for(int i=0;i<sqlite3_column_count(statement);++i){const auto name=sqlite3_column_name(statement,i);const auto type=sqlite3_column_type(statement,i);
        if(type==SQLITE_NULL){result[name]=nullptr;continue;}
        if(type==SQLITE_INTEGER){result[name]=sqlite3_column_int64(statement,i);continue;}
        if(type==SQLITE_FLOAT){result[name]=sqlite3_column_double(statement,i);continue;}
        const auto* bytes=static_cast<const unsigned char*>(sqlite3_column_blob(statement,i));const auto length=sqlite3_column_bytes(statement,i);
        if(type==SQLITE_TEXT){std::string value(reinterpret_cast<const char*>(bytes?bytes:reinterpret_cast<const unsigned char*>("")),length);
            try{json(value).dump();result[name]=value;continue;}catch(...){} }
        std::string hex;const char* digits="0123456789abcdef";for(int j=0;j<length;++j){hex+=digits[bytes[j]>>4];hex+=digits[bytes[j]&15];}
        result[name]={{"encoding","hex"},{"sqlite_type",type==SQLITE_TEXT?"text_invalid_utf8":"blob"},{"bytes",hex}};
    }return result;
}
inline json location(sqlite3* raw,const std::string& path){
    json value={{"path",path},{"source_id",nullptr},{"binding_status","unresolved"}};
    if(!raw || path.empty() || !sources::table(raw,"source_objects"))return value;
    Statement s(raw,"SELECT source_id,locator_json FROM source_objects WHERE path=? ORDER BY source_id LIMIT 2");s.bind(1,path);
    if(sqlite3_step(s.value)!=SQLITE_ROW)return value;
    auto id=std::string(reinterpret_cast<const char*>(sqlite3_column_text(s.value,0)));
    auto locator=json::parse(reinterpret_cast<const char*>(sqlite3_column_text(s.value,1)));
    if(sqlite3_step(s.value)==SQLITE_ROW){value["binding_status"]="ambiguous";return value;}
    value["source_id"]=id;value["locator"]=locator;value["binding_status"]="unique";return value;
}
struct Mapping {std::string table,type,time,path,basis,label;std::vector<std::string> required;};
inline const std::vector<Mapping>& mappings(){static const std::vector<Mapping> list={
 {"event_logs","WINDOWS_EVENT_RECORD","timestamp","source_path","event_system_time","Windows事件日志记录",{"record_id","event_id","level","timestamp","source","message","parse_status","source_path","is_recovered"}},
 {"prefetch_files","PREFETCH_EXECUTION","last_run_time","file_path","prefetch_execution_filetime","Prefetch运行记录",{"file_path","executable_name","run_count","last_run_time","all_run_times","raw_run_times","parse_status"}},
 {"browser_history","WEB_HISTORY","visit_time","","browser_visit_time","浏览器访问记录",{"url","title","visit_time","browser_name","profile_name"}},
 {"browser_downloads","WEB_DOWNLOAD","start_time","","download_start_time","浏览器下载开始记录",{"url","file_name","file_size","start_time","target_path"}},
 {"browser_logins","BROWSER_CREDENTIAL_USE","date_last_used","","credential_entry_last_used","浏览器账户条目使用时间；不能据此确认登录成功",{"url","username","date_last_used"}},
 {"windows_services","WINDOWS_SERVICE_CONFIG","","","offline_configuration","Windows服务配置；离线配置不能证实正在运行",{"service_name","display_name","image_path","is_running"}},
 {"scheduled_tasks","SCHEDULED_TASK_CONFIG","","","offline_configuration","计划任务配置；计划时间不等于实际执行",{"task_name","task_path","action_path","next_run_time"}},
 {"usb_devices","USB_REGISTRY_OBSERVATION","first_connected","","registry_device_connection_time","USB注册表连接时间记录",{"serial_number","device_description","first_connected","last_connected"}},
 {"recycle_bin","RECYCLE_BIN_DELETION","deletion_time","recycle_file_path","recycle_bin_deletion_time","回收站删除时间记录",{"recycle_file_path","original_path","original_size","deletion_time"}},
 {"amcache_entries","AMCACHE_FILE_METADATA","last_modified","","cached_file_modification_time","Amcache文件元数据；缓存存在不能证明程序执行",{"file_path","file_hash","last_modified","file_size"}}
 };return list;}
inline json importArtifacts(sqlite3* events,sqlite3* raw,const std::string& windowsDb,const std::string& task){
    json report={{"version",version},{"task_id",task},{"success",false},{"complete",false},{"tables",json::object()}};
    bool attached=false,transaction=false;
    try{
        if(!events || !std::filesystem::is_regular_file(windowsDb))throw std::runtime_error("WINDOWS_DATABASE_MISSING");
        schema(events);sqlite3_busy_timeout(events,10000);
        {Statement owner(events,"SELECT 1 FROM windows_activity_current WHERE task_id<>? LIMIT 1");owner.bind(1,task);if(sqlite3_step(owner.value)==SQLITE_ROW)throw std::runtime_error("WINDOWS_TASK_MISMATCH");}
        {Statement attach(events,"ATTACH DATABASE ? AS win_activity_source");attach.bind(1,windowsDb);done(events,attach.value);attached=true;}
        sources::sql(events,"BEGIN IMMEDIATE");transaction=true;
        std::string revision="unbound";
        if(raw && sources::table(raw,"source_index_meta")){Statement s(raw,"SELECT value FROM source_index_meta WHERE key='revision'");if(sqlite3_step(s.value)==SQLITE_ROW)revision=reinterpret_cast<const char*>(sqlite3_column_text(s.value,0));}
        std::vector<json> records;std::string digest=std::string(version)+":"+task+":"+revision;bool complete=true;
        size_t valid=0,undated=0,failed=0,partial=0,knownTables=0;
        for(const auto& m:mappings()){
            json count={{"input",0},{"valid",0},{"undated",0},{"ignored",0},{"failed",0},{"partial",0},{"timeline_events",0},{"status","empty"}};
            std::set<std::string> columns;
            {Statement s(events,"PRAGMA win_activity_source.table_info("+m.table+")");while(sqlite3_step(s.value)==SQLITE_ROW)columns.insert(reinterpret_cast<const char*>(sqlite3_column_text(s.value,1)));}
            if(columns.empty()){count["status"]="missing_table";complete=false;report["tables"][m.table]=count;digest+=m.table+":missing";continue;}
            std::vector<std::string> missing;for(const auto& key:m.required)if(!columns.count(key))missing.push_back(key);
            if(!missing.empty()){count["status"]="incompatible_schema";count["missing_columns"]=missing;complete=false;report["tables"][m.table]=count;digest+=m.table+":incompatible:"+json(missing).dump();continue;}
            ++knownTables;
            std::string query="SELECT rowid AS source_row_id";
            for(const auto& column:columns)if(column.rfind("llm_",0)!=0)query+=",\""+column+"\"";
            query+=" FROM win_activity_source."+m.table+" ORDER BY rowid";
            Statement s(events,query);int rc;
            while((rc=sqlite3_step(s.value))==SQLITE_ROW){
                auto fields=sourceFields(s.value);const auto rowid=number(fields,"source_row_id");fields.erase("source_row_id");
                count["input"]=count["input"].get<size_t>()+1;
                const auto status=columns.count("parse_status")?str(fields,"parse_status"):"ok";
                const bool usable=status=="ok" || status=="partial";
                json times=json::array();
                if(usable && m.table=="prefetch_files"){
                    const auto parsed=json::parse(str(fields,"all_run_times"),nullptr,false);
                    const auto original=json::parse(str(fields,"raw_run_times"),nullptr,false);
                    if(parsed.is_array())for(size_t i=0;i<parsed.size();++i)if(parsed[i].is_number_integer()&&parsed[i].get<int64_t>()>0)
                        times.push_back({{"timestamp",parsed[i]},{"slot",i},{"raw_time",original.is_array()&&i<original.size()?original[i]:json(nullptr)}});
                }else if(usable && !m.time.empty() && number(fields,m.time)>0){
                    times.push_back({{"timestamp",fields[m.time]},{"slot",m.time},{"raw_time",m.table=="event_logs"?fields.value("raw_timestamp",json(nullptr)):fields[m.time]}});
                }
                if(usable && m.table=="usb_devices" && number(fields,"last_connected")>0 && number(fields,"last_connected")!=number(fields,"first_connected"))
                    times.push_back({{"timestamp",fields["last_connected"]},{"slot","last_connected"},{"raw_time",fields["last_connected"]}});
                if(status=="partial"){++partial;complete=false;count["partial"]=count["partial"].get<size_t>()+1;}
                if(status=="metadata_only"){count["ignored"]=count["ignored"].get<size_t>()+1;}
                else if(!usable){++failed;complete=false;count["failed"]=count["failed"].get<size_t>()+1;}
                else if(times.empty()){++undated;count["undated"]=count["undated"].get<size_t>()+1;}
                else {++valid;count["valid"]=count["valid"].get<size_t>()+1;}
                std::string path=m.path.empty()?"":str(fields,m.path);
                auto record=json{{"source_table",m.table},{"source_row_id",rowid},{"fields",fields},{"parser_status",status},
                    {"source",location(raw,path)},{"event_type",m.type},{"observation",m.label},{"time_basis",m.basis},
                    {"timestamp_timezone","UTC"},{"timestamp_precision","seconds"},{"times",times},
                    {"is_recovered",m.table=="event_logs"&&number(fields,"is_recovered")!=0}};
                if(record["is_recovered"].get<bool>())record["event_type"]=m.type+"_RECOVERED";
                record["severity"]=m.table=="event_logs"?eventSeverity(fields):"INFO";
                record["event_category"]=m.table.rfind("browser_",0)==0?"USER_ACTIVITY":m.table=="prefetch_files"?"APPLICATION_EVENT":m.table=="recycle_bin"?"FILE_OPERATION":"SYSTEM_ACTIVITY";
                auto hash=sources::hash(record.dump());record["record_hash"]=hash;digest+=m.table+":"+std::to_string(rowid)+":"+hash;
                count["timeline_events"]=count["timeline_events"].get<size_t>()+times.size();records.push_back(std::move(record));
            }
            if(rc!=SQLITE_DONE)throw std::runtime_error(sqlite3_errmsg(events));
            if(count["input"].get<size_t>())count["status"]=(count["failed"].get<size_t>() || count["partial"].get<size_t>())?"partial":"ok";
            report["tables"][m.table]=count;
        }
        if(!knownTables)throw std::runtime_error("WINDOWS_SCHEMA_UNSUPPORTED");
        {Statement exists(events,"SELECT 1 FROM win_activity_source.sqlite_master WHERE name='parser_outcomes' AND type='table'");
         if(sqlite3_step(exists.value)==SQLITE_ROW){
            json outcomes=json::array();Statement rows(events,"SELECT source_path,parser,status,diagnostic,record_count,recovered_count FROM win_activity_source.parser_outcomes ORDER BY source_path,parser,status,diagnostic,record_count,recovered_count");int rc;
            while((rc=sqlite3_step(rows.value))==SQLITE_ROW){auto value=sources::row(rows.value);outcomes.push_back(value);if(str(value,"status")=="error" || str(value,"status")=="unsupported")complete=false;}
            if(rc!=SQLITE_DONE)throw std::runtime_error(sqlite3_errmsg(events));report["parser_outcomes"]=outcomes;digest+=outcomes.dump();
         }else {report["parser_outcomes_status"]="unavailable";complete=false;}}
        const auto result=sources::hash(digest);report["result_set_id"]=result;
        report["valid_records"]=valid;report["undated_records"]=undated;report["failed_records"]=failed;report["partial_records"]=partial;
        report["complete"]=complete;report["success"]=true;
        report["limitations"]={"仅导入已实现的工件类型；无时间配置不进入活动时间线","MFT解析上限为100000；MFT与未支持工件不在本导入覆盖范围","回收EVTX记录带回收标记，不与标准可见记录混计"};
        std::string current;
        {Statement s(events,"SELECT result_set_id FROM windows_activity_current WHERE task_id=?");s.bind(1,task);if(sqlite3_step(s.value)==SQLITE_ROW)current=reinterpret_cast<const char*>(sqlite3_column_text(s.value,0));}
        report["reused"]=current==result;
        if(current!=result){
            {Statement s(events,"INSERT OR IGNORE INTO windows_activity_sets VALUES(?,?,?,?,?,strftime('%s','now'))");s.bind(1,result);s.bind(2,task);s.bind(3,revision);s.bind(4,version);s.bind(5,report.dump());done(events,s.value);}
            // Archive only this importer's previous projection. Source records
            // and analysis records are never deleted or overwritten.
            {Statement old(events,"SELECT * FROM events WHERE source_id LIKE 'winactivity:%'");
             int rc;while((rc=sqlite3_step(old.value))==SQLITE_ROW){auto r=sources::row(old.value);Statement save(events,"INSERT OR IGNORE INTO windows_event_history VALUES(?,?,?)");save.bind(1,str(r,"source_id"));save.bind(2,current);save.bind(3,r.dump());done(events,save.value);}if(rc!=SQLITE_DONE)throw std::runtime_error(sqlite3_errmsg(events));}
            sources::sql(events,"DELETE FROM events WHERE source_id LIKE 'winactivity:%'");
            for(auto record:records){
                auto hash=str(record,"record_hash");record.erase("record_hash");
                Statement s(events,"INSERT OR IGNORE INTO windows_activity_records(result_set_id,source_table,source_row_id,record_hash,record_json) VALUES(?,?,?,?,?)");
                s.bind(1,result);s.bind(2,str(record,"source_table"));sqlite3_bind_int64(s.value,3,number(record,"source_row_id"));s.bind(4,hash);s.bind(5,record.dump());done(events,s.value);
                int64_t recordId=0;{Statement find(events,"SELECT record_id FROM windows_activity_records WHERE result_set_id=? AND source_table=? AND source_row_id=?");find.bind(1,result);find.bind(2,str(record,"source_table"));sqlite3_bind_int64(find.value,3,number(record,"source_row_id"));if(sqlite3_step(find.value)!=SQLITE_ROW)throw std::runtime_error("WINDOWS_RECORD_WRITE_FAILED");recordId=sqlite3_column_int64(find.value,0);}
                for(const auto& time:record["times"]){
                    const auto key="winactivity:"+sources::hash(result+":"+std::to_string(recordId)+":"+time.at("slot").dump());
                    const auto fields=record["fields"];std::string description=str(record,"observation");
                    // Describe observed fields, never infer a successful login or execution from configuration.
                    for(const auto& [field,label]:std::vector<std::pair<std::string,std::string>>{{"source","提供程序"},{"event_id","事件编号"},{"executable_name","程序名"},{"url","网址"},{"title","标题"},{"file_name","文件名"},{"original_path","原路径"},{"serial_number","序列号"},{"message","原始事件内容"}})
                        if(fields.contains(field)&&!fields[field].is_null())description+="；"+label+"="+(fields[field].is_string()?fields[field].get<std::string>():fields[field].dump());
                    json context={{"task_id",task},{"result_set_id",result},{"record_id",recordId},{"record_hash",hash},{"time",time},{"time_basis",record["time_basis"]},{"source",record["source"]},{"is_recovered",record["is_recovered"]}};
                    Statement insert(events,"INSERT INTO events(timestamp,event_type,file_path,inode,description,file_size,file_type,system_context,priority,severity,event_source,event_category,normalized_type,source_id) VALUES(?,?,?,0,?,0,'WINDOWS_ARTIFACT',?,'LOW',?,'WINDOWS_ACTIVITY',?,?,?)");
                    sqlite3_bind_int64(insert.value,1,number(time,"timestamp"));insert.bind(2,str(record,"event_type"));insert.bind(3,str(record["source"],"path"));insert.bind(4,description);insert.bind(5,context.dump());insert.bind(6,str(record,"severity"));insert.bind(7,str(record,"event_category"));insert.bind(8,str(record,"event_type"));insert.bind(9,key);done(events,insert.value);
                }
            }
            Statement s(events,"INSERT INTO windows_activity_current VALUES(?,?) ON CONFLICT(task_id) DO UPDATE SET result_set_id=excluded.result_set_id");s.bind(1,task);s.bind(2,result);done(events,s.value);
        }
        {Statement s(events,"INSERT INTO windows_activity_import_runs(task_id,status,result_set_id,coverage_json,created_at) VALUES(?,?,?,?,strftime('%s','now'))");s.bind(1,task);s.bind(2,complete?"completed":"partial");s.bind(3,result);s.bind(4,report.dump());done(events,s.value);}
        sources::sql(events,"COMMIT");transaction=false;sources::sql(events,"DETACH DATABASE win_activity_source");attached=false;
    }catch(const std::exception& e){
        if(transaction)sqlite3_exec(events,"ROLLBACK",nullptr,nullptr,nullptr);
        if(attached)sqlite3_exec(events,"DETACH DATABASE win_activity_source",nullptr,nullptr,nullptr);
        report["success"]=false;report["complete"]=false;report["rolled_back"]=transaction;
        report["error_code"]="WINDOWS_ACTIVITY_IMPORT_FAILED";report["error"]=e.what();
        try{if(events && sources::table(events,"windows_activity_import_runs")){
            Statement failure(events,"INSERT INTO windows_activity_import_runs(task_id,status,result_set_id,coverage_json,created_at) VALUES(?,'failed',?,?,strftime('%s','now'))");
            failure.bind(1,task);failure.bind(2,report.value("result_set_id",std::string()));failure.bind(3,report.dump());done(events,failure.value);
        }}catch(...){/* The task audit retains the failure if the store is locked. */}
    }
    return report;
}
}
