#include "HarmonyArtifactParsers.h"
#include "HarmonyBackupExtractor.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileBackupSchema.h"
#include <fstream>
#include <iostream>
#include <array>
#include <memory>
#include <set>
#include <chrono>
#include <openssl/evp.h>

namespace fs = std::filesystem;
using json = nlohmann::json;
namespace {
using Connection = std::unique_ptr<sqlite3, decltype(&sqlite3_close)>;
using Statement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;
std::string quote(const std::string& s) {
    std::string out = "\""; for (char c : s) { out += c; if (c == '"') out += c; } return out + '"';
}
std::string text(sqlite3_stmt* s, int i) {
    const auto* p = sqlite3_column_text(s, i); return p ? reinterpret_cast<const char*>(p) : "";
}
Statement prepare(sqlite3* db, const std::string& sql) {
    sqlite3_stmt* s = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &s, nullptr) != SQLITE_OK)
        throw std::runtime_error(sqlite3_errmsg(db));
    return Statement(s, sqlite3_finalize);
}
void bindText(sqlite3_stmt* s, int i, const std::string& v) { sqlite3_bind_text(s,i,v.c_str(),-1,SQLITE_TRANSIENT); }
std::string serialized(const json& j) { return j.dump(-1, ' ', false, json::error_handler_t::replace); }
std::string scalar(const json& j, const char* key) {
    if (!j.contains(key) || j[key].is_null()) return {};
    return j[key].is_string() ? j[key].get<std::string>() : j[key].dump();
}
json row(sqlite3_stmt* s) {
    json j = json::object();
    for (int i=0;i<sqlite3_column_count(s);++i) {
        const std::string name=sqlite3_column_name(s,i);
        switch(sqlite3_column_type(s,i)) {
            case SQLITE_NULL: j[name]=nullptr; break;
            case SQLITE_INTEGER: j[name]=sqlite3_column_int64(s,i); break;
            case SQLITE_FLOAT: j[name]=sqlite3_column_double(s,i); break;
            case SQLITE_BLOB: j[name]={{"type","blob"},{"bytes",sqlite3_column_bytes(s,i)},{"decoded",false}}; break;
            default: j[name]=text(s,i); break;
        }
    }
    return j;
}
struct Rule { std::string table,kind,time; };
std::vector<Rule> rules(const HarmonyBackupExtractor::Entry& e) {
    const auto name=fs::path(e.originalPath).filename().string();
    if(e.bundle=="com.huawei.hmos.calendardata" && name=="calendardata.db") return {{"Events","calendar","dtstart"}};
    if(e.bundle=="com.huawei.hmos.soundrecorder" && name=="recorderSound.db") return {{"normal_record_table","recording","date_added"}};
    if(e.bundle=="com.huawei.hmos.callrecorder" && name=="call_record.db") return {{"record_log","call_recording","date_added"}};
    if(e.bundle=="com.ohos.medialibrary.medialibrarydata" && name=="media_library.db") return {{"Photos","media","date_taken"},{"Files","media_file","date_taken"}};
    if(e.bundle=="com.huawei.hmos.notepad" && name=="notepad.db") return {{"note","note","create_time"},{"todo","todo","create_time"},{"content","note_content",""}};
    if(e.bundle=="org.b3log.siyuan.ho" && name=="siyuan.db") return {{"blocks","note_block","created"}};
    // Legacy migrated QQ data; NT/SQLCipher messages are inventoried separately.
    if(e.bundle=="com.tencent.mqq" && name.ends_with(".db") && name.size()>3 &&
       name.substr(0,name.size()-3).find_first_not_of("0123456789")==std::string::npos)
        return {{"Friends","qq_contact",""},{"TroopInfoV2","qq_group",""},{"recent","qq_recent","lastmsgtime"}};
    return {};
}
bool primaryDatabase(const std::string& p) {
    return p.ends_with(".db") || p.ends_with(".sqlite") || p.ends_with(".sqlite3") || p.ends_with(".sqlitedb");
}
int budget(void* ptr) { auto& n=*static_cast<int*>(ptr); return --n<=0; }
}

