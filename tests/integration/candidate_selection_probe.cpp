// Offline acceptance driver for the production selection service. Never calls a model.
#include "network/HTTPServer/FileSelectionService.h"
#include <fstream>
#include <iostream>
int main(int argc,char** argv){
    // Cross-check the production bounded probe against independent parser counts.
    if(argc==4 && std::string(argv[1])=="--evtx-headers"){
        nlohmann::json rows=nlohmann::json::array();
        for(const auto& entry:std::filesystem::directory_iterator(argv[2])){
            if(!entry.is_regular_file() || entry.path().extension()!=".evtx")continue;
            std::ifstream input(entry.path(),std::ios::binary);std::string bytes(4608,'\0');
            input.read(bytes.data(),bytes.size());bytes.resize(static_cast<size_t>(input.gcount()));
            rows.push_back({{"file_name",entry.path().filename().string()},{"size",entry.file_size()},
                {"probe",forensics::selection::inspectBytes(bytes,bytes.size()==entry.file_size(),entry.file_size())}});
        }
        std::ofstream output(argv[3]);output<<rows.dump(2);return output?0:3;
    }
    if(argc!=6)return 2;
    try{
        auto& paths=forensics::PathManager::instance();paths.initialize(argv[0]);
        auto& config=forensics::ConfigManager::instance();config.load();
        paths.setDataDirName(config.get("DATA_DIR","data"));
        auto budget=forensics::FileSelectionService::budget(1000);
        auto plan=forensics::FileSelectionService::plan({{argv[4],argv[3],argv[2],argv[1]}},budget);
        std::ofstream output(argv[5]);output<<plan.dump(2);if(!output)return 3;
        std::cout<<nlohmann::json({{"plan_id",plan["plan_id"]},{"counts",plan["counts"]},{"semantic_probe",plan["semantic_probe"]}}).dump()<<std::endl;
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;return 4;}
}
