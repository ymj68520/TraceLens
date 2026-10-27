#pragma once
#include "DatabaseManager/SourceIndex.h"
#include <mutex>
#include <memory>

namespace forensics::selection {
// For the byte-BPE adapters used by the OpenAI-compatible text endpoint,
// serialized UTF-8 bytes are a conservative token upper bound. Framing is
// reserved separately. No character/4 heuristic is used for admission.
inline size_t inputUpperBound(const nlohmann::json& messages,const std::string& tools="") {
    return messages.dump(-1,' ',false,nlohmann::json::error_handler_t::replace).size()+tools.size();
}
inline bool reserveModelCall(const std::string& database,const std::string& plan,
                             const std::string& source,size_t input,size_t output) {
    if(database.empty() || plan.empty())return true;
    sqlite3* raw=nullptr;if(sqlite3_open(database.c_str(),&raw)!=SQLITE_OK){if(raw)sqlite3_close(raw);return false;}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);sqlite3_busy_timeout(raw,10000);
    try {sources::sql(raw,"BEGIN IMMEDIATE");
        sources::Statement s(raw,"UPDATE selection_budget SET used_calls=used_calls+1,reserved_tokens=reserved_tokens+? WHERE plan_id=? AND used_calls<max_calls AND reserved_tokens+?<=max_tokens");
        const auto tokens=static_cast<int64_t>(input+output);sqlite3_bind_int64(s.value,1,tokens);s.bind(2,plan);sqlite3_bind_int64(s.value,3,tokens);
        if(sqlite3_step(s.value)!=SQLITE_DONE || sqlite3_changes(raw)!=1){sources::sql(raw,"ROLLBACK");return false;}
        sources::Statement record(raw,"INSERT INTO selection_call_ledger(plan_id,source_key,input_bound,output_limit,created_at) VALUES(?,?,?,?,strftime('%s','now'))");
        record.bind(1,plan);record.bind(2,source);sqlite3_bind_int64(record.value,3,input);sqlite3_bind_int64(record.value,4,output);
        if(sqlite3_step(record.value)!=SQLITE_DONE)throw std::runtime_error("MODEL_BUDGET_WRITE_FAILED");sources::sql(raw,"COMMIT");return true;
    }catch(...){sqlite3_exec(raw,"ROLLBACK",nullptr,nullptr,nullptr);return false;}
}
}
