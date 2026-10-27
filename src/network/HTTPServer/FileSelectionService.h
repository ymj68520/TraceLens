#pragma once
#include "core/Selection/CandidateSelection.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "ConfigManager/ConfigManager.h"
#include "LLMPythonProxy.h"
#include "core/PathManager/PathManager.h"
#include <mutex>

namespace forensics {
struct SelectionSource {std::string task,files,raw,image;};
class FileSelectionService {
public:
    static selection::Budget budget(size_t requested){
        auto& config=ConfigManager::instance();if(!config.isLoaded())config.load();selection::Budget b;
        auto limit=[&](const char* key,int64_t fallback,int64_t ceiling){const auto raw=config.get(key,std::to_string(fallback));
            size_t used=0;const auto value=std::stoll(raw,&used);if(used!=raw.size() || value<0 || value>ceiling)throw std::runtime_error(std::string("选择预算配置无效：")+key);return value;};
        size_t maximum=config.getLLMMaxFiles();if(!maximum)maximum=100000;
        const auto filter=limit("FILTER_MAX_FILES",0,100000);if(filter>0)maximum=std::min(maximum,static_cast<size_t>(filter));
        b.files=requested?std::min(requested,maximum):maximum;
        b.candidates=config.getLLMSmartCandidateFiles();if(!b.candidates)b.candidates=100000;
        b.probeFiles=limit("SELECTION_MAX_PROBE_FILES",std::min<size_t>(2000,b.candidates),100000);
        b.probeBytes=limit("SELECTION_MAX_PROBE_BYTES",128*1024*1024,4LL*1024*1024*1024);
        b.probePerFile=limit("SELECTION_PROBE_BYTES_PER_FILE",65536,65536);
        b.semanticFiles=limit("SELECTION_MAX_SEMANTIC_FILES",500,10000);
        b.semanticBytes=limit("SELECTION_MAX_SEMANTIC_BYTES",1024LL*1024*1024,8LL*1024*1024*1024);
        b.seconds=limit("SELECTION_MAX_SECONDS",300,3600);b.skipExecutables=config.getLLMSkipBinary();
        b.visionAvailable=config.getInt("LLM_VISION_IMAGE_TOKEN_BOUND",0)>0;
        b.seed=config.get("SELECTION_SEED","tracelens-selection-v1");
        const auto model=config.getTextModelConfig();
        const auto vision=config.getVisionModelConfig();
        const auto configuration=selection::json{{"text_model",model.model},{"text_url",model.baseUrl},{"endpoint",model.endpoint},
            {"context",model.contextLength},{"output",model.maxTokens},{"temperature",model.temperature},{"thinking",model.thinkingMode},
            {"vision_model",vision.model},{"vision_url",vision.baseUrl},{"vision_output",vision.maxTokens},{"image_bound",vision.visionImageTokenBound}};
        b.analysisContract="file-analysis:v3-zh|parser-truth:v1|source-read:v1|probe:evtx128-sqlite5-v1|byte-bpe-bound:v1|"+sources::hash(configuration.dump());
        b.maxCalls=limit("LLM_ANALYSIS_MAX_CALLS",std::min<size_t>(b.files*2,200000),200000);
        b.maxTokens=limit("LLM_ANALYSIS_MAX_TOTAL_TOKENS",b.maxCalls*model.contextLength,1LL<<48);
        return b;
    }
    static nlohmann::json plan(const std::vector<SelectionSource>& contexts,const selection::Budget& budget){
        if(contexts.empty())throw std::runtime_error("SELECTION_SOURCE_REQUIRED");
        // Legacy task stores acquire identities through the existing reader,
        // before any plan is frozen. Historical report snapshots are untouched.
        for(const auto& context:contexts){
            sqlite3* raw=nullptr;if(sqlite3_open_v2(context.files.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);throw std::runtime_error("SELECTION_SOURCE_UNAVAILABLE");}
            bool indexed=sources::table(raw,"source_index_meta");sqlite3_close(raw);
            if(indexed)continue;
            FileExtractor indexer(context.image,context.raw);if(!indexer.initialize())throw std::runtime_error("SOURCE_INDEX_UNAVAILABLE");
            if(context.files==context.raw)continue;
            sqlite3 *origin=nullptr,*destination=nullptr;bool copied=false;
            if(sqlite3_open_v2(context.raw.c_str(),&origin,SQLITE_OPEN_READONLY,nullptr)==SQLITE_OK && sqlite3_open(context.files.c_str(),&destination)==SQLITE_OK){sqlite3_busy_timeout(destination,10000);copied=sources::copy(origin,destination,context.raw);}
            if(destination)sqlite3_close(destination);if(origin)sqlite3_close(origin);
            if(!copied)throw std::runtime_error("SOURCE_INDEX_SYNC_FAILED");
        }
        std::vector<selection::Input> inputs;for(auto& c:contexts)inputs.push_back({c.files,c.task});
        const auto key=selection::planInputKey(inputs,budget);
        if(auto old=selection::cached(contexts.front().files,key);!old.is_null())return old;
        std::map<std::string,std::unique_ptr<FileExtractor>> readers;
        auto read=[&](const selection::Candidate& c,size_t count){
            const auto probeKey="range:"+c.key;
            if(auto previous=selection::probeCache(contexts.front().files,key,probeKey);!previous.is_null())return previous;
            if(!selection::reserveProbe(contexts.front().files,key,"range",1,count,budget.probeFiles,budget.probeBytes,budget.seconds))
                return selection::json{{"state","unprobed"},{"reason","本轮范围探测额度已用尽"}};
            auto ctx=std::find_if(contexts.begin(),contexts.end(),[&](const auto& entry){return entry.task==c.task;});
            if(ctx==contexts.end() || c.id.empty() || ctx->image.empty() || ctx->raw.empty())return selection::json{{"state","unprobed"},{"reason","来源暂不支持范围读取"}};
            auto& reader=readers[c.task];if(!reader){reader=std::make_unique<FileExtractor>(ctx->image,ctx->raw);if(!reader->initialize()){reader.reset();return selection::json{{"state","source_error"},{"reason","来源初始化失败"}};}}
            std::string data,error;if(!reader->readSourceRange(c.id,0,count,data,error))return selection::json{{"state",error=="RANGE_READER_UNAVAILABLE"?"unprobed":"source_error"},{"reason",error}};
            return selection::probeCache(contexts.front().files,key,probeKey,selection::inspectBytes(data,data.size()==static_cast<size_t>(c.size),c.size));
        };
        auto semantic=[&](const std::vector<selection::Candidate>& candidates,const selection::Budget& b){
            selection::json result={{"results",selection::json::object()},{"stats",{{"reserved_bytes",0},{"processed",0}}}};
            if(!LLMPythonProxy::instance().isServiceAvailable())throw std::runtime_error("语义探测服务不可用");
            const auto started=std::chrono::steady_clock::now();
            size_t remaining=b.semanticBytes,processed=0,remainingContexts=contexts.size();
            for(auto& context:contexts){
                const auto contextSlots=remainingContexts--;
                if(context.task.empty())continue;selection::json refs=selection::json::array();
                for(const auto& c:candidates)if(c.task==context.task && !c.id.empty())refs.push_back({{"path",c.path},{"source_id",c.id}});
                if(refs.empty() || !remaining)continue;
                const auto allowance=remaining/contextSlots;
                const auto probeKey="semantic:"+context.task+":"+sources::hash(refs.dump());
                auto answer=selection::probeCache(contexts.front().files,key,probeKey);
                if(answer.is_null()){
                    // Reserve the entire batch allowance before the remote work.
                    // Unknown outcomes keep their reservation on timeout/restart.
                    if(!selection::reserveProbe(contexts.front().files,key,"semantic",refs.size(),allowance,b.semanticFiles,b.semanticBytes,b.seconds))continue;
                    selection::json materialized=selection::json::array();size_t materializedBytes=0;
                    auto& reader=readers[context.task];
                    if(!reader){reader=std::make_unique<FileExtractor>(context.image,context.raw);if(!reader->initialize()){reader.reset();continue;}}
                    for(const auto& ref:refs){
                        if(std::chrono::steady_clock::now()-started>std::chrono::seconds(b.seconds))break;
                        auto ready=reader->materializeSource(ref.at("path").get<std::string>(),PathManager::instance().getTaskExtractDir(context.task),ref.at("source_id").get<std::string>(),allowance-materializedBytes);
                        if(ready.value("success",false)){
                            for(const auto& c:ready.at("components"))materializedBytes+=c.at("size").get<size_t>();
                            materialized.push_back(ref);
                        }
                    }
                    const auto seconds=std::max(1,b.seconds-static_cast<int>(std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now()-started).count()));
                    if(materialized.empty())continue;
                    answer=LLMPythonProxy::instance().probeFileSelection({{"task_id",context.task},{"sources",materialized},
                    {"max_bytes",allowance},{"max_files",b.semanticFiles-processed},{"timeout_seconds",seconds}});
                    selection::probeCache(contexts.front().files,key,probeKey,answer);
                }
                if(!answer.contains("results") || !answer["results"].is_object())throw std::runtime_error("PROBE_PROTOCOL_INVALID");
                const auto charged=answer.value("reserved_bytes",size_t(0));if(charged>allowance)throw std::runtime_error("PROBE_BUDGET_EXCEEDED");
                remaining-=allowance;processed+=answer.value("processed",size_t(0));
                for(auto& [sid,value]:answer["results"].items())result["results"][context.task+":"+sid]=value;
            }
            result["stats"]={{"reserved_bytes",b.semanticBytes-remaining},{"processed",processed}};return result;
        };
        auto result=selection::build(inputs,budget,read,semantic);
        result["budget_database"]=contexts.front().files;
        selection::save(contexts.front().files,key,result,budget.maxCalls,budget.maxTokens);
        for(size_t i=1;i<contexts.size();++i)selection::save(contexts[i].files,key,result,budget.maxCalls,budget.maxTokens);
        // A concurrent winner is authoritative; all consumers use the same bytes.
        return selection::cached(contexts.front().files,key);
    }
};
}
