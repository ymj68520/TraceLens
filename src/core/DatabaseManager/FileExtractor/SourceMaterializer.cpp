#include "FileExtractor.h"
#include "DatabaseManager/SourceIndex.h"
#include "analyzers/AndroidAnalyzer/IndexedMobileSource.h"
#include <openssl/evp.h>
#include <fstream>
#include <array>
#include <atomic>
#include <algorithm>
#include <mutex>
#ifdef _WIN32
#include <Windows.h>
#endif

namespace fs=std::filesystem;
using nlohmann::json;
namespace source=forensics::sources;
namespace {
json hashes(const fs::path& path) {
    std::ifstream stream(path,std::ios::binary);
    if(!stream)throw std::runtime_error("SOURCE_READ_FAILED");
    auto sha=std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)>(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    auto md5=std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)>(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    if(!sha||!md5||EVP_DigestInit_ex(sha.get(),EVP_sha256(),nullptr)!=1||EVP_DigestInit_ex(md5.get(),EVP_md5(),nullptr)!=1)throw std::runtime_error("SOURCE_HASH_FAILED");
    std::array<char,1024*1024> buffer{};uint64_t size=0;
    while(stream){stream.read(buffer.data(),buffer.size());const auto n=stream.gcount();if(n>0){size+=n;EVP_DigestUpdate(sha.get(),buffer.data(),n);EVP_DigestUpdate(md5.get(),buffer.data(),n);}}
    if(stream.bad())throw std::runtime_error("SOURCE_READ_FAILED");
    auto finish=[](EVP_MD_CTX* ctx){unsigned char value[EVP_MAX_MD_SIZE];unsigned int length=0;
        if(EVP_DigestFinal_ex(ctx,value,&length)!=1)throw std::runtime_error("SOURCE_HASH_FAILED");
        const char* hex="0123456789abcdef";std::string result;for(unsigned int i=0;i<length;++i){result+=hex[value[i]>>4];result+=hex[value[i]&15];}return result;};
    return {{"sha256",finish(sha.get())},{"md5",finish(md5.get())},{"size",size}};
}
}

bool FileExtractor::readSourceRange(const std::string& id,uint64_t offset,size_t length,
                                  std::string& data,std::string& error) {
    data.clear();error.clear();
    try {
        if(!dbManager_ || length>65536)throw std::runtime_error("SOURCE_RANGE_INVALID");
        auto* db=dbManager_->getDb();const auto loc=source::lookup(db,id);
        if(loc.is_null())throw std::runtime_error("SOURCE_NOT_FOUND");
        source::Statement binding(db,"SELECT value FROM source_index_meta WHERE key='source_stamp'");
        if(sqlite3_step(binding.value)==SQLITE_ROW){const std::string stamp=reinterpret_cast<const char*>(sqlite3_column_text(binding.value,0));
            if(!stamp.empty() && source::stamp(imagePath_)!=stamp)throw std::runtime_error("SOURCE_CHANGED_AFTER_INDEX");}
        auto records=searchFiles("source_id='"+id+"' AND type='REG'");
        if(records.size()!=1 || records[0].path!=loc.at("logical_path").get<std::string>() || records[0].size!=loc.at("size").get<int64_t>())throw std::runtime_error("SOURCE_RECORD_CHANGED");
        const auto& record=records[0];
        if(offset>static_cast<uint64_t>(record.size))throw std::runtime_error("SOURCE_RANGE_INVALID");
        length=std::min<uint64_t>(length,record.size-offset);
        if(auto* logical=dynamic_cast<IndexedMobileSource*>(logicalSource_.get()))
            return logical->readRange(record.path,offset,length,data,error);
        if(loc.at("source_kind")!="physical" || loc.at("inode").get<int64_t>()!=record.inode || loc.at("partition_num").get<int>()!=record.partitionNum)
            throw std::runtime_error("SOURCE_RECORD_CHANGED");
        auto* fs=fsForPartition(record.partitionNum);
        // XFS's old helper reads the entire file: it is deliberately not used here.
        if(!fs)throw std::runtime_error("RANGE_READER_UNAVAILABLE");
        auto* raw=tsk_fs_file_open_meta(fs,nullptr,record.inode);
        if(!raw)throw std::runtime_error("SOURCE_RANGE_READ_FAILED");
        std::unique_ptr<TSK_FS_FILE,decltype(&tsk_fs_file_close)> file(raw,tsk_fs_file_close);
        if(!file->meta || file->meta->size!=record.size)throw std::runtime_error("SOURCE_RECORD_CHANGED");
        data.resize(length);
        if(length && tsk_fs_file_read(file.get(),offset,data.data(),length,TSK_FS_FILE_READ_FLAG_NONE)!=static_cast<ssize_t>(length))throw std::runtime_error("SOURCE_RANGE_READ_FAILED");
        return true;
    }catch(const std::exception& e){data.clear();error=e.what();return false;}
}

