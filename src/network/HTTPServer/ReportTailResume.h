#pragma once
#include "TaskStageLedger.h"
#include "DatabaseManager/EventExtractor/ActivityRevision.h"

namespace forensics::report_tail {
inline std::string ingestionFingerprint(const std::string& events,const std::string& files) {
    const auto a=activity_revision::fingerprint(events,{"events","event_cluster_analyses","cluster_derivations","windows_activity_current"});
    const auto b=activity_revision::fingerprint(files,{"files","file_analyses"});
    if(a.empty() || b.empty())return {};
    return stage_ledger::combine({"ingestion-activity:v1",a,b});
}

// A WAL checkpoint changes physical file stats without changing the analyzed
// records. A report-only retry must bind to those records and the indexed image.
inline bool unchangedInputs(const std::string& image,const std::string& files,
                            const std::string& events,const std::string& expected) {
    if(expected.empty() || !std::filesystem::is_regular_file(image))return false;
    sqlite3* raw=nullptr;
    if(sqlite3_open_v2(files.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);return false;}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);
    try {
        sources::Statement metadata(raw,"SELECT key,value FROM source_index_meta WHERE key IN ('source_path','source_stamp')");
        std::map<std::string,std::string> values;int rc;
        while((rc=sqlite3_step(metadata.value))==SQLITE_ROW){
            if(sqlite3_column_type(metadata.value,1)==SQLITE_NULL)return false;
            values[reinterpret_cast<const char*>(sqlite3_column_text(metadata.value,0))]=
                reinterpret_cast<const char*>(sqlite3_column_text(metadata.value,1));
        }
        if(rc!=SQLITE_DONE || values["source_path"].empty() || values["source_stamp"].empty())return false;
        std::error_code a,b;
        const auto original=std::filesystem::weakly_canonical(values["source_path"],a);
        const auto current=std::filesystem::weakly_canonical(image,b);
        if(a || b || original!=current || sources::stamp(image)!=values["source_stamp"])return false;
    } catch(...) {return false;}
    const auto actual=ingestionFingerprint(events,files);
    return !actual.empty() && actual==expected;
}
}
