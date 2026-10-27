#include "core/DatabaseManager/EventExtractor/WindowsActivityImport.h"
#include "core/DatabaseManager/SQL/event_extractor_sql.h"
#include <iostream>
int main(int argc,char** argv){
 if(argc!=5)return 2;sqlite3 *events=nullptr,*raw=nullptr;
 if(sqlite3_open(argv[2],&events)!=SQLITE_OK)return 3;
 if(sqlite3_open_v2(argv[3],&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){sqlite3_close(events);return 3;}
 try{forensics::sources::sql(events,EventExtractorSQL::CREATE_EVENTS_TABLE);
 auto report=forensics::windows_activity::importArtifacts(events,raw,argv[1],argv[4]);std::cout<<report.dump(2)<<std::endl;
 sqlite3_close(raw);sqlite3_close(events);return report.value("success",false)?0:4;
 }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;sqlite3_close(raw);sqlite3_close(events);return 5;}
}
