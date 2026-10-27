#pragma once
#include <sqlite3.h>
#include <string>
#include <iostream>
#include "SourceIndex.h"

// Preserve logical source locators whenever the common pipeline derives a
// filtered/classified files database. The prefix is selected by this code only.
inline bool copyMobileSourceIndex(sqlite3* source, sqlite3* destination, const std::string& sourcePath,
                                 const std::string& prefix) {
    sqlite3_stmt* statement=nullptr;
    if(sqlite3_prepare_v2(source,"SELECT 1 FROM sqlite_master WHERE name=?",-1,&statement,nullptr)!=SQLITE_OK) return false;
    const auto meta=prefix+"_source_meta",files=prefix+"_source_files";
    sqlite3_bind_text(statement,1,meta.c_str(),-1,SQLITE_TRANSIENT);
    const bool present=sqlite3_step(statement)==SQLITE_ROW;sqlite3_finalize(statement);
    if(!present) return true;
    if(sqlite3_prepare_v2(destination,"ATTACH DATABASE ? AS harmony_origin",-1,&statement,nullptr)!=SQLITE_OK) return false;
    sqlite3_bind_text(statement,1,sourcePath.c_str(),-1,SQLITE_TRANSIENT);
    const bool attached=sqlite3_step(statement)==SQLITE_DONE;sqlite3_finalize(statement);
    if(!attached) return false;
    const auto sql="SAVEPOINT harmony_copy;DROP TABLE IF EXISTS main."+meta+"; DROP TABLE IF EXISTS main."+files+";"
        "CREATE TABLE main."+meta+" AS SELECT * FROM harmony_origin."+meta+";"
        "CREATE TABLE main."+files+" AS SELECT * FROM harmony_origin."+files+";"
        "CREATE UNIQUE INDEX main."+prefix+"_source_path ON "+files+"(path);"
        "RELEASE harmony_copy;";
    const bool okay=sqlite3_exec(destination,sql.c_str(),nullptr,nullptr,nullptr)==SQLITE_OK;
    if(!okay) {
        std::cerr << "Logical source index copy: " << sqlite3_errmsg(destination) << std::endl;
        sqlite3_exec(destination,"ROLLBACK TO harmony_copy; RELEASE harmony_copy;",nullptr,nullptr,nullptr);
    }
    const bool detached=sqlite3_exec(destination,"DETACH DATABASE harmony_origin",nullptr,nullptr,nullptr)==SQLITE_OK;
    return okay && detached;
}

inline bool copyHarmonySourceIndex(sqlite3* source, sqlite3* destination, const std::string& sourcePath) {
    return copyMobileSourceIndex(source,destination,sourcePath,"harmony") &&
           copyMobileSourceIndex(source,destination,sourcePath,"xiaomi") &&
           forensics::sources::copy(source,destination,sourcePath);
}
