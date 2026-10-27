// Offline integration driver for the production materializer; never opens an HTTP service.
#include "core/DatabaseManager/FileExtractor/FileExtractor.h"
#include "core/DatabaseManager/SourceIndex.h"
#include <iostream>
int main(int argc,char** argv) {
    if(argc<5 || argc>6)return 2;
    FileExtractor extractor(argv[1],argv[2]);
    if(!extractor.initialize()){std::cerr<<"来源初始化失败\n";return 3;}
    if(std::string(argv[4])=="--range" && argc==6){
        std::string data,error;const bool okay=extractor.readSourceRange(argv[5],0,65536,data,error);
        std::cout<<nlohmann::json({{"success",okay},{"bytes",data.size()},{"sha256",forensics::sources::hash(data)},{"error",error}}).dump()<<std::endl;return okay?0:7;
    }
    if(std::string(argv[4])=="--copy-index") {
        sqlite3 *origin=nullptr,*destination=nullptr;
        if(sqlite3_open(argv[2],&origin)!=SQLITE_OK || sqlite3_open(argv[3],&destination)!=SQLITE_OK)return 5;
        const bool copied=forensics::sources::copy(origin,destination,argv[2]);
        sqlite3_close(origin);sqlite3_close(destination);
        std::cout<<nlohmann::json({{"success",copied}}).dump()<<std::endl;return copied?0:6;
    }
    const auto result=extractor.materializeSource(argv[4],argv[3],argc==6?argv[5]:"");
    std::cout<<result.dump()<<std::endl;
    return result.value("success",false)?0:4;
}
