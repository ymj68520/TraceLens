#pragma once
#include "DatabaseManager/SourceIndex.h"
#include <openssl/evp.h>
#include <memory>
#include <set>
namespace forensics::activity_revision {
inline std::string fingerprint(const std::string& database,const std::vector<std::string>& tables){
 sqlite3* raw=nullptr;if(sqlite3_open_v2(database.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);return "";}
 std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);
 auto hash=std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)>(EVP_MD_CTX_new(),EVP_MD_CTX_free);
 if(!hash || EVP_DigestInit_ex(hash.get(),EVP_sha256(),nullptr)!=1)return "";
 try{sources::sql(raw,"BEGIN");for(const auto& table:tables){
  if(!sources::table(raw,table)){const auto missing=table+":missing";EVP_DigestUpdate(hash.get(),missing.data(),missing.size());continue;}
  sources::Statement columns(raw,"PRAGMA table_info("+table+")");std::vector<std::string> names;
  while(sqlite3_step(columns.value)==SQLITE_ROW){std::string name=reinterpret_cast<const char*>(sqlite3_column_text(columns.value,1));
   if(name=="ingested_at" || name=="llm_analyzed_at")continue;
   if(table=="events" && name.rfind("llm_",0)==0)continue;
   names.push_back(name);
  }
  std::string query="SELECT ";for(size_t i=0;i<names.size();++i){if(i)query+=",";query+="\""+names[i]+"\"";}query+=" FROM "+table+" ORDER BY rowid";
  sources::Statement rows(raw,query);int rc;EVP_DigestUpdate(hash.get(),table.data(),table.size());
  while((rc=sqlite3_step(rows.value))==SQLITE_ROW){const auto value=sources::row(rows.value).dump(-1,' ',false,nlohmann::json::error_handler_t::replace);EVP_DigestUpdate(hash.get(),value.data(),value.size());}
  if(rc!=SQLITE_DONE)throw std::runtime_error("ACTIVITY_REVISION_READ_FAILED");
 }
 sources::sql(raw,"COMMIT");unsigned char bytes[EVP_MAX_MD_SIZE];unsigned length=0;EVP_DigestFinal_ex(hash.get(),bytes,&length);
 return sources::hash(std::string(reinterpret_cast<char*>(bytes),length));
 }catch(...){return "";}
}
inline void archive(const std::string& database){
 if(!std::filesystem::is_regular_file(database))return;
 std::vector<std::string> names;
 {sqlite3* source=nullptr;if(sqlite3_open_v2(database.c_str(),&source,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(source)sqlite3_close(source);throw std::runtime_error("WINDOWS_HISTORY_READ_FAILED");}
  std::unique_ptr<sqlite3,decltype(&sqlite3_close)> handle(source,sqlite3_close);
  sources::Statement tables(source,"SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name");
  while(sqlite3_step(tables.value)==SQLITE_ROW){std::string name=reinterpret_cast<const char*>(sqlite3_column_text(tables.value,0));
    if(name.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")!=std::string::npos)throw std::runtime_error("WINDOWS_HISTORY_SCHEMA_INVALID");names.push_back(name);}}
 const auto key=fingerprint(database,names);
 if(key.empty())throw std::runtime_error("WINDOWS_HISTORY_FINGERPRINT_FAILED");
 const auto folder=std::filesystem::path(database).parent_path()/"windows_history";std::filesystem::create_directories(folder);
 const auto destination=folder/(key+".db");if(std::filesystem::exists(destination))return;
 sqlite3 *source=nullptr,*target=nullptr;
 const bool opened=sqlite3_open_v2(database.c_str(),&source,SQLITE_OPEN_READONLY,nullptr)==SQLITE_OK && sqlite3_open(destination.c_str(),&target)==SQLITE_OK;
 bool copied=false;if(opened){auto backup=sqlite3_backup_init(target,"main",source,"main");if(backup){copied=sqlite3_backup_step(backup,-1)==SQLITE_DONE;sqlite3_backup_finish(backup);}}
 if(target)sqlite3_close(target);if(source)sqlite3_close(source);
 if(!copied){std::error_code error;std::filesystem::remove(destination,error);throw std::runtime_error("WINDOWS_HISTORY_BACKUP_FAILED");}
}
}
