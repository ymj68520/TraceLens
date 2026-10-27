#pragma once
#include <sqlite3.h>
#include <openssl/sha.h>
#include <openssl/rand.h>
#include <nlohmann/json.hpp>
#include <string>
#include <vector>
#include <stdexcept>
#include <filesystem>
#include "SourceNameEncoding.h"

// An acquisition-index identity, not a claim that an image hash was verified.
// Copies of files.db preserve the original raw-record locator and revision.
namespace forensics::sources {
using json=nlohmann::json;
inline void sql(sqlite3* db,const std::string& query) {
    char* error=nullptr;
    if(sqlite3_exec(db,query.c_str(),nullptr,nullptr,&error)!=SQLITE_OK) {
        std::string message=error?error:"source index SQL failed";sqlite3_free(error);
        throw std::runtime_error(message);
    }
}
struct Statement {
    sqlite3_stmt* value=nullptr;
    Statement(sqlite3* db,const std::string& query) {
        if(sqlite3_prepare_v2(db,query.c_str(),-1,&value,nullptr)!=SQLITE_OK) throw std::runtime_error(sqlite3_errmsg(db));
    }
    ~Statement(){sqlite3_finalize(value);}
    void bind(int i,const std::string& text){sqlite3_bind_text(value,i,text.data(),static_cast<int>(text.size()),SQLITE_TRANSIENT);}
};
inline bool table(sqlite3* db,const std::string& name) {
    Statement s(db,"SELECT 1 FROM sqlite_master WHERE type='table' AND name=?");s.bind(1,name);
    return sqlite3_step(s.value)==SQLITE_ROW;
}
inline bool column(sqlite3* db,const std::string& name) {
    Statement s(db,"PRAGMA table_info(files)");
    while(sqlite3_step(s.value)==SQLITE_ROW) if(name==reinterpret_cast<const char*>(sqlite3_column_text(s.value,1)))return true;
    return false;
}
inline std::string hash(const std::string& text) {
    unsigned char digest[SHA256_DIGEST_LENGTH];SHA256(reinterpret_cast<const unsigned char*>(text.data()),text.size(),digest);
    const char* hex="0123456789abcdef";std::string result;
    for(auto b:digest){result+=hex[b>>4];result+=hex[b&15];}return result;
}
inline bool validId(const std::string& id) {
    return id.size()==64 && id.find_first_not_of("0123456789abcdef")==std::string::npos;
}
inline std::string stamp(const std::string& path) {
    std::error_code ec;
    if(!std::filesystem::is_regular_file(path,ec))return "";
    const auto size=std::filesystem::file_size(path,ec);if(ec)return "";
    const auto modified=std::filesystem::last_write_time(path,ec);if(ec)return "";
    return std::to_string(size)+":"+std::to_string(modified.time_since_epoch().count());
}
inline json row(sqlite3_stmt* s) {
    json result=json::object();
    for(int i=0;i<sqlite3_column_count(s);++i) {
        const auto name=sqlite3_column_name(s,i);
        switch(sqlite3_column_type(s,i)) {
            case SQLITE_NULL: result[name]=nullptr;break;
            case SQLITE_INTEGER:result[name]=sqlite3_column_int64(s,i);break;
            default:result[name]=std::string(reinterpret_cast<const char*>(sqlite3_column_text(s,i)),sqlite3_column_bytes(s,i));break;
        }
    }return result;
}
inline const char* matchFields() {
    return "s.path=f.path AND s.inode=COALESCE(f.inode,0) AND s.partition_num=COALESCE(f.partition_num,0) "
           "AND s.is_deleted=COALESCE(f.is_deleted,0) AND s.size=COALESCE(f.size,0) "
           "AND s.mtime=COALESCE(f.mtime,0) AND s.ctime=COALESCE(f.ctime,0)";
}
inline void normalizePhysicalNames(sqlite3* db) {
    sql(db,"CREATE TABLE IF NOT EXISTS source_name_bytes(raw_record_id INTEGER PRIMARY KEY,path_bytes BLOB,name_bytes BLOB,display_path TEXT,display_name TEXT,policy TEXT NOT NULL)");
    Statement rows(db,"SELECT rowid,path,name FROM files ORDER BY rowid");
    Statement save(db,"INSERT INTO source_name_bytes VALUES(?,?,?,?,?,?)");
    Statement update(db,"UPDATE files SET path=?,name=? WHERE rowid=?");
    int rc;
    while((rc=sqlite3_step(rows.value))==SQLITE_ROW) {
        const auto id=sqlite3_column_int64(rows.value,0);
        const bool pathNull=sqlite3_column_type(rows.value,1)==SQLITE_NULL,nameNull=sqlite3_column_type(rows.value,2)==SQLITE_NULL;
        auto bytes=[&](int column){const auto* p=sqlite3_column_blob(rows.value,column);return p?std::string(static_cast<const char*>(p),sqlite3_column_bytes(rows.value,column)):std::string();};
        const auto path=bytes(1),name=bytes(2),shownPath=source_names::path(path),shownName=source_names::component(name);
        if(path==shownPath && name==shownName)continue;
        sqlite3_bind_int64(save.value,1,id);
        if(pathNull)sqlite3_bind_null(save.value,2);else sqlite3_bind_blob(save.value,2,path.data(),path.size(),SQLITE_TRANSIENT);
        if(nameNull)sqlite3_bind_null(save.value,3);else sqlite3_bind_blob(save.value,3,name.data(),name.size(),SQLITE_TRANSIENT);
        save.bind(4,shownPath);save.bind(5,shownName);save.bind(6,source_names::policy);
        if(sqlite3_step(save.value)!=SQLITE_DONE)throw std::runtime_error("SOURCE_NAME_PROVENANCE_WRITE_FAILED");sqlite3_reset(save.value);
        if(pathNull)sqlite3_bind_null(update.value,1);else update.bind(1,shownPath);
        if(nameNull)sqlite3_bind_null(update.value,2);else update.bind(2,shownName);
        sqlite3_bind_int64(update.value,3,id);
        if(sqlite3_step(update.value)!=SQLITE_DONE)throw std::runtime_error("SOURCE_NAME_DISPLAY_WRITE_FAILED");sqlite3_reset(update.value);
    }
    if(rc!=SQLITE_DONE)throw std::runtime_error("SOURCE_NAME_SCAN_FAILED");
}
inline bool ensure(sqlite3* db,const std::string& sourcePath,std::string* diagnostic=nullptr) {
    if(diagnostic)diagnostic->clear();
    try {
        if(!table(db,"files") || !column(db,"inode") || !column(db,"partition_num")) throw std::runtime_error("SOURCE_INDEX_SCHEMA_INVALID");
        if(table(db,"source_index_meta")) {
            Statement original(db,"SELECT value FROM source_index_meta WHERE key='source_path'");
            if(sqlite3_step(original.value)==SQLITE_ROW) {
                const std::string expected=reinterpret_cast<const char*>(sqlite3_column_text(original.value,0));
                std::error_code ec1,ec2;
                const auto a=std::filesystem::weakly_canonical(expected,ec1);
                const auto b=std::filesystem::weakly_canonical(sourcePath,ec2);
                if(ec1 || ec2 || a!=b)throw std::runtime_error("SOURCE_IMAGE_PATH_CHANGED");
            }
            Statement binding(db,"SELECT value FROM source_index_meta WHERE key='source_stamp'");
            if(sqlite3_step(binding.value)==SQLITE_ROW) {
                const std::string expected=reinterpret_cast<const char*>(sqlite3_column_text(binding.value,0));
                if(!expected.empty() && stamp(sourcePath)!=expected)throw std::runtime_error("SOURCE_IMAGE_CHANGED_AFTER_INDEX");
            }
            // An existing revision is immutable. Never silently regenerate its IDs.
            Statement valid(db,std::string("SELECT 1 FROM files f WHERE type='REG' AND (source_id IS NULL OR NOT EXISTS (SELECT 1 FROM source_objects s WHERE s.source_id=f.source_id AND ")+matchFields()+")) LIMIT 1");
            const auto state=sqlite3_step(valid.value);
            if(state==SQLITE_ROW)throw std::runtime_error("SOURCE_RECORD_CHANGED_AFTER_INDEX");
            if(state!=SQLITE_DONE)throw std::runtime_error("SOURCE_INDEX_VALIDATION_READ_FAILED");
            return true;
        }
        sql(db,"SAVEPOINT source_index_create");
        try {
            if(!column(db,"source_id")) sql(db,"ALTER TABLE files ADD COLUMN source_id TEXT");
            sql(db,"CREATE TABLE source_index_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);"
                "CREATE TABLE source_objects(source_id TEXT PRIMARY KEY,source_revision TEXT NOT NULL,path TEXT NOT NULL,"
                "logical_name TEXT NOT NULL,partition_num INTEGER NOT NULL,inode INTEGER NOT NULL,is_deleted INTEGER NOT NULL,"
                "size INTEGER NOT NULL,mtime INTEGER NOT NULL,ctime INTEGER NOT NULL,locator_json TEXT NOT NULL);"
                "CREATE INDEX source_objects_location ON source_objects(path,partition_num,inode,is_deleted,size,mtime,ctime);"
                "CREATE INDEX IF NOT EXISTS files_source_id ON files(source_id);");
            unsigned char random[32];if(RAND_bytes(random,sizeof(random))!=1)throw std::runtime_error("source revision unavailable");
            const auto revision=hash(std::string(reinterpret_cast<char*>(random),sizeof(random)));
            std::string kind="physical";
            if(table(db,"harmony_source_files"))kind="harmony";
            if(table(db,"xiaomi_source_files"))kind="xiaomi";
            if(kind=="physical")normalizePhysicalNames(db);
            Statement meta(db,"INSERT INTO source_index_meta VALUES(?,?)");
            for(const auto& item:std::vector<std::pair<std::string,std::string>>{{"version","1"},{"revision",revision},{"kind",kind},{"source_path",sourcePath},{"source_stamp",stamp(sourcePath)}}) {
                meta.bind(1,item.first);meta.bind(2,item.second);if(sqlite3_step(meta.value)!=SQLITE_DONE)throw std::runtime_error("source metadata write failed");sqlite3_reset(meta.value);
            }
            Statement files(db,"SELECT rowid AS raw_record_id,path,name,COALESCE(inode,0) AS inode,COALESCE(partition_num,0) AS partition_num,"
                "COALESCE(is_deleted,0) AS is_deleted,COALESCE(size,0) AS size,COALESCE(mtime,0) AS mtime,COALESCE(ctime,0) AS ctime FROM files WHERE type='REG' ORDER BY rowid");
            Statement insert(db,"INSERT INTO source_objects VALUES(?,?,?,?,?,?,?,?,?,?,?)");
            Statement update(db,"UPDATE files SET source_id=? WHERE rowid=?");
            int readResult;
            while((readResult=sqlite3_step(files.value))==SQLITE_ROW) {
                const auto f=row(files.value);
                json locator={{"version",1},{"source_revision",revision},{"source_kind",kind},
                    {"identity_scope","acquisition_index"},{"raw_record_id",f["raw_record_id"]},
                    {"logical_path",f["path"]},{"logical_name",f["name"]},{"size",f["size"]},
                    {"is_deleted",f["is_deleted"]},{"mtime",f["mtime"]},{"ctime",f["ctime"]}};
                if(kind=="physical") {
                    locator["partition_num"]=f["partition_num"];locator["inode"]=f["inode"];
                    locator["data_stream"]="default";locator["attribute_id"]=nullptr;
                    Statement original(db,"SELECT path_bytes,name_bytes,policy FROM source_name_bytes WHERE raw_record_id=?");
                    sqlite3_bind_int64(original.value,1,f["raw_record_id"].get<int64_t>());
                    if(sqlite3_step(original.value)==SQLITE_ROW) {
                        locator["name_encoding"]=source_names::policy;
                        for(int i=0;i<2;++i){const auto* data=sqlite3_column_blob(original.value,i);
                            locator[i==0?"raw_path_hex":"raw_name_hex"]=data?json(source_names::hex(std::string(static_cast<const char*>(data),sqlite3_column_bytes(original.value,i)))):json(nullptr);}
                    }
                } else {
                    locator["inode"]=nullptr; // The logical entry number is not a handset inode.
                    locator["entry_id"]=f["inode"];
                    Statement member(db,"SELECT * FROM "+kind+"_source_files WHERE path=?");member.bind(1,f["path"].get<std::string>());
                    if(sqlite3_step(member.value)!=SQLITE_ROW)throw std::runtime_error("logical locator missing");
                    locator["logical_location"]=row(member.value);
                }
                const auto id=hash(locator.dump());
                insert.bind(1,id);insert.bind(2,revision);insert.bind(3,f["path"].get<std::string>());
                insert.bind(4,f["name"].is_string()?f["name"].get<std::string>():"");
                int n=5;for(const auto key:{"partition_num","inode","is_deleted","size","mtime","ctime"})sqlite3_bind_int64(insert.value,n++,f[key].get<int64_t>());
                insert.bind(11,locator.dump());
                if(sqlite3_step(insert.value)!=SQLITE_DONE)throw std::runtime_error("source object write failed");sqlite3_reset(insert.value);
                update.bind(1,id);sqlite3_bind_int64(update.value,2,f["raw_record_id"].get<int64_t>());
                if(sqlite3_step(update.value)!=SQLITE_DONE)throw std::runtime_error("source link write failed");sqlite3_reset(update.value);
            }
            if(readResult!=SQLITE_DONE)throw std::runtime_error("SOURCE_INDEX_SCAN_FAILED");
            sql(db,"RELEASE source_index_create");return true;
        }catch(...){sql(db,"ROLLBACK TO source_index_create; RELEASE source_index_create");throw;}
    }catch(const std::exception& error){if(diagnostic)*diagnostic=error.what();return false;}
}

inline bool copy(sqlite3* source,sqlite3* destination,const std::string& sourcePath) {
    if(!table(source,"source_index_meta")) return true; // Legacy data remains readable by unique path.
    bool attached=false;
    try {
        Statement attach(destination,"ATTACH DATABASE ? AS source_origin");attach.bind(1,sourcePath);
        if(sqlite3_step(attach.value)!=SQLITE_DONE)return false;attached=true;
        sql(destination,"SAVEPOINT source_index_copy");
        try {
            if(!column(destination,"source_id"))sql(destination,"ALTER TABLE files ADD COLUMN source_id TEXT");
            sql(destination,"DROP TABLE IF EXISTS main.source_index_meta; DROP TABLE IF EXISTS main.source_objects;"
                "CREATE TABLE source_index_meta AS SELECT * FROM source_origin.source_index_meta;"
                "CREATE TABLE source_objects AS SELECT * FROM source_origin.source_objects;"
                "CREATE UNIQUE INDEX source_objects_id ON source_objects(source_id);"
                "CREATE INDEX source_objects_location ON source_objects(path,partition_num,inode,is_deleted,size,mtime,ctime);"
                "CREATE INDEX IF NOT EXISTS files_source_id ON files(source_id);");
            const std::string match=matchFields();
            sql(destination,"UPDATE files AS f SET source_id=(SELECT s.source_id FROM source_objects s WHERE "+match+
                ") WHERE type='REG' AND (SELECT COUNT(*) FROM source_objects s WHERE "+match+")==1;");
            sql(destination,"RELEASE source_index_copy");
        }catch(...){sql(destination,"ROLLBACK TO source_index_copy; RELEASE source_index_copy");throw;}
        sql(destination,"DETACH DATABASE source_origin");return true;
    }catch(...){if(attached)sqlite3_exec(destination,"DETACH DATABASE source_origin",nullptr,nullptr,nullptr);return false;}
}
inline json lookup(sqlite3* db,const std::string& id) {
    if(!validId(id)||!table(db,"source_objects"))return nullptr;
    Statement s(db,"SELECT locator_json FROM source_objects WHERE source_id=?");s.bind(1,id);
    if(sqlite3_step(s.value)!=SQLITE_ROW)return nullptr;
    auto locator=json::parse(reinterpret_cast<const char*>(sqlite3_column_text(s.value,0)));
    if(hash(locator.dump())!=id)throw std::runtime_error("SOURCE_LOCATOR_HASH_MISMATCH");
    Statement revision(db,"SELECT value FROM source_index_meta WHERE key='revision'");
    if(sqlite3_step(revision.value)!=SQLITE_ROW || locator.value("version",0)!=1 || locator.value("source_revision","")!=reinterpret_cast<const char*>(sqlite3_column_text(revision.value,0)))
        throw std::runtime_error("SOURCE_REVISION_MISMATCH");
    return locator;
}
inline std::string reference(const std::string& id,const std::string& path){return validId(id)?"source:v1:"+id+":"+path:path;}
inline std::string referenceId(const std::string& ref){return ref.rfind("source:v1:",0)==0 && ref.size()>74 && ref[74]==':' && validId(ref.substr(10,64))?ref.substr(10,64):"";}
inline std::string referencePath(const std::string& ref){return referenceId(ref).empty()?ref:ref.substr(75);}
}