bool analyzeHarmonyBackup(HarmonyBackupExtractor& source, AndroidAnalysisDatabase& output, const fs::path& temporaryRoot) {
    const char* schema = mobile_backup_schema::DDL;
    auto* dest=output.handle();
    if(sqlite3_exec(dest,schema,nullptr,nullptr,nullptr)!=SQLITE_OK) return false;
    if(!output.beginTransaction()) return false;
    try {
        // Re-running the same source replaces derived records; never accumulate duplicates.
        if(sqlite3_exec(dest,"DELETE FROM mobile_artifacts; DELETE FROM installed_apps; DELETE FROM app_db_inventory;"
            "DELETE FROM android_source_coverage; DELETE FROM android_source_provenance;",nullptr,nullptr,nullptr)!=SQLITE_OK)
            throw std::runtime_error("HARMONY_RESULT_RESET_FAILED");
        const auto& meta=source.manifest();
        auto ms=prepare(dest,"INSERT OR REPLACE INTO mobile_backup_manifest VALUES(1,?,?,?,?,?,?,?)");
        bindText(ms.get(),1,"HarmonyOS");bindText(ms.get(),2,meta.value("device",""));bindText(ms.get(),3,meta.value("backup_version",""));
        sqlite3_bind_int64(ms.get(),4,meta.value("backup_time_ms",0LL));sqlite3_bind_int64(ms.get(),5,meta["modules"].size());
        bindText(ms.get(),6,meta.value("manifest_sha256",""));bindText(ms.get(),7,"harmony-decrypted-v1");
        if(sqlite3_step(ms.get())!=SQLITE_DONE) throw std::runtime_error("HARMONY_MANIFEST_WRITE_FAILED");
        for(const auto& app:meta["modules"])
            if(!output.insertInstalledApp(app.value("bundle",""),app.value("name",""),
                std::to_string(app.value("version_code",0LL)),app.value("version",""),
                app.value("declared_size",0LL),0,0,serialized(app))) throw std::runtime_error("HARMONY_APP_WRITE_FAILED");
        for(const auto& c:source.coverage()) output.recordSourceCoverage("backup_module",c["path"],c["status"],c["detail"]);
        std::size_t serial=0, totalRows=0;
        auto insert=prepare(dest,"INSERT OR REPLACE INTO mobile_artifacts(kind,package_name,app_index,source_path,source_table,"
            "source_key,record_json,timestamp_raw,time_unit,timestamp_seconds,source_db_sha256,source_wal_sha256,parser_version,related_path,related_status) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)");
        for(const auto& [path,e]:source.entries()) {
            if(!primaryDatabase(path)) continue;
            if(e.size>(256ULL<<20)) { output.recordSourceCoverage("database",path,"UNSUPPORTED","database_size_limit");continue; }
            const auto local=temporaryRoot/("harmony-db-"+std::to_string(++serial)+".db");
            struct Cleanup { fs::path p; ~Cleanup(){for(const char* s:{"","-wal","-shm","-journal"}) {std::error_code ec;fs::remove(p.string()+s,ec);}} } cleanup{local};
            if(!source.extractFileByPath(path,local.string())) {
                if(source.error()=="CANCELLED" || source.error().starts_with("EVIDENCE_CHANGED")) throw std::runtime_error(source.error());
                output.recordSourceCoverage("database",path,"EXTRACT_FAILED",source.error());continue;
            }
            std::array<char,16> magic{};std::ifstream probe(local,std::ios::binary);probe.read(magic.data(),magic.size());probe.close();
            if(std::string(magic.data(),16)!=std::string("SQLite format 3\0",16)) {
                const std::string status=std::string(magic.data(),7)=="unqlite"?"unsupported_format":"encrypted_or_unsupported";
                output.insertAppDbInventory(e.bundle,path,"",0,"[]",status);
                output.recordSourceCoverage("database",path,"UNSUPPORTED",status+"; non-SQLite header is not proof of encryption");continue;
            }
            bool sidecarsOk=true;
            for(const char* suffix:{"-wal","-shm","-journal"}) {
                auto side=source.entries().find(path+suffix);
                if(side==source.entries().end()) continue;
                if(side->second.size>(256ULL<<20) || !source.extractFileByPath(path+suffix,local.string()+suffix)) sidecarsOk=false;
            }
            if(!sidecarsOk) {
                if(source.error()=="CANCELLED" || source.error().starts_with("EVIDENCE_CHANGED")) throw std::runtime_error(source.error());
                output.recordSourceCoverage("database",path,"EXTRACT_FAILED","incomplete_sqlite_bundle");continue;
            }
            sqlite3* raw=nullptr;
            int rc=sqlite3_open_v2(local.string().c_str(),&raw,SQLITE_OPEN_READONLY,nullptr);Connection db(raw,sqlite3_close);
            if(rc!=SQLITE_OK) {output.recordSourceCoverage("database",path,"ERROR","sqlite_open_failed");continue;}
            sqlite3_exec(db.get(),"PRAGMA query_only=ON; PRAGMA trusted_schema=OFF;",nullptr,nullptr,nullptr);
            sqlite3_limit(db.get(),SQLITE_LIMIT_LENGTH,8<<20);sqlite3_limit(db.get(),SQLITE_LIMIT_COLUMN,2048);
            int instructions=20000;sqlite3_progress_handler(db.get(),1000,budget,&instructions);
            try {
                auto tables=prepare(db.get(),"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 10001");
                std::set<std::string> names;
                std::size_t unavailableTables=0;
                while((rc=sqlite3_step(tables.get()))==SQLITE_ROW) {
                    const auto table=text(tables.get(),0); if(names.size()>=10000) throw std::runtime_error("table_limit");names.insert(table);
                    try {
                        json cols=json::array();auto cs=prepare(db.get(),"PRAGMA table_info("+quote(table)+")");
                        while(sqlite3_step(cs.get())==SQLITE_ROW) cols.push_back(text(cs.get(),1));
                        auto count=prepare(db.get(),"SELECT COUNT(*) FROM "+quote(table));
                        if(sqlite3_step(count.get())!=SQLITE_ROW) throw std::runtime_error("inventory_query_limit_or_error");
                        if(!output.insertAppDbInventory(e.bundle,path,table,sqlite3_column_int64(count.get(),0),serialized(cols),"readable"))
                            throw std::runtime_error("RESULT_WRITE_FAILED: inventory");
                    } catch(const std::exception& ex) {
                        if(std::string(ex.what()).starts_with("RESULT_WRITE_FAILED")) throw;
                        ++unavailableTables;
                        // Missing FTS modules/custom collations affect an index, not
                        // necessarily the ordinary business tables in the same DB.
                        auto missing=prepare(dest,"INSERT INTO app_db_inventory(package_name,db_path,table_name,row_count,columns,open_status) "
                            "VALUES(?,?,?,NULL,?,'unsupported_table')");
                        bindText(missing.get(),1,e.bundle);bindText(missing.get(),2,path);bindText(missing.get(),3,table);
                        bindText(missing.get(),4,serialized(json{{"error",ex.what()}}));
                        if(sqlite3_step(missing.get())!=SQLITE_DONE)throw std::runtime_error("RESULT_WRITE_FAILED: inventory");
                    }
                }
                if(rc!=SQLITE_DONE) throw std::runtime_error("schema_read_failed");
                output.recordSourceCoverage("database",path,unavailableTables?"PARTIAL":"parsed",
                    "schema_inventory; unavailable_tables="+std::to_string(unavailableTables)+"; business_semantics_separately_reported");
                const auto dbHash=HarmonyBackupExtractor::sha256(local);
                const auto wal=fs::path(local.string()+"-wal");const auto walHash=fs::exists(wal)?HarmonyBackupExtractor::sha256(wal):"";
                for(const auto& rule:rules(e)) {
                    if(!names.count(rule.table)) {output.recordSourceCoverage(rule.kind,path,"UNSUPPORTED","expected_table_missing: "+rule.table);continue;}
                    auto columns=prepare(db.get(),"PRAGMA table_info("+quote(rule.table)+")");std::vector<std::string> keys;
                    while(sqlite3_step(columns.get())==SQLITE_ROW) if(sqlite3_column_int(columns.get(),5)) keys.push_back(text(columns.get(),1));
                    std::string select=keys.empty()?"SELECT rowid AS __source_rowid__,* FROM ":"SELECT * FROM ";
                    auto rows=prepare(db.get(),select+quote(rule.table)+" LIMIT 50001");std::size_t parsed=0;
                    while((rc=sqlite3_step(rows.get()))==SQLITE_ROW) {
                        if(parsed>=50000 || totalRows>=200000) throw std::runtime_error("artifact_row_limit");
                        auto record=row(rows.get());json key=json::object();
                        if(keys.empty()) key["rowid"]=record["__source_rowid__"];
                        else for(const auto& k:keys) key[k]=record[k];
                        auto rawTime=rule.time.empty()?"":scalar(record,rule.time.c_str());
                        std::string unit="unknown";std::int64_t seconds=0;
                        if(rule.kind=="note_block") unit="local_datetime_timezone_unknown";
                        else if(!rawTime.empty()) {
                            try {std::size_t end=0;auto n=std::stoll(rawTime,&end);if(end!=rawTime.size())throw std::runtime_error("not_numeric");
                                if(n>=1000000000000LL && n<4102444800000LL){seconds=n/1000;unit="epoch_ms";}
                                else if(n>=1000000000LL && n<4102444800LL){seconds=n;unit="epoch_s";}} catch(...) {}
                        }
                        sqlite3_reset(insert.get());sqlite3_clear_bindings(insert.get());
                        bindText(insert.get(),1,rule.kind);bindText(insert.get(),2,e.bundle);sqlite3_bind_int(insert.get(),3,e.appIndex);
                        bindText(insert.get(),4,path);bindText(insert.get(),5,rule.table);bindText(insert.get(),6,serialized(key));bindText(insert.get(),7,serialized(record));
                        bindText(insert.get(),8,rawTime);bindText(insert.get(),9,unit);if(seconds)sqlite3_bind_int64(insert.get(),10,seconds);else sqlite3_bind_null(insert.get(),10);
                        bindText(insert.get(),11,dbHash);bindText(insert.get(),12,walHash);bindText(insert.get(),13,"harmony-decrypted-v1");
                        std::string related,relatedStatus="no_file_reference";
                        if(rule.kind=="recording" || rule.kind=="call_recording" || rule.kind=="media" || rule.kind=="media_file") {
                            auto original=scalar(record,rule.kind=="recording"?"_data":rule.kind=="call_recording"?"file_path":"data");
                            related=HarmonyBackupExtractor::scopedPath(e.bundle,e.appIndex,original);
                            relatedStatus=source.entries().count(related)?"present_in_backup":"not_resolved_in_backup";
                            if(relatedStatus=="not_resolved_in_backup") {
                                std::string restored;
                                if((rule.kind=="media" || rule.kind=="media_file") && original.starts_with("/storage/cloud/files/"))
                                    restored="/storage/media/local/files/"+original.substr(std::string("/storage/cloud/files/").size());
                                if(rule.kind=="call_recording" && original.starts_with("/data/storage/el2/group/")) {
                                    const auto marker=original.find("/CallRecord/");
                                    if(marker!=std::string::npos) restored="/data/storage/el2/base/.backup/restore"+original.substr(marker);
                                }
                                const auto candidate=HarmonyBackupExtractor::scopedPath(e.bundle,e.appIndex,restored);
                                const auto target=source.entries().find(candidate);
                                // Only documented backup relocation roots and an exact
                                // suffix are considered; never match by basename globally.
                                if(target!=source.entries().end() && (rule.kind=="call_recording" ||
                                    (record.contains("size") && record["size"].is_number_integer() &&
                                     record["size"].get<std::int64_t>()>=0 && record["size"].get<std::uint64_t>()==target->second.size))) {
                                    related=candidate;relatedStatus="present_in_backup_restore_path";
                                }
                            }
                        }
                        bindText(insert.get(),14,related);bindText(insert.get(),15,relatedStatus);
                        if(sqlite3_step(insert.get())!=SQLITE_DONE) throw std::runtime_error(std::string("RESULT_WRITE_FAILED: ")+sqlite3_errmsg(dest));
                        ++parsed;++totalRows;
                    }
                    if(rc!=SQLITE_DONE) throw std::runtime_error("artifact_query_failed");
                    output.recordSourceCoverage(rule.kind,path,"parsed","table="+rule.table+"; rows="+std::to_string(parsed)+
                        (parsed?"":"; empty_table"));
                }
            } catch(const std::exception& ex) {
                if (std::string(ex.what()).starts_with("RESULT_WRITE_FAILED")) throw;
                std::cerr << "Harmony database " << path << ": " << ex.what() << std::endl;
                output.recordSourceCoverage("database",path,"ERROR",ex.what());
            }
        }
        for(const auto* missing:{"sms","contacts","wechat"})
            output.recordSourceCoverage(missing,"<harmony-backup>","NOT_PRESENT","no_verified_source_in_supported_backup_profile; not evidence of absence on device");
        for(const auto& p:source.usedSourceProvenance()) if(!output.insertSourceProvenance(p))throw std::runtime_error("provenance_write_failed");
        if(!source.verifyIntegrity()) throw std::runtime_error(source.error().empty()?"EVIDENCE_CHANGED_AFTER_INDEX":source.error());
        if(!output.commitTransaction())throw std::runtime_error("harmony_commit_failed");
        return true;
    } catch(...) { output.rollbackTransaction();throw; }
}