bool FileExtractor::extractFileBySourceId(const std::string& sourceId,const std::string& outputPath) {
    if(!dbManager_ || !source::validId(sourceId))return false;
    const auto locator=source::lookup(dbManager_->getDb(),sourceId);
    if(locator.is_null())return false;
    auto records=searchFiles("source_id='"+sourceId+"' AND type='REG'");
    if(records.size()!=1)return false;
    const auto& record=records.front();
    if(record.path!=locator["logical_path"].get<std::string>() || record.size!=locator["size"].get<int64_t>() || record.isDeleted!=locator["is_deleted"].get<int>())return false;
    if(locator["source_kind"]=="physical" && (record.inode!=locator["inode"].get<int64_t>() || record.partitionNum!=locator["partition_num"].get<int>() || locator.value("data_stream","")!="default"))return false;
    return extractFile(record,outputPath,true,nullptr);
}

json FileExtractor::materializeSource(const std::string& filePath,const fs::path& root,const std::string& requestedId,uint64_t maxBundleBytes) {
    // Serialize publication of bundles across HTTP and initial-analysis readers.
    static std::mutex publicationMutex;
    std::lock_guard<std::mutex> publicationLock(publicationMutex);
    try {
        if(!dbManager_)throw std::runtime_error("SOURCE_INDEX_UNAVAILABLE");
        sqlite3* db=dbManager_->getDb();
        source::Statement binding(db,"SELECT value FROM source_index_meta WHERE key='source_stamp'");
        if(sqlite3_step(binding.value)==SQLITE_ROW) {
            const std::string expected=reinterpret_cast<const char*>(sqlite3_column_text(binding.value,0));
            if(!expected.empty() && source::stamp(imagePath_)!=expected)throw std::runtime_error("SOURCE_CHANGED_AFTER_INDEX");
        }
        const auto embeddedId=source::referenceId(filePath);
        if(!requestedId.empty() && !embeddedId.empty() && requestedId!=embeddedId)throw std::runtime_error("SOURCE_PATH_ID_MISMATCH");
        std::string id=requestedId.empty()?source::referenceId(filePath):requestedId;
        std::string path=source::referencePath(filePath);
        std::replace(path.begin(),path.end(),'\\','/');
        if(id.empty()) {
            if(path.empty())throw std::runtime_error("SOURCE_PATH_REQUIRED");
            const auto alternate=path.front()=='/'?path.substr(1):"/"+path;
            source::Statement s(db,"SELECT source_id FROM files WHERE type='REG' AND path IN (?,?)");s.bind(1,path);s.bind(2,alternate);
            json candidates=json::array();
            while(sqlite3_step(s.value)==SQLITE_ROW) {
                const auto value=sqlite3_column_text(s.value,0);
                if(!value)throw std::runtime_error("SOURCE_INDEX_UNAVAILABLE");
                const std::string candidate=reinterpret_cast<const char*>(value);
                candidates.push_back({{"source_id",candidate},{"locator",source::lookup(db,candidate)}});
            }
            if(candidates.empty())throw std::runtime_error("SOURCE_NOT_FOUND");
            if(candidates.size()!=1)return {{"success",false},{"error","SOURCE_PATH_AMBIGUOUS"},{"message","同一路径对应多个来源记录，请指定来源标识"},{"candidates",candidates}};
            id=candidates[0]["source_id"];
        }
        const auto locator=source::lookup(db,id);
        if(locator.is_null())throw std::runtime_error("SOURCE_NOT_FOUND");
        if(locator.at("size").get<uint64_t>()>std::min<uint64_t>(maxBundleBytes,256ULL*1024*1024))throw std::runtime_error("SOURCE_READ_BUDGET_EXCEEDED");
        uint64_t componentBytes=locator.at("size").get<uint64_t>();
        const auto logicalPath=locator["logical_path"].get<std::string>();
        if(!path.empty() && path!=logicalPath && "/"+path!=logicalPath && path!="/"+logicalPath)throw std::runtime_error("SOURCE_PATH_ID_MISMATCH");
        const auto name=locator["logical_name"].get<std::string>();
        if(name.empty() || name=="." || name==".." || fs::path(name).filename()!=fs::path(name))throw std::runtime_error("SOURCE_NAME_INVALID");
        std::string outputError;
        const auto output=resolveSafeOutputPath(root,"by-source/"+id+"/payload/"+name,&outputError);
        if(!output)throw std::runtime_error("SOURCE_OUTPUT_PATH_UNSAFE");
        const auto published=resolveSafeOutputPath(root,"by-source/"+id+"/source.json",&outputError);
        if(!published)throw std::runtime_error("SOURCE_OUTPUT_PATH_UNSAFE");
        // Published bundles are immutable. A parallel reader must never see a
        // partially overwritten primary or a temporarily removed WAL.
        if(fs::exists(*published)) {
            std::ifstream stream(*published);json existing;stream>>existing;
            if(existing.value("source_id","")!=id || existing["locator"]!=locator || existing.value("payload_directory","")!="payload")throw std::runtime_error("SOURCE_MANIFEST_MISMATCH");
            size_t primaries=0;
            uint64_t publishedBytes=0;
            for(const auto& component:existing.at("components")) {
                const auto bytes=component.at("size").get<uint64_t>();
                if(bytes>maxBundleBytes-publishedBytes)throw std::runtime_error("SOURCE_READ_BUDGET_EXCEEDED");publishedBytes+=bytes;
                const auto filename=component.at("file_name").get<std::string>();
                if(filename!=name && filename!=name+"-wal" && filename!=name+"-journal")throw std::runtime_error("SOURCE_MANIFEST_INVALID");
                const auto part=resolveSafeOutputPath(root,"by-source/"+id+"/payload/"+filename,&outputError);
                if(!part)throw std::runtime_error("SOURCE_OUTPUT_PATH_UNSAFE");
                const auto actual=hashes(*part);
                if(actual["sha256"]!=component.at("sha256") || actual["size"]!=component.at("size"))throw std::runtime_error("SOURCE_HASH_CHANGED");
                if(component.at("role")=="primary")++primaries;
            }
            if(primaries!=1)throw std::runtime_error("SOURCE_MANIFEST_INVALID");
            const auto primary=hashes(*output);
            return {{"success",true},{"source_id",id},{"source_locator",locator},{"materialized_path",output->string()},
                {"manifest_path",published->string()},{"sha256",primary["sha256"]},{"bytes",primary["size"]},
                {"components",existing.at("components")},{"limitations",existing.at("limitations")}};
        }
        fs::create_directories(output->parent_path());
        if(!extractFileBySourceId(id,output->string()))throw std::runtime_error("SOURCE_EXTRACTION_FAILED");
        auto primary=hashes(*output);
        if(primary["size"]!=locator["size"])throw std::runtime_error("SOURCE_SIZE_MISMATCH");
        primary.update({{"role","primary"},{"source_id",id},{"logical_name",name},{"file_name",name}});
        json components=json::array({primary}), notes=json::array();
        // WAL and rollback journals must be from the same acquisition, partition
        // and allocation state. Never choose one of several companion records.
        std::ifstream signature(*output,std::ios::binary);char magic[16]{};signature.read(magic,16);
        if(signature.gcount()==16 && std::string(magic,16)==std::string("SQLite format 3\0",16)) {
            for(const std::string suffix:{"-wal","-journal"}) {
                const auto stale=resolveSafeOutputPath(root,"by-source/"+id+"/payload/"+name+suffix,&outputError);
                if(!stale)throw std::runtime_error("SOURCE_OUTPUT_PATH_UNSAFE");
                if(fs::exists(*stale))fs::remove(*stale);
                source::Statement siblings(db,"SELECT source_id FROM source_objects WHERE path=? AND partition_num=(SELECT partition_num FROM source_objects WHERE source_id=?) AND is_deleted=?");
                siblings.bind(1,logicalPath+suffix);siblings.bind(2,id);sqlite3_bind_int(siblings.value,3,locator["is_deleted"].get<int>());
                std::vector<std::string> ids;
                while(sqlite3_step(siblings.value)==SQLITE_ROW)ids.emplace_back(reinterpret_cast<const char*>(sqlite3_column_text(siblings.value,0)));
                if(ids.size()>1)throw std::runtime_error("COMPANION_SOURCE_AMBIGUOUS");
                if(ids.empty()){notes.push_back(suffix=="-wal"?"COMPANION_WAL_NOT_FOUND":"COMPANION_JOURNAL_NOT_FOUND");continue;}
                const auto other=source::lookup(db,ids[0]);
                if(other["source_revision"]!=locator["source_revision"] || other["source_kind"]!=locator["source_kind"])throw std::runtime_error("COMPANION_SOURCE_MISMATCH");
                if(locator["source_kind"]=="harmony" && (other["logical_location"]["bundle"]!=locator["logical_location"]["bundle"] || other["logical_location"]["app_index"]!=locator["logical_location"]["app_index"]))throw std::runtime_error("COMPANION_SOURCE_MISMATCH");
                const auto companionBytes=other.at("size").get<uint64_t>();
                if(companionBytes>std::min<uint64_t>(maxBundleBytes-componentBytes,256ULL*1024*1024))throw std::runtime_error("SOURCE_READ_BUDGET_EXCEEDED");componentBytes+=companionBytes;
                const auto sibling=resolveSafeOutputPath(root,"by-source/"+id+"/payload/"+name+suffix,&outputError);
                if(!sibling || !extractFileBySourceId(ids[0],sibling->string()))throw std::runtime_error("COMPANION_READ_FAILED");
                auto digest=hashes(*sibling);if(digest["size"]!=other["size"])throw std::runtime_error("COMPANION_SIZE_MISMATCH");
                digest.update({{"role",suffix=="-wal"?"wal":"journal"},{"source_id",ids[0]},{"logical_name",name+suffix},{"file_name",name+suffix},{"locator",other}});components.push_back(digest);
            }
        }
        json manifest={{"schema_version",1},{"payload_directory","payload"},{"source_id",id},{"locator",locator},{"hash_scope","extracted_components"},
            {"components",components},{"limitations",notes}};
        static std::atomic<uint64_t> sequence{0};
        const auto manifestPath=output->parent_path().parent_path()/"source.json";
        const auto temp=manifestPath.parent_path()/("source-"+std::to_string(++sequence)+".tmp");
        {std::ofstream file(temp,std::ios::binary);file<<manifest.dump(2);if(!file)throw std::runtime_error("SOURCE_MANIFEST_WRITE_FAILED");}
        std::error_code ec;
#ifdef _WIN32
        if(!MoveFileExW(temp.c_str(),manifestPath.c_str(),MOVEFILE_REPLACE_EXISTING|MOVEFILE_WRITE_THROUGH))
            ec=std::error_code(GetLastError(),std::system_category());
#else
        fs::rename(temp,manifestPath,ec);
#endif
        if(ec){fs::remove(temp);throw std::runtime_error("SOURCE_MANIFEST_WRITE_FAILED");}
        return {{"success",true},{"source_id",id},{"source_locator",locator},{"materialized_path",output->string()},
            {"manifest_path",manifestPath.string()},{"sha256",primary["sha256"]},{"bytes",primary["size"]},{"components",components},{"limitations",notes}};
    }catch(const std::exception& error){return {{"success",false},{"error",error.what()},{"message","来源读取失败，未改用其他记录"}};}
}
