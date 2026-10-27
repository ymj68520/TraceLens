#include "XiaomiImageExtractor.h"
#include "HarmonyBackupExtractor.h"
#include <openssl/evp.h>
#include <array>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>
#ifndef _WIN32
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <signal.h>
#include <unistd.h>
extern char** environ;
#endif

namespace fs = std::filesystem;
using json = nlohmann::json;
namespace {
std::string digest(const char* data, std::size_t size) {
    unsigned char hash[EVP_MAX_MD_SIZE]; unsigned n = 0;
    if (!EVP_Digest(data, size, hash, &n, EVP_sha256(), nullptr)) return {};
    std::ostringstream out; out << std::hex << std::setfill('0');
    for (unsigned i=0;i<n;++i) out << std::setw(2) << unsigned(hash[i]);
    return out.str();
}
std::int64_t stamp(const fs::path& p) { return fs::last_write_time(p).time_since_epoch().count(); }
bool reader(const std::string& command, const fs::path& source,
            const std::function<void(const json&)>& receive,
            const std::function<void()>& heartbeat = {}, const std::function<bool()>& cancelled = {}) {
#ifdef _WIN32
    return false;
#else
    std::string root;
    if (const char* value=std::getenv("TRACELENS_RELEASE_ROOT"); value && *value) root=value;
#ifdef TRACELENS_SOURCE_ROOT
    else root=TRACELENS_SOURCE_ROOT;
#endif
    std::string python="/usr/bin/python3";
    if (const char* value=std::getenv("TRACELENS_PYTHON_BIN"); value && *value) python=value;
    const auto script=fs::path(root)/"python_service/httpserver/services/xiaomi_image.py";
    if (!fs::path(root).is_absolute() || !fs::path(python).is_absolute() || !fs::is_regular_file(script)) return false;
    std::vector<std::string> args{python,"-B",script.string(),command,source.string()};
    std::vector<char*> argv;for(auto& a:args)argv.push_back(a.data());argv.push_back(nullptr);
    int pipes[2]; if(pipe(pipes)) return false;
    posix_spawn_file_actions_t actions;posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions,pipes[1],STDOUT_FILENO);
    posix_spawn_file_actions_addopen(&actions,STDIN_FILENO,"/dev/null",O_RDONLY,0);
    posix_spawn_file_actions_addopen(&actions,STDERR_FILENO,"/dev/null",O_WRONLY,0);
    posix_spawn_file_actions_addclose(&actions,pipes[0]);posix_spawn_file_actions_addclose(&actions,pipes[1]);
    pid_t pid=-1;const int spawned=posix_spawn(&pid,argv[0],&actions,nullptr,argv.data(),environ);
    posix_spawn_file_actions_destroy(&actions);close(pipes[1]);
    if(spawned){close(pipes[0]);return false;}
    fcntl(pipes[0],F_SETFL,O_NONBLOCK);
    bool okay=true;std::string pending;std::size_t bytes=0;
    const auto start=std::chrono::steady_clock::now();auto last=start;
    try {
        while(true) {
            auto now=std::chrono::steady_clock::now();
            if((cancelled && cancelled()) || now-start>std::chrono::minutes(command=="probe"?1:30)) {okay=false;break;}
            if(heartbeat && now-last>std::chrono::seconds(2)){heartbeat();last=now;}
            pollfd descriptor{pipes[0],POLLIN,0};
            if(poll(&descriptor,1,200)<0){okay=false;break;}
            if(!descriptor.revents)continue;
            std::array<char,65536> buffer{};auto count=read(pipes[0],buffer.data(),buffer.size());
            if(count==0)break;if(count<0)continue;
            bytes+=count;pending.append(buffer.data(),count);
            if(bytes>(512ULL<<20) || pending.size()>(16ULL<<20)){okay=false;break;}
            std::size_t newline;
            while((newline=pending.find('\n'))!=std::string::npos){
                auto line=pending.substr(0,newline);pending.erase(0,newline+1);receive(json::parse(line));
            }
        }
    } catch(...) {okay=false;}
    close(pipes[0]);if(!okay)kill(pid,SIGKILL);
    int status=0;while(waitpid(pid,&status,0)<0 && errno==EINTR){}
    return okay && pending.empty() && WIFEXITED(status) && WEXITSTATUS(status)==0;
#endif
}
std::string column(sqlite3_stmt* s,int i){const auto* p=sqlite3_column_text(s,i);return p?reinterpret_cast<const char*>(p):"";}
}

