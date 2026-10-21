#pragma once
#include <sqlite3.h>
#include <string>
#include <iostream>

// Preserve logical source locators whenever the common pipeline derives a
// filtered/classified files database. Non-Harmony databases are unchanged.
inline bool copyHarmonySourceIndex(sqlite3* source, sqlite3* destination, const std::string& sourcePath) {
    sqlite3_stmt* statement=nullptr;
    if(sqlite3_prepare_v2(source,"SELECT 1 FROM sqlite_master WHERE name='harmony_source_meta'",-1,&statement,nullptr)!=SQLITE_OK) return false;
    const bool present=sqlite3_step(statement)==SQLITE_ROW;sqlite3_finalize(statement);
    if(!present) return true;
    if(sqlite3_prepare_v2(destination,"ATTACH DATABASE ? AS harmony_origin",-1,&statement,nullptr)!=SQLITE_OK) return false;
    sqlite3_bind_text(statement,1,sourcePath.c_str(),-1,SQLITE_TRANSIENT);
    const bool attached=sqlite3_step(statement)==SQLITE_DONE;sqlite3_finalize(statement);
    if(!attached) return false;
    const bool okay=sqlite3_exec(destination,
        "SAVEPOINT harmony_copy;"
        "DROP TABLE IF EXISTS main.harmony_source_meta; DROP TABLE IF EXISTS main.harmony_source_files;"
        "CREATE TABLE main.harmony_source_meta AS SELECT * FROM harmony_origin.harmony_source_meta;"
        "CREATE TABLE main.harmony_source_files AS SELECT * FROM harmony_origin.harmony_source_files;"
        "CREATE UNIQUE INDEX main.harmony_source_path ON harmony_source_files(path);"
        "RELEASE harmony_copy;",nullptr,nullptr,nullptr)==SQLITE_OK;
    if(!okay) {
        std::cerr << "Logical source index copy: " << sqlite3_errmsg(destination) << std::endl;
        sqlite3_exec(destination,"ROLLBACK TO harmony_copy; RELEASE harmony_copy;",nullptr,nullptr,nullptr);
    }
    const bool detached=sqlite3_exec(destination,"DETACH DATABASE harmony_origin",nullptr,nullptr,nullptr)==SQLITE_OK;
    return okay && detached;
}