XiaomiImageExtractor::XiaomiImageExtractor(std::string image):image_(fs::absolute(image).lexically_normal()){}
void XiaomiImageExtractor::setProgress(std::function<void(std::size_t)> p,std::function<bool()> c){progress_=std::move(p);cancelled_=std::move(c);}
bool XiaomiImageExtractor::recognizes(const std::string& path){
    try{
        if(!fs::is_regular_file(path) || fs::is_symlink(fs::symlink_status(path)))return false;
        std::ifstream in(path,std::ios::binary);in.seekg(1080);char magic[2]{};in.read(magic,2);
        if(static_cast<unsigned char>(magic[0])!=0x53 || static_cast<unsigned char>(magic[1])!=0xef)return false;
        bool found=false;
        return reader("probe",fs::absolute(path),[&](const json& j){found=j.value("type","")=="probe" && j.value("layout","")=="dmf_export";}) && found;
    }catch(...){return false;}
}
bool XiaomiImageExtractor::sameSource() const{
    try{
        if(fs::is_symlink(fs::symlink_status(image_)) || !fs::is_regular_file(image_) ||
            fs::file_size(image_)!=manifest_.at("size").get<std::uint64_t>() || stamp(image_)!=sourceTime_)return false;
#ifndef _WIN32
        struct stat info{};if(lstat(image_.c_str(),&info))return false;
        const auto& identity=manifest_.at("source_identity");
        return identity.at("st_dev").get<std::uint64_t>()==static_cast<std::uint64_t>(info.st_dev) &&
            identity.at("st_ino").get<std::uint64_t>()==static_cast<std::uint64_t>(info.st_ino) &&
            identity.at("st_mtime_ns").get<std::int64_t>()==info.st_mtim.tv_sec*1000000000LL+info.st_mtim.tv_nsec &&
            identity.at("st_ctime_ns").get<std::int64_t>()==info.st_ctim.tv_sec*1000000000LL+info.st_ctim.tv_nsec;
#else
        return false;
#endif
    }catch(...){return false;}
}
std::string XiaomiImageExtractor::sourceHash(){
    std::ifstream in(image_,std::ios::binary);if(!in)return {};
    std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)> ctx(EVP_MD_CTX_new(),EVP_MD_CTX_free);
    if(!ctx || EVP_DigestInit_ex(ctx.get(),EVP_sha256(),nullptr)!=1)return {};
    std::array<char,1<<20> buffer{};auto last=std::chrono::steady_clock::now();
    while(in){
        if(cancelled_ && cancelled_()){error_="CANCELLED";return {};}
        in.read(buffer.data(),buffer.size());if(in.gcount() && EVP_DigestUpdate(ctx.get(),buffer.data(),in.gcount())!=1)return {};
        if(progress_ && std::chrono::steady_clock::now()-last>std::chrono::seconds(2)){progress_(entries_.size());last=std::chrono::steady_clock::now();}
    }
    if(in.bad())return {};
    unsigned char hash[EVP_MAX_MD_SIZE];unsigned n=0;if(EVP_DigestFinal_ex(ctx.get(),hash,&n)!=1)return {};
    std::ostringstream out;out<<std::hex<<std::setfill('0');for(unsigned i=0;i<n;++i)out<<std::setw(2)<<unsigned(hash[i]);return out.str();
}
bool XiaomiImageExtractor::add(const json& row){
    const std::string path=row.at("path");
    if(entries_.size()>=500000 || path.empty() || path[0]!='/' || path.size()>12288)return false;
    for(const auto& part:fs::path(path).relative_path())if(part==".." || part==".")return false;
    Entry e;e.path=path;e.originalPath=path;e.bundle=row.value("package","");e.container=image_.string();e.size=row.at("size");
    e.containerSize=manifest_.at("size");e.containerTime=sourceTime_;
    // Export filesystem timestamps are not verified handset activity timestamps.
    e.modified=0;e.offset=row.at("inode");
    if(!entries_.emplace(path,e).second)return false;
    locations_[path]=row;
    if(!row.at("readable").get<bool>())coverage_.push_back({{"path",path},{"status","UNSUPPORTED"},{"detail",row.at("error")}});
    return true;
}
bool XiaomiImageExtractor::initialize(){
    entries_.clear();locations_.clear();used_.clear();coverage_=json::array();error_.clear();
    try{
        sourceTime_=stamp(image_);bool completed=false;
        const bool okay=reader("index",image_,[&](const json& row){
            const auto type=row.value("type","");
            if(type=="meta")manifest_=row.at("manifest");
            else if(type=="file"){if(!add(row))throw std::runtime_error("来源索引无效");}
            else if(type=="warning")coverage_.push_back({{"path",row.at("path")},{"status","UNSUPPORTED"},{"detail",row.at("detail")}});
            else if(type=="error"){error_=row.value("detail","镜像读取失败");throw std::runtime_error(error_);}
            else if(type=="complete")completed=true;
        },[&](){if(progress_)progress_(entries_.size());},cancelled_);
        if(!okay || !completed || entries_.empty() || !sameSource()){
            if(error_.empty())error_=cancelled_ && cancelled_()?"CANCELLED":"小米导出镜像索引未完成";return false;
        }
        manifest_["manifest_sha256"]=manifest_.at("source_sha256");manifest_["modules"]=json::array();
        std::map<std::string,std::uint64_t> packages;
        for(const auto& [_,e]:entries_)if(!e.bundle.empty())packages[e.bundle]+=e.size;
        for(const auto& [package,size]:packages)manifest_["modules"].push_back({{"bundle",package},{"name",package},{"declared_size",size}});
        manifest_["file_count"]=entries_.size();manifest_["coverage_count"]=coverage_.size();return true;
    }catch(const std::exception& e){error_=e.what();return false;}
}
bool XiaomiImageExtractor::verifyIntegrity(){
    if(!sameSource() || sourceHash()!=manifest_.value("source_sha256","") || !sameSource()){
        if(error_!="CANCELLED")error_="EVIDENCE_CHANGED_AFTER_INDEX";return false;
    }return true;
}
bool XiaomiImageExtractor::saveIndex(sqlite3* db) const{
    if(sqlite3_exec(db,"CREATE TABLE IF NOT EXISTS xiaomi_source_meta(key TEXT PRIMARY KEY,value TEXT);"
        "CREATE TABLE IF NOT EXISTS xiaomi_source_files(path TEXT PRIMARY KEY,location_json TEXT NOT NULL);"
        "DELETE FROM xiaomi_source_meta;DELETE FROM xiaomi_source_files;",nullptr,nullptr,nullptr)!=SQLITE_OK)return false;
    sqlite3_stmt* s=nullptr;
    if(sqlite3_prepare_v2(db,"INSERT INTO xiaomi_source_meta VALUES(?,?)",-1,&s,nullptr)!=SQLITE_OK)return false;
    for(const auto& [k,v]:std::map<std::string,std::string>{{"source",image_.string()},{"stamp",std::to_string(sourceTime_)},{"manifest",manifest_.dump()},{"coverage",coverage_.dump()}}){
        sqlite3_bind_text(s,1,k.c_str(),-1,SQLITE_TRANSIENT);sqlite3_bind_text(s,2,v.c_str(),-1,SQLITE_TRANSIENT);
        if(sqlite3_step(s)!=SQLITE_DONE){sqlite3_finalize(s);return false;}sqlite3_reset(s);
    }sqlite3_finalize(s);
    if(sqlite3_prepare_v2(db,"INSERT INTO xiaomi_source_files VALUES(?,?)",-1,&s,nullptr)!=SQLITE_OK)return false;
    for(const auto& [path,row]:locations_){const auto value=row.dump();sqlite3_bind_text(s,1,path.c_str(),-1,SQLITE_TRANSIENT);sqlite3_bind_text(s,2,value.c_str(),-1,SQLITE_TRANSIENT);
        if(sqlite3_step(s)!=SQLITE_DONE){sqlite3_finalize(s);return false;}sqlite3_reset(s);
    }sqlite3_finalize(s);return true;
}
bool XiaomiImageExtractor::loadIndex(sqlite3* db){
    try{
        sqlite3_stmt* raw=nullptr;
        if(sqlite3_prepare_v2(db,"SELECT key,value FROM xiaomi_source_meta",-1,&raw,nullptr)!=SQLITE_OK)return false;
        std::unique_ptr<sqlite3_stmt,decltype(&sqlite3_finalize)> statement(raw,sqlite3_finalize);
        std::map<std::string,std::string> meta;int rc;
        while((rc=sqlite3_step(raw))==SQLITE_ROW)meta[column(raw,0)]=column(raw,1);
        if(rc!=SQLITE_DONE || meta.at("source")!=image_.string())return false;
        sourceTime_=std::stoll(meta.at("stamp"));manifest_=json::parse(meta.at("manifest"));coverage_=json::array();
        // The index and final analysis hash the entire image. Each later read
        // validates dev/inode/size/mtime/ctime and its exact inode bytes; avoid
        // re-reading tens of GiB for every file preview.
        if(!sameSource()){error_="EVIDENCE_CHANGED_AFTER_INDEX";return false;}
        if(sqlite3_prepare_v2(db,"SELECT path,location_json FROM xiaomi_source_files ORDER BY path",-1,&raw,nullptr)!=SQLITE_OK)return false;
        statement.reset(raw);entries_.clear();locations_.clear();
        while((rc=sqlite3_step(raw))==SQLITE_ROW){auto row=json::parse(column(raw,1));if(row.at("path")!=column(raw,0) || !add(row))return false;}
        coverage_=json::parse(meta.at("coverage"));return rc==SQLITE_DONE && entries_.size()==manifest_.at("file_count").get<std::size_t>();
    }catch(const std::exception& e){error_=e.what();return false;}
}
bool XiaomiImageExtractor::extractFileByPath(const std::string& request,const std::string& output){
    const std::string path=request.starts_with('/')?request:"/"+request;bool created=false;error_.clear();
    try{
        const auto found=locations_.find(path);if(found==locations_.end())return false;
        const auto& row=found->second;if(!row.at("readable").get<bool>()){error_=row.value("error","文件未支持");return false;}
        if(!sameSource())throw std::runtime_error("EVIDENCE_CHANGED_AFTER_INDEX");
        const auto dest=fs::absolute(output).lexically_normal();
        if(fs::exists(dest) || fs::is_symlink(fs::symlink_status(dest)) || fs::weakly_canonical(dest)==fs::canonical(image_))return false;
        std::ifstream in(image_,std::ios::binary);const auto inodeSize=row.at("inode_size").get<std::size_t>();
        if(inodeSize>4096)throw std::runtime_error("来源 inode 大小无效");
        std::vector<char> inode(inodeSize);in.seekg(row.at("inode_offset").get<std::uint64_t>());in.read(inode.data(),inode.size());
        if(in.gcount()!=static_cast<std::streamsize>(inode.size()) || digest(inode.data(),inode.size())!=row.at("inode_sha256").get<std::string>())throw std::runtime_error("EVIDENCE_CHANGED_INODE");
        fs::create_directories(dest.parent_path());
#ifndef _WIN32
        const int fd=open(dest.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);if(fd<0)return false;close(fd);
#else
        return false;
#endif
        created=true;std::ofstream out(dest,std::ios::binary|std::ios::trunc);if(!out)throw std::runtime_error("文件输出失败");
        const auto size=row.at("size").get<std::uint64_t>();if(size>(8ULL<<30))throw std::runtime_error("文件大小超限");
        std::uint64_t position=0,end=0;std::array<char,65536> buffer{};
        auto zeros=[&](std::uint64_t n){buffer.fill(0);while(n){auto take=std::min<std::uint64_t>(n,buffer.size());out.write(buffer.data(),take);n-=take;position+=take;}};
        for(const auto& run:row.at("runs")){
            const auto logical=run.at(0).get<std::uint64_t>(),length=run.at(2).get<std::uint64_t>();const auto physical=run.at(1).get<std::int64_t>();
            if(logical<end || !length || length>(2ULL<<40) || logical>UINT64_MAX-length)throw std::runtime_error("来源区段无效或重叠");
            end=logical+length;if(position>=size)break;
            if(logical>position)zeros(std::min(size-position,logical-position));
            if(position>=size)break;auto left=std::min(length,size-position);
            if(physical==-1){zeros(left);continue;}
            if(physical<0 || static_cast<std::uint64_t>(physical)>fs::file_size(image_) || left>fs::file_size(image_)-physical)throw std::runtime_error("来源区段越界");
            in.seekg(physical);
            while(left){if(cancelled_ && cancelled_())throw std::runtime_error("CANCELLED");auto n=std::min<std::uint64_t>(left,buffer.size());in.read(buffer.data(),n);if(in.gcount()!=static_cast<std::streamsize>(n))throw std::runtime_error("来源读取不完整");out.write(buffer.data(),n);left-=n;position+=n;}
        }
        if(position<size)zeros(size-position);out.close();if(!out || !sameSource())throw std::runtime_error("来源发生变化或输出失败");
        const auto hash=HarmonyBackupExtractor::sha256(dest);if(hash.empty())throw std::runtime_error("文件哈希计算失败");
        AndroidSourceProvenance p{image_.string(),manifest_.at("source_sha256"),path,path,static_cast<std::size_t>(size),hash,"xiaomi-image","xiaomi-export-ext4-v1"};
        p.filesystemObjectId=std::to_string(row.at("inode").get<std::uint64_t>());p.filesystemType="ext4-export";p.partitionName="导出镜像文件系统";p.filesystemReader="xiaomi-export-ext4-v1";p.imageContainerType="raw";used_[path]=p;
        if(progress_)progress_(used_.size());return true;
    }catch(const std::exception& e){error_=e.what();if(created){std::error_code ec;fs::remove(output,ec);}return false;}
}
std::vector<std::string> XiaomiImageExtractor::findPathsByFilename(const std::string& name,std::size_t limit)const{
    std::vector<std::string> out;for(const auto& [path,_]:entries_)if(fs::path(path).filename()==name && out.size()<limit)out.push_back(path);return out;
}
bool XiaomiImageExtractor::readRange(const std::string& path,std::uint64_t offset,std::size_t length,std::string& data,std::string& error) {
    data.clear();error.clear();
    try {
        const auto& row=locations_.at(path);const auto size=row.at("size").get<std::uint64_t>();
        if(length>65536 || offset>size || !row.at("readable").get<bool>())throw std::runtime_error("SOURCE_RANGE_INVALID");
        if(!sameSource())throw std::runtime_error("EVIDENCE_CHANGED_AFTER_INDEX");
        std::ifstream in(image_,std::ios::binary);
        const auto inodeSize=row.at("inode_size").get<std::size_t>();if(inodeSize>4096)throw std::runtime_error("SOURCE_RECORD_CHANGED");
        std::string inode(inodeSize,'\0');in.seekg(row.at("inode_offset").get<std::uint64_t>());in.read(inode.data(),inode.size());
        if(in.gcount()!=static_cast<std::streamsize>(inode.size()) || digest(inode.data(),inode.size())!=row.at("inode_sha256").get<std::string>())throw std::runtime_error("EVIDENCE_CHANGED_INODE");
        length=std::min<std::uint64_t>(length,size-offset);data.assign(length,'\0');
        std::uint64_t previous=0;
        for(const auto& run:row.at("runs")) {
            auto logical=run.at(0).get<std::uint64_t>(),n=run.at(2).get<std::uint64_t>();auto physical=run.at(1).get<std::int64_t>();
            if(!n || logical<previous || logical>UINT64_MAX-n)throw std::runtime_error("SOURCE_RECORD_CHANGED");previous=logical+n;
            const auto begin=std::max(offset,logical),end=std::min(offset+length,logical+n);
            if(begin>=end || physical==-1)continue;
            const auto delta=begin-logical,count=end-begin;
            if(physical<0 || static_cast<uint64_t>(physical)>fs::file_size(image_) || delta>fs::file_size(image_)-physical || count>fs::file_size(image_)-physical-delta)throw std::runtime_error("SOURCE_RECORD_CHANGED");
            in.seekg(physical+delta);in.read(data.data()+begin-offset,count);
            if(in.gcount()!=static_cast<std::streamsize>(count))throw std::runtime_error("SOURCE_RANGE_READ_FAILED");
        }
        if(!sameSource())throw std::runtime_error("EVIDENCE_CHANGED_AFTER_INDEX");return true;
    }catch(const std::exception& e){data.clear();error=e.what();return false;}
}
std::vector<AndroidSourceProvenance> XiaomiImageExtractor::usedSourceProvenance()const{
    std::vector<AndroidSourceProvenance> out;for(const auto& [_,p]:used_)out.push_back(p);return out;
}
