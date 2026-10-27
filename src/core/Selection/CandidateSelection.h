#pragma once
#include "DatabaseManager/SourceIndex.h"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <functional>
#include <map>
#include <memory>
#include <queue>
#include <set>
#include <unordered_set>
#include <openssl/evp.h>

// Pure selection policy shared by native task analysis, HTTP and Python clients.
// Probes are injected; the policy never interprets a path as a host file.
namespace forensics::selection {
using json=nlohmann::json;
inline constexpr const char* policyVersion="candidate-selection:v7-user-programs";
struct Budget {
    size_t candidates=1000,files=500,probeFiles=2000,probeBytes=128*1024*1024,probePerFile=65536;
    size_t semanticFiles=500,semanticBytes=1024ULL*1024*1024;
    int seconds=300;
    bool skipExecutables=true;
    bool visionAvailable=false;
    std::string seed="tracelens-selection-v1";
    std::string analysisContract="file-analysis:v2";
    int64_t maxCalls=1000,maxTokens=4096000;
    std::vector<std::string> fileReferences,fileTypes;
    json asJson() const {return {{"candidates",candidates},{"files",files},{"probe_files",probeFiles},
        {"probe_bytes",probeBytes},{"probe_per_file",probePerFile},{"semantic_files",semanticFiles},
        {"semantic_bytes",semanticBytes},{"seconds",seconds},{"skip_executables",skipExecutables},{"seed",seed},
        {"analysis_contract",analysisContract},{"max_calls",maxCalls},{"max_tokens",maxTokens},
        {"file_references",fileReferences},{"file_types",fileTypes},{"vision_available",visionAvailable}};}
};
struct Candidate {
    std::string task,id,path,name,category,key,context,cluster,family="other",format="unknown",state="unprobed",hash,group,reason,resourceGroup;
    int64_t size=0,mtime=0,inode=0;int partition=0,deleted=0,score=0,diversityPenalty=0;
    bool eligible=true,cache=false,exploration=false,explicitSelection=false;
    json probe=json::object();
    json scoreParts=json::object();
    std::string reference() const {return sources::reference(id,path);}
    json asJson() const {return {{"task_id",task},{"source_id",id},{"path",path},{"reference",reference()},
        {"source_key",task+":"+reference()},
        {"size",size},{"partition_num",partition},{"inode",inode},{"is_deleted",deleted},{"family",family},
        {"score",score},{"score_parts",scoreParts},{"diversity_penalty",diversityPenalty},{"format",format},{"probe_state",state},{"probe",probe},{"group_id",group},
        {"reason",reason},{"resource_group",resourceGroup},{"lane",explicitSelection?"explicit":(exploration?"exploration":"quota")}};}
};
inline std::string lower(std::string value){for(auto& c:value)c=static_cast<char>(std::tolower(static_cast<unsigned char>(c)));return value;}
inline bool contains(const std::string& value,const std::vector<std::string>& tokens){for(auto& token:tokens)if(value.find(token)!=std::string::npos)return true;return false;}
inline bool ends(const std::string& value,const std::string& suffix){return value.size()>=suffix.size() && value.compare(value.size()-suffix.size(),suffix.size(),suffix)==0;}
inline std::string parent(const std::string& path){const auto pos=path.find_last_of('/');return pos==std::string::npos?"":path.substr(0,pos);}
inline bool systemExecutable(const std::string& path){
    const auto p=lower(path);
    for(const std::string prefix:{"/windows/","/windows.old/","/program files/","/program files (x86)/","/programdata/microsoft/",
        "/usr/bin/","/usr/sbin/","/bin/","/sbin/","/usr/lib/","/lib/","/lib64/"})if(p.rfind(prefix,0)==0)return true;
    return false;
}
inline bool boundedKeyword(const std::string& path,const std::string& word){
    size_t at=path.find(word);
    while(at!=std::string::npos){const auto end=at+word.size();
        if((at==0 || !std::isalnum(static_cast<unsigned char>(path[at-1]))) &&
           (end==path.size() || !std::isalnum(static_cast<unsigned char>(path[end]))))return true;
        at=path.find(word,at+1);
    }
    return false;
}
inline bool caseToolDirectory(const std::string& path){
    const auto p=parent(lower(path));
    for(const std::string word:{"控制端","木马","远控","恶意","样本","后门","清理","反取证","quasar","njrat","darkcomet",
        "gh0st","remcos","asyncrat","xworm","cobalt","meterpreter","backdoor","payload","privazer","ccleaner","eraser","rat"})
        if(boundedKeyword(p,word))return true;
    return false;
}
inline std::string resourcePackage(const std::string& path) {
    const auto p=lower(path);
    for(const std::string marker:{"/.m2/repository/","/.gradle/caches/","/.git/objects/","/.git/modules/","/.npm/","/.yarn/","/.pnpm-store/","/.cargo/registry/","/go/pkg/mod/",
        "/appdata/local/programs/","/chrome/application/","/public/static/plugs/","/public/static/plugins/","/usr/src/kernels/","/usr/share/cmake/","/var/lib/yum/yumdb/",
        "/_locales/","/locales/","/node_modules/","/site-packages/","/vendor/","/thinkphp/","/mysql-test/","/winsxs/","/usr/share/doc/","/usr/share/man/","/usr/lib/","/lib64/"}) {
        const auto at=p.find(marker);
        if(at!=std::string::npos){
            if(marker=="/_locales/" || marker=="/locales/")return p.substr(0,at)+":language-resources";
            const auto end=p.find('/',at+marker.size());return p.substr(0,end)+":software-resources";
        }
    }
    if(p.rfind("/usr/local/",0)==0 && p.find("/man/man")!=std::string::npos)
        return p.substr(0,p.find("/man/man"))+":manual-pages";
    if(p.rfind("/var/log/anaconda/",0)==0 && ends(p,".hdr"))
        return "/var/log/anaconda:package-headers";
    if(contains(p,{"/systemapps/","/windowsapps/"}) && contains(p,{"/assets/","/strings/","/images/"}))
        return parent(p)+":software-resources";
    return "";
}
inline bool executableSignature(const std::string& data){
    if(data.size()>=16 && data.compare(0,4,std::string("\x7f" "ELF",4))==0)
        return (data[4]==1 || data[4]==2) && (data[5]==1 || data[5]==2) && data[6]==1;
    if(data.size()<64 || data.compare(0,2,"MZ")!=0)return false;
    uint32_t offset=0;for(int i=0;i<4;++i)offset|=static_cast<uint32_t>(static_cast<unsigned char>(data[60+i]))<<(8*i);
    return offset<=data.size()-4 && data.compare(offset,4,std::string("PE\0\0",4))==0;
}
inline void classify(Candidate& c){
    const auto p=lower(c.path),n=lower(c.name);
    const bool user=contains(p,{"/users/","/home/","/root/","/data/data/","/data/user/","/files/basic/","/var/www/","/www/wwwroot/","/srv/"});
    c.context=c.task+":"+parent(c.path)+":"+std::to_string(c.deleted);
    c.cluster=c.context;c.score=user?45:20;
    c.cache=contains(p,{"/cache/","/runtime/temp/","/code cache/","/cache_data/","/cachestorage/","/domstore/","/inetcache/","/thumbcache"});
    if(contains(n,{"history","cookies","places.sqlite","login data","web data","msgstore","mm.sqlite","sms.db","contacts.db"}) &&
       !contains(p,{"/code cache/","/node_modules/","/site-packages/"})) {c.family="browser";c.score=95;}
    else if(ends(n,".evtx") || ends(n,".pf") || ends(n,".lnk") || contains(n,{"automaticdestinations","customdestinations","ntuser.dat","usrclass.dat","amcache.hve"}) ||
        contains(p,{"/system32/config/","/var/log/","/www/wwwlogs/","/srum/"})) {c.family="activity";c.score=72;}
    else if(contains(p,{"/system32/tasks/","/etc/systemd/","/etc/cron","/etc/ssh/","/var/spool/cron/","/etc/init.d/"}) || ends(n,".ps1") || ends(n,".sh") || ends(n,".exe") || ends(n,".dll")) {c.family="program";c.score=user?82:40;}
    else if(contains(p,{"/desktop/","/documents/","/downloads/","/wwwroot/","/profiles/"}) ||
        contains(n,{"settings.xml",".bash_history","authorized_keys"}) || ends(n,".docx") || ends(n,".xlsx") || ends(n,".pdf") || ends(n,".txt") || ends(n,".json") || ends(n,".xml") || ends(n,".conf") || ends(n,".ini")) {c.family="business";c.score=user?90:38;}
    if(c.family=="business" && contains(p,{"/desktop/","/documents/","/downloads/"}))c.score=112;
    if(c.family=="business" && user && (n=="settings.xml" || n=="settings.json" || n=="preferences"))c.score=std::max(c.score,100);
    if(contains(p,{"/system32/tasks/","/etc/systemd/","/etc/cron","/etc/ssh/","/var/spool/cron/","/etc/init.d/"})){c.family="program";c.score=95;}
    if(p=="/etc/passwd" || p=="/etc/shadow" || n=="authorized_keys" || n=="known_hosts"){c.family="program";c.score=100;}
    if(n==".bash_history" || n==".zsh_history"){c.family="activity";c.score=100;}
    const bool application=contains(p,{"/www/wwwroot/","/var/www/","/srv/"});
    if(application && (ends(n,".php") || ends(n,".py") || ends(n,".js"))){c.family="business";c.score=100;}
    if(application && contains(p,{"/controller/","/controllers/","/model/","/models/","/routes/","/service/","/services/"})) {c.family="business";c.score=118;}
    if(contains(p,{"/file_history/","/runtime/cache/"}))c.score=std::min<int64_t>(c.score,65);
    if(ends(n,".jpg") || ends(n,".jpeg") || ends(n,".png") || ends(n,".mp4") || ends(n,".mp3") || ends(n,".wav") || ends(n,".m4a") || ends(n,".amr") || ends(n,".mov")){c.family="media";c.score=user?65:20;}
    if(c.cache)c.score=8;
    if(contains(p,{"/www/server/panel/vhost/","/etc/nginx/","/etc/httpd/","/etc/apache2/"}) ||
       n=="database.php" || n==".env" || n=="my.cnf" || n=="sshd_config") {c.family="program";c.score=114;}
    if(p=="/etc/centos-release" || p=="/etc/os-release" || p=="/etc/redhat-release" || p=="/etc/hostname") {c.family="activity";c.score=105;}
    if(contains(p,{"/var/log/secure","/var/log/auth.log","/var/log/wtmp","/var/log/btmp"}) || n==".bash_history") {c.family="activity";c.score=115;}
    const bool programArea=contains(p,{"/users/","/home/","/root/"}) || (p.rfind("/programdata/",0)==0 && p.rfind("/programdata/microsoft/",0)!=0);
    if(programArea && (ends(n,".exe") || ends(n,".bin") || ends(n,".scr") || ends(n,".com") || ends(n,".pif") ||
        ends(n,".ps1") || ends(n,".vbs") || ends(n,".js") || ends(n,".jse") || ends(n,".hta") || ends(n,".bat") || ends(n,".cmd") || ends(n,".jar") || ends(n,".py") || ends(n,".sh"))) {
        c.family="program";c.score=std::max(c.score,116);
    }
    if(caseToolDirectory(p)){c.score=std::max(c.score,115);if(c.family=="other")c.family="business";}
    c.resourceGroup=resourcePackage(p);
    if(!c.resourceGroup.empty()){c.family="resource";c.score=6;c.cluster=c.task+":"+c.resourceGroup;}
    if(n=="authorized_keys" || n=="known_hosts" || n=="id_rsa" || n=="id_ed25519"){
        c.resourceGroup.clear();c.family="program";c.score=115;c.cluster=c.context;
    }
    if(n=="desktop.ini" || n=="thumbs.db"){c.cache=true;c.score=6;}
    c.scoreParts={{"role_prior",c.score}};
    c.key=c.task+":"+std::to_string(c.partition)+":"+std::to_string(c.inode)+":"+c.path+":"+std::to_string(c.deleted)+":"+c.id;
}
inline bool better(const Candidate& a,const Candidate& b){return a.score!=b.score?a.score>b.score:a.key<b.key;}
inline std::string cleanText(const std::string& data){return json::parse(json(data).dump(-1,' ',false,json::error_handler_t::replace)).get<std::string>();}
inline uint32_t crc32(const std::string& data){uint32_t crc=0xffffffffu;for(unsigned char c:data){crc^=c;for(int i=0;i<8;++i)crc=(crc>>1)^(0xedb88320u & (0u-(crc&1)));}return crc^0xffffffffu;}
inline uint32_t little(const std::string& data,size_t offset,size_t length=4){uint32_t value=0;for(size_t i=0;i<length;++i)value|=static_cast<uint32_t>(static_cast<unsigned char>(data.at(offset+i)))<<(8*i);return value;}
inline bool verifiedEmptyEvtxHeaders(const std::string& data,uint64_t sourceSize){
    if(data.size()<4096 || data.compare(0,8,std::string("ElfFile\0",8))!=0 || little(data,38,2)!=3 ||
        (little(data,36,2)!=1 && little(data,36,2)!=2) || little(data,40,2)!=4096 || little(data,120)!=0 || crc32(data.substr(0,120))!=little(data,124))return false;
    const auto chunks=little(data,42,2);
    if(chunks==0)return sourceSize==4096;
    if(chunks!=1 || sourceSize<4096+65536 || data.size()<4608)return false;
    const auto block=data.substr(4096,512);
    // Accept only the observed standard empty-chunk flag, never unknown flags.
    // These headers describe visible records; inactive/recovered data is not scanned.
    return block.compare(0,8,std::string("ElfChnk\0",8))==0 && little(block,40)==128 && little(block,44)==0 &&
        little(block,48)==512 && little(block,52)==0 && little(block,120)==1 &&
        crc32(block.substr(0,120)+block.substr(128,384))==little(block,124);
}
inline json inspectBytes(const std::string& data,bool complete,uint64_t sourceSize=0){
    json result={{"state","signature_confirmed"},{"bytes",data.size()},{"complete",complete},{"format","unknown"},
        {"window_sha256",sources::hash(data)},{"window_offset",0},{"window_hash_scope","probe_window"}};
    if(data.empty()){result["state"]=complete?"empty":"unprobed";return result;}
    if(data.compare(0,16,std::string("SQLite format 3\0",16))==0)result["format"]="sqlite";
    else if(data.compare(0,4,"regf")==0)result["format"]="registry";
    else if(data.compare(0,8,std::string("ElfFile\0",8))==0){result["format"]="evtx";
        if(verifiedEmptyEvtxHeaders(data,sourceSize?sourceSize:(complete?data.size():0))){
            result["state"]="metadata_only";result["coverage"]={{"record_count",0},{"record_scope","standard_visible_headers"},
                {"header_checksums_verified",true},{"recovered_records_included",false}};
        }}
    else if(data.compare(0,3,"MAM")==0 || (data.size()>=8 && data.compare(4,4,"SCCA")==0))result["format"]="prefetch";
    else if(executableSignature(data))result["format"]="executable";
    else if(data.compare(0,4,"PK\3\4")==0)result["format"]="zip_container";
    else if(data.compare(0,5,"%PDF-")==0)result["format"]="pdf";
    else if(data.size()>=8 && (data.compare(0,8,std::string("\x89PNG\r\n\x1a\n",8))==0 ||
            (static_cast<unsigned char>(data[0])==0xff && static_cast<unsigned char>(data[1])==0xd8)))result["format"]="image";
    else if(data.size()>=20 && static_cast<unsigned char>(data[0])==0x4c && data[1]==0 && data[2]==0 && data[3]==0 && data.substr(4,4)==std::string("\1\24\2\0",4))result["format"]="lnk";
    else if(data.size()>=2 && ((static_cast<unsigned char>(data[0])==0xff && static_cast<unsigned char>(data[1])==0xfe) ||
            (static_cast<unsigned char>(data[0])==0xfe && static_cast<unsigned char>(data[1])==0xff)))result["format"]="text_utf16";
    else {
        size_t controls=0;for(unsigned char c:data)if(c<32 && c!='\n' && c!='\r' && c!='\t' && c!='\f')++controls;
        if(controls==0){
            bool valid=false;for(size_t trim=0;trim<=(complete?0:std::min<size_t>(3,data.size()));++trim)try{json(data.substr(0,data.size()-trim)).dump();valid=true;break;}catch(...){}
            if(!valid){result["state"]="unprobed";result["format"]="text_unknown_encoding";return result;}
            result["format"]="text";result["state"]=(complete && data.find_first_not_of(" \t\r\n\f")==std::string::npos)?"empty":"readable";const auto preview=cleanText(data.substr(0,768));result["preview"]=preview;
            // Soft grouping only. Never erase numbers, dates or addresses.
            std::string normalized;bool space=false;for(unsigned char c:data){if(std::isspace(c)){if(!space)normalized+=' ';space=true;}else {normalized+=c;space=false;}}
            result["template_hash"]=sources::hash(normalized);}
    }
    // A SQLite main file without its WAL is never an exact content package.
    if(complete && result["format"]!="sqlite")result["sha256"]=sources::hash(data);
    return result;
}
inline void applyProbe(Candidate& c,const json& probe){
    if(probe.value("state","")=="unprobed" && c.state=="signature_confirmed" && c.format!="unknown"){
        c.probe["semantic_probe"]=probe;return; // Preserve a valid cheaper observation.
    }
    c.probe=probe;c.state=probe.value("state","unprobed");c.format=probe.value("format",c.format);
    const auto oldScore=c.score;
    if(c.family=="other" && c.format=="sqlite"){c.family="browser";c.score=std::max(c.score,75);}
    if(c.family=="other" && contains(c.format,{"registry","prefetch","evtx"})){c.family="activity";c.score=std::max(c.score,70);}
    c.scoreParts["format_support"]=c.scoreParts.value("format_support",0)+c.score-oldScore;
    if(contains(c.state,{"error","unavailable","unsupported","empty","metadata_only"})) {
        c.eligible=false;
        c.reason=c.state=="metadata_only"?"仅有元数据，没有可用记录正文":c.state=="empty"?"空内容，仅登记覆盖情况":
            c.state=="unsupported"?"当前解析器未支持该格式":c.state=="source_error"?"来源校验或读取失败，保持未知":"解析失败，未将诊断当作正文";
        return;}
    if(c.state=="readable" || c.state=="ok" || c.state=="partial"){
        c.score+=20;c.scoreParts["readability"]=20;
        const auto coverage=probe.value("coverage",json::object());
        const auto n=coverage.value("parsed_record_count",coverage.value("record_count",json(nullptr)));
        if(n.is_number_integer() && n.get<int64_t>()>0){const auto bonus=std::min(10,static_cast<int>(std::log2(1.0+n.get<int64_t>())*2));c.score+=bonus;c.scoreParts["observed_records"]=bonus;}
        if(coverage.contains("earliest_utc") && !coverage["earliest_utc"].is_null()){c.score+=4;c.scoreParts["observed_time_range"]=4;}
    }
    if(probe.contains("template_hash"))c.cluster=c.context+":"+probe["template_hash"].get<std::string>();
    c.hash=probe.value("bundle_sha256",probe.value("sha256",std::string()));
    if(!c.hash.empty())c.group=sources::hash(c.hash+":"+c.context+":"+c.format+(c.format=="registry"?":"+lower(c.name):""));
}

using Probe=std::function<json(const Candidate&,size_t)>;
using SemanticProbe=std::function<json(const std::vector<Candidate>&,const Budget&)>;
struct Input {std::string database,task;};

inline std::vector<Candidate> diversify(std::vector<Candidate> values,size_t count,const std::string& seed,bool explore=false){
    if(explore)std::sort(values.begin(),values.end(),[&](const auto&a,const auto&b){return sources::hash(seed+a.key)<sources::hash(seed+b.key);});
    else std::sort(values.begin(),values.end(),better);
    std::map<std::string,std::vector<Candidate>> clusters;
    for(auto& c:values)clusters[c.cluster].push_back(std::move(c));
    std::vector<Candidate> result;
    if(!explore){
        struct Head {std::string cluster,key;size_t position;int score;};
        struct Weaker {bool operator()(const Head&a,const Head&b)const{return a.score!=b.score?a.score<b.score:a.key>b.key;}};
        std::priority_queue<Head,std::vector<Head>,Weaker> heads;
        for(const auto& [key,group]:clusters)heads.push({key,group[0].key,0,group[0].score});
        while(!heads.empty() && result.size()<count){
            auto head=heads.top();heads.pop();auto& group=clusters.at(head.cluster);auto c=group[head.position];
            c.diversityPenalty=4*static_cast<int>(std::min<size_t>(head.position,10));result.push_back(std::move(c));
            if(++head.position<group.size())heads.push({head.cluster,group[head.position].key,head.position,group[head.position].score-4*static_cast<int>(std::min<size_t>(head.position,10))});
        }
        return result;
    }
    for(size_t round=0;result.size()<count;++round){
        std::vector<Candidate> heads;
        for(auto& [_,group]:clusters)if(round<group.size())heads.push_back(group[round]);
        if(heads.empty())break;
        if(explore)std::sort(heads.begin(),heads.end(),[&](const auto&a,const auto&b){return sources::hash(seed+a.key)<sources::hash(seed+b.key);});
        else std::sort(heads.begin(),heads.end(),better);
        for(auto& c:heads){if(result.size()==count)break;result.push_back(std::move(c));}
    }
    return result;
}
inline std::vector<Candidate> allocate(const std::vector<Candidate>& rows,size_t count,const std::string& seed,bool explicitMode=false){
    std::vector<Candidate> result;std::set<std::string> used,groups;std::map<std::string,size_t> templateCounts;
    size_t cacheCount=0;const auto cacheCap=explicitMode?count:std::max<size_t>(1,count/20);
    size_t resourceCount=0;std::map<std::string,size_t> resourceCounts;
    const auto resourceCap=std::max<size_t>(1,std::min<size_t>(20,count/20));
    auto add=[&](Candidate c,bool explore){
        if(result.size()>=count || !c.eligible || used.count(c.key) || (!explicitMode && !c.group.empty() && groups.count(c.group)))return false;
        if(c.cache && cacheCount>=cacheCap)return false;
        if(!explicitMode && !c.resourceGroup.empty() && (resourceCount>=resourceCap || resourceCounts[c.task+c.resourceGroup]>=2))return false;
        const auto pattern=c.probe.value("template_hash",std::string());
        // Similar templates affect scheduling only. Whitespace in code or
        // quoted values can be meaningful, so it is never an identity gate.
        c.exploration=explore;c.reason=explore?"探索抽样：补充规则覆盖不足的来源":"类别配额：兼顾内容状态和来源覆盖";
        if(explicitMode){c.explicitSelection=true;c.reason="用户指定来源：通过读取能力和数量预算准入";}
        used.insert(c.key);if(!c.group.empty())groups.insert(c.group);if(c.cache)++cacheCount;
        if(!c.resourceGroup.empty()){++resourceCount;++resourceCounts[c.task+c.resourceGroup];}
        if(!pattern.empty())++templateCounts[c.context+pattern];result.push_back(std::move(c));return true;
    };
    if(explicitMode){for(auto c:diversify(rows,rows.size(),seed))add(std::move(c),false);return result;}
    // Reserve exploration first so it cannot be eaten by a busy evidence family.
    const size_t exploration=count>=10?count/10:(count>=5?1:0);
    std::vector<Candidate> low;for(const auto& c:rows)if((c.exploration || c.score<65) && c.eligible)low.push_back(c);
    size_t added=0;for(auto c:diversify(low,low.size(),seed,true)){if(added>=exploration)break;if(add(std::move(c),true))++added;}
    const std::array<std::pair<const char*,int>,5> quotas={{{"business",20},{"activity",30},{"program",20},{"browser",15},{"media",5}}};
    for(auto [family,weight]:quotas){
        std::vector<Candidate> bucket;for(const auto& c:rows)if(c.family==family && c.eligible)bucket.push_back(c);
        const auto slots=count*weight/100;size_t filled=0;
        for(auto c:diversify(bucket,bucket.size(),seed)){if(filled>=slots)break;if(add(std::move(c),false))++filled;}
    }
    // Only spare eligible capacity flows back. Never pad with a failed/empty source.
    for(auto c:diversify(rows,rows.size(),seed))add(std::move(c),false);
    return result;
}

inline json build(const std::vector<Input>& inputs,const Budget& budget,const Probe& probe={},const SemanticProbe& semantic={}){
    if(inputs.empty() || budget.candidates==0 || budget.files==0 || budget.probePerFile>65536)throw std::runtime_error("SELECTION_BUDGET_INVALID");
    const auto start=std::chrono::steady_clock::now();
    struct Weak {bool operator()(const Candidate&a,const Candidate&b)const{return better(a,b);}};
    std::map<std::string,std::priority_queue<Candidate,std::vector<Candidate>,Weak>> heaps;
    std::vector<Candidate> exploration;
    size_t total=0,empty=0,excluded=0;json revisions=json::array();
    std::set<std::string> allowed(budget.fileReferences.begin(),budget.fileReferences.end());std::map<std::string,int> pathMatches;
    std::set<std::string> matchedReferences;
    // Retain at most C per family and an independent low-priority reservoir.
    auto retain=[&](const std::string& name,Candidate c){auto& heap=heaps[name];if(heap.size()<budget.candidates)heap.push(std::move(c));else if(better(c,heap.top())){heap.pop();heap.push(std::move(c));}};
    for(const auto& input:inputs){
        sqlite3* raw=nullptr;if(sqlite3_open_v2(input.database.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);throw std::runtime_error("SELECTION_SOURCE_UNAVAILABLE");}
        std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);
        std::set<std::string> columns;{sources::Statement s(raw,"PRAGMA table_info(files)");while(sqlite3_step(s.value)==SQLITE_ROW)columns.insert(reinterpret_cast<const char*>(sqlite3_column_text(s.value,1)));}
        auto col=[&](const std::string& name,const std::string& fallback){return columns.count(name)?name:fallback+" AS "+name;};
        std::string revision="legacy";if(sources::table(raw,"source_index_meta")){sources::Statement r(raw,"SELECT value FROM source_index_meta WHERE key='revision'");if(sqlite3_step(r.value)==SQLITE_ROW)revision=reinterpret_cast<const char*>(sqlite3_column_text(r.value,0));}
        revisions.push_back({{"task_id",input.task},{"revision",revision}});
        const auto query="SELECT path,"+col("name","''")+","+col("source_id","''")+","+col("category","''")+","+col("size","0")+","+col("mtime","0")+","+col("partition_num","0")+","+col("inode","0")+","+col("is_deleted","0")+" FROM files"+(columns.count("type")?" WHERE type='REG'":"");
        sources::Statement s(raw,query);int rc;
        while((rc=sqlite3_step(s.value))==SQLITE_ROW){
            ++total;auto r=sources::row(s.value);Candidate c;c.task=input.task;c.path=r["path"].is_string()?r["path"].get<std::string>():"";if(c.path.empty()){++excluded;continue;}
            c.name=r["name"].is_string()?r["name"].get<std::string>():"";if(c.name.empty())c.name=c.path.substr(c.path.find_last_of('/')+1);
            c.id=r["source_id"].is_string()?r["source_id"].get<std::string>():"";c.category=r["category"].is_string()?r["category"].get<std::string>():"";
            if(!allowed.empty() && !allowed.count(c.reference()) && !allowed.count(c.path)){++excluded;continue;}
            if(allowed.count(c.path)){++pathMatches[c.path];matchedReferences.insert(c.path);}if(allowed.count(c.reference()))matchedReferences.insert(c.reference());
            if(!budget.fileTypes.empty()){bool match=false;for(auto type:budget.fileTypes){type=lower(type);match=match || lower(c.category)==type;if(!type.empty() && type[0]!='.')type="."+type;match=match||ends(lower(c.name),type);}if(!match){++excluded;continue;}}
            auto number=[&](const char* field){return r[field].is_number_integer()?r[field].get<int64_t>():0;};
            c.size=number("size");c.mtime=number("mtime");c.partition=number("partition_num");c.inode=number("inode");c.deleted=number("is_deleted");
            if(c.size<=0){++empty;continue;}
            if(budget.skipExecutables && c.category=="Executables" && systemExecutable(c.path)){++excluded;continue;}
            classify(c);retain(c.family,c);
            auto sample=c;sample.score=0;sample.key=sources::hash(budget.seed+c.key)+":"+c.key;retain("_exploration",std::move(sample));
        }
        if(rc!=SQLITE_DONE)throw std::runtime_error("SELECTION_SCAN_INCOMPLETE");
    }
    for(auto& [_,count]:pathMatches)if(count>1)throw std::runtime_error("SOURCE_PATH_AMBIGUOUS");
    if(matchedReferences.size()!=allowed.size())throw std::runtime_error("SOURCE_NOT_FOUND");
    std::map<std::string,Candidate> unique;
    for(auto& [family,heap]:heaps)while(!heap.empty()){auto c=heap.top();heap.pop();if(family=="_exploration")classify(c);unique.emplace(c.key,std::move(c));}
    std::vector<Candidate> retained;for(auto& [_,c]:unique)retained.push_back(std::move(c));
    const bool explicitMode=!budget.fileReferences.empty();
    auto pool=allocate(retained,budget.candidates,budget.seed,explicitMode);
    size_t probed=0,bytes=0;bool timedOut=false;
    std::map<std::string,size_t> locations;for(size_t i=0;i<pool.size();++i)locations[pool[i].key]=i;
    const auto probeOrder=allocate(pool,std::min(budget.probeFiles,pool.size()),budget.seed,explicitMode);
    for(const auto& entry:probeOrder){
        auto& c=pool.at(locations.at(entry.key));
        if(std::chrono::steady_clock::now()-start>std::chrono::seconds(budget.seconds)){timedOut=true;break;}
        if(!probe || probed>=budget.probeFiles || bytes>=budget.probeBytes){c.reason="暂缓：本轮内容探测额度不足";continue;}
        const auto allowance=std::min<size_t>({budget.probePerFile,budget.probeBytes-bytes,static_cast<size_t>(c.size)});
        ++probed;bytes+=allowance; // Reserve the worst case before the reader runs.
        try {auto value=probe(c,allowance);if(value.value("bytes",size_t(0))>allowance)throw std::runtime_error("PROBE_BUDGET_EXCEEDED");applyProbe(c,value);
            if(budget.skipExecutables && c.format=="executable" && systemExecutable(c.path)){c.eligible=false;c.reason="本轮跳过系统目录程序内容分析";}}
        catch(const std::exception&){c.state="probe_error";c.eligible=false;c.reason="内容探测失败，状态未知";}
    }
    json semanticStats=json::object();
    if(semantic && !timedOut){
        std::vector<Candidate> requested,needsSemantic;size_t reserved=0;
        for(const auto& c:pool)if(c.eligible && (c.state=="signature_confirmed" || c.state=="unprobed"))needsSemantic.push_back(c);
        for(const auto& c:allocate(needsSemantic,budget.semanticFiles,budget.seed,explicitMode))if(requested.size()<budget.semanticFiles && c.size<=static_cast<int64_t>(budget.semanticBytes-reserved)){
            requested.push_back(c);reserved+=c.size;
        }
        if(!requested.empty())try{auto remainingBudget=budget;
            remainingBudget.seconds=std::max(1,budget.seconds-static_cast<int>(std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now()-start).count()));
            const auto answer=semantic(requested,remainingBudget);semanticStats=answer.value("stats",json::object());
            const auto values=answer.value("results",json::object());for(auto& c:pool)if(values.contains(c.task+":"+c.id))applyProbe(c,values[c.task+":"+c.id]);
        }catch(...){semanticStats={{"state","unavailable"},{"message","语义探测不可用，保留签名及未探测状态"}};}
    }
    for(auto& c:pool)if(c.state=="unprobed" || (c.state=="signature_confirmed" && c.format=="unknown")){
        c.eligible=false;if(c.reason.empty())c.reason="暂缓：没有足够的内容探测信息，来源继续保留";
    }
    for(auto& c:pool){
        if(budget.skipExecutables && c.format=="executable" && systemExecutable(c.path)){c.eligible=false;c.reason="本轮跳过系统目录程序内容分析";}
        if(!budget.visionAvailable && c.format=="image"){c.eligible=false;c.reason="暂缓：尚未配置视觉模型令牌上界";}
        if(c.size>256LL*1024*1024){c.eligible=false;c.reason="暂缓：超出当前完整来源读取预算，需要分段读取能力";}
    }
    auto selected=allocate(pool,std::min(budget.files,budget.candidates),budget.seed,explicitMode);
    json plan={{"schema_version",1},{"policy_version",policyVersion},{"budget",budget.asJson()},{"sources",revisions},
        {"selected",json::array()},{"candidates",json::array()},{"counts",{{"indexed",total},{"zero_bytes",empty},{"scope_excluded",excluded},
        {"candidates",pool.size()},{"selected",selected.size()},{"probed",probed},{"probe_reserved_bytes",bytes}}},
        {"semantic_probe",semanticStats},{"probe_timed_out",timedOut},{"physical_io_accounting","由后端管理；此额度计逻辑读取字节，不冒充物理磁盘字节"}};
    std::set<std::string> chosen;std::set<std::string> represented;
    for(auto& c:selected){chosen.insert(c.key);if(!c.group.empty())represented.insert(c.group);plan["selected"].push_back(c.asJson());}
    for(auto& c:pool){auto value=c.asJson();value["selected"]=chosen.count(c.key)!=0;
        if(!chosen.count(c.key) && !c.group.empty() && represented.count(c.group))value["reason"]="未单独分析：同内容同上下文代表已入选，来源仍保留";
        else if(!chosen.count(c.key) && !c.resourceGroup.empty() && c.eligible)value["reason"]="软件资源按包限额抽样，未将不同语言或模板视为相同证据；原来源仍保留";
        else if(!chosen.count(c.key) && c.eligible)value["reason"]="本轮数量或类别额度已满，材料仍保留；不能据此认定无关";
        plan["candidates"].push_back(std::move(value));}
    return plan;
}

inline std::string planInputKey(const std::vector<Input>& inputs,const Budget& budget){
    json value={{"policy",policyVersion},{"budget",budget.asJson()},{"inputs",json::array()}};
    for(const auto& input:inputs){sqlite3* raw=nullptr;if(sqlite3_open_v2(input.database.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);throw std::runtime_error("SELECTION_SOURCE_UNAVAILABLE");}
        std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);std::string revision=sources::stamp(input.database);
        if(sources::table(raw,"source_index_meta")){sources::Statement r(raw,"SELECT value FROM source_index_meta WHERE key='revision'");if(sqlite3_step(r.value)==SQLITE_ROW)revision=reinterpret_cast<const char*>(sqlite3_column_text(r.value,0));}
        // Hash the actual allowed inventory, not database timestamps/counts.
        // Analysis/cache writes do not change this fingerprint; equal-size
        // filtered inventories with different sources cannot reuse a plan.
        std::string query="SELECT path,size";
        for(const std::string name:{"source_id","category","type","mtime","ctime","is_deleted","partition_num","inode"})
            query+=sources::column(raw,name)?","+name:",NULL AS "+name;
        query+=" FROM files ORDER BY path,source_id,size,category,type,mtime,ctime,is_deleted,partition_num,inode";
        sources::Statement rows(raw,query);
        auto hash=std::unique_ptr<EVP_MD_CTX,decltype(&EVP_MD_CTX_free)>(EVP_MD_CTX_new(),EVP_MD_CTX_free);
        if(!hash || EVP_DigestInit_ex(hash.get(),EVP_sha256(),nullptr)!=1)throw std::runtime_error("SELECTION_HASH_FAILED");
        int rc;size_t count=0;while((rc=sqlite3_step(rows.value))==SQLITE_ROW){const auto text=sources::row(rows.value).dump();EVP_DigestUpdate(hash.get(),text.data(),text.size());++count;}
        if(rc!=SQLITE_DONE)throw std::runtime_error("SELECTION_SCAN_INCOMPLETE");unsigned char bytes[EVP_MAX_MD_SIZE];unsigned length=0;EVP_DigestFinal_ex(hash.get(),bytes,&length);
        const auto inventory=sources::hash(std::string(reinterpret_cast<char*>(bytes),length));
        value["inputs"].push_back({{"task",input.task},{"revision",revision},{"rows",count},{"inventory",inventory}});
    }return sources::hash(value.dump());
}
inline void schema(sqlite3* db){sources::sql(db,
    "CREATE TABLE IF NOT EXISTS selection_runs(plan_id TEXT PRIMARY KEY,plan_json TEXT NOT NULL,created_at INTEGER NOT NULL);"
    "CREATE TABLE IF NOT EXISTS selection_execution(plan_id TEXT NOT NULL,source_key TEXT NOT NULL,state TEXT NOT NULL,updated_at INTEGER NOT NULL,error TEXT NOT NULL DEFAULT '',PRIMARY KEY(plan_id,source_key));"
    "CREATE TABLE IF NOT EXISTS selection_budget(plan_id TEXT PRIMARY KEY,max_calls INTEGER NOT NULL,max_tokens INTEGER NOT NULL,used_calls INTEGER NOT NULL DEFAULT 0,reserved_tokens INTEGER NOT NULL DEFAULT 0);"
    "CREATE TABLE IF NOT EXISTS selection_call_ledger(id INTEGER PRIMARY KEY,plan_id TEXT NOT NULL,source_key TEXT NOT NULL,input_bound INTEGER NOT NULL,output_limit INTEGER NOT NULL,created_at INTEGER NOT NULL);"
    "CREATE TABLE IF NOT EXISTS selection_probe_budget(plan_id TEXT,kind TEXT,used_files INTEGER NOT NULL DEFAULT 0,used_bytes INTEGER NOT NULL DEFAULT 0,started_at INTEGER NOT NULL,PRIMARY KEY(plan_id,kind));"
    "CREATE TABLE IF NOT EXISTS selection_probe_cache(plan_id TEXT,source_key TEXT,value_json TEXT NOT NULL,PRIMARY KEY(plan_id,source_key));");}
inline json probeCache(const std::string& database,const std::string& plan,const std::string& key,const json& value=nullptr){
    sqlite3* raw=nullptr;if(sqlite3_open(database.c_str(),&raw)!=SQLITE_OK){if(raw)sqlite3_close(raw);throw std::runtime_error("PROBE_STORE_UNAVAILABLE");}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);sqlite3_busy_timeout(raw,10000);schema(raw);
    if(!value.is_null()){sources::Statement s(raw,"INSERT OR IGNORE INTO selection_probe_cache VALUES(?,?,?)");s.bind(1,plan);s.bind(2,key);s.bind(3,value.dump());if(sqlite3_step(s.value)!=SQLITE_DONE)throw std::runtime_error("PROBE_STORE_UNAVAILABLE");}
    sources::Statement s(raw,"SELECT value_json FROM selection_probe_cache WHERE plan_id=? AND source_key=?");s.bind(1,plan);s.bind(2,key);
    return sqlite3_step(s.value)==SQLITE_ROW?json::parse(reinterpret_cast<const char*>(sqlite3_column_text(s.value,0))):json(nullptr);
}
inline bool reserveProbe(const std::string& database,const std::string& plan,const std::string& kind,size_t files,size_t bytes,size_t maxFiles,size_t maxBytes,int seconds){
    sqlite3* raw=nullptr;if(sqlite3_open(database.c_str(),&raw)!=SQLITE_OK){if(raw)sqlite3_close(raw);return false;}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);sqlite3_busy_timeout(raw,10000);schema(raw);
    try{sources::sql(raw,"BEGIN IMMEDIATE");sources::Statement seed(raw,"INSERT OR IGNORE INTO selection_probe_budget(plan_id,kind,started_at) VALUES(?,?,strftime('%s','now'))");seed.bind(1,plan);seed.bind(2,kind);if(sqlite3_step(seed.value)!=SQLITE_DONE)throw std::runtime_error("PROBE_BUDGET_UNAVAILABLE");
        sources::Statement s(raw,"UPDATE selection_probe_budget SET used_files=used_files+?,used_bytes=used_bytes+? WHERE plan_id=? AND kind=? AND used_files+?<=? AND used_bytes+?<=? AND strftime('%s','now')-started_at<=?");
        sqlite3_bind_int64(s.value,1,files);sqlite3_bind_int64(s.value,2,bytes);s.bind(3,plan);s.bind(4,kind);sqlite3_bind_int64(s.value,5,files);sqlite3_bind_int64(s.value,6,maxFiles);sqlite3_bind_int64(s.value,7,bytes);sqlite3_bind_int64(s.value,8,maxBytes);sqlite3_bind_int(s.value,9,seconds);
        const bool okay=sqlite3_step(s.value)==SQLITE_DONE && sqlite3_changes(raw)==1;sources::sql(raw,"COMMIT");return okay;
    }catch(...){sqlite3_exec(raw,"ROLLBACK",nullptr,nullptr,nullptr);return false;}
}
inline json cached(const std::string& database,const std::string& key){sqlite3* raw=nullptr;if(sqlite3_open_v2(database.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);return nullptr;}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);if(!sources::table(raw,"selection_runs"))return nullptr;
    sources::Statement s(raw,"SELECT plan_json FROM selection_runs WHERE plan_id=?");s.bind(1,key);if(sqlite3_step(s.value)!=SQLITE_ROW)return nullptr;
    auto result=json::parse(reinterpret_cast<const char*>(sqlite3_column_text(s.value,0)));const auto digest=result.value("plan_digest",std::string());
    auto verified=result;verified.erase("plan_digest");
    if(digest.empty() || sources::hash(verified.dump())!=digest)throw std::runtime_error("SELECTION_PLAN_INTEGRITY_FAILED");
    return result;}
inline void save(const std::string& database,const std::string& key,json& plan,int64_t calls,int64_t tokens){
    sqlite3* raw=nullptr;if(sqlite3_open(database.c_str(),&raw)!=SQLITE_OK){if(raw)sqlite3_close(raw);throw std::runtime_error("SELECTION_PLAN_WRITE_FAILED");}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);sqlite3_busy_timeout(raw,10000);schema(raw);sources::sql(raw,"BEGIN IMMEDIATE");
    try{plan["plan_id"]=key;plan["model_budget"]={{"max_calls",calls},{"max_tokens",tokens}};plan.erase("plan_digest");plan["plan_digest"]=sources::hash(plan.dump());
        sources::Statement s(raw,"INSERT OR IGNORE INTO selection_runs VALUES(?,?,strftime('%s','now'))");s.bind(1,key);s.bind(2,plan.dump());if(sqlite3_step(s.value)!=SQLITE_DONE)throw std::runtime_error("SELECTION_PLAN_WRITE_FAILED");
        sources::Statement b(raw,"INSERT OR IGNORE INTO selection_budget(plan_id,max_calls,max_tokens) VALUES(?,?,?)");b.bind(1,key);sqlite3_bind_int64(b.value,2,calls);sqlite3_bind_int64(b.value,3,tokens);if(sqlite3_step(b.value)!=SQLITE_DONE)throw std::runtime_error("SELECTION_PLAN_WRITE_FAILED");sources::sql(raw,"COMMIT");
    }catch(...){sqlite3_exec(raw,"ROLLBACK",nullptr,nullptr,nullptr);throw;}
}
inline bool finished(const std::string& database,const std::string& plan,const std::string& reference){sqlite3* raw=nullptr;if(sqlite3_open_v2(database.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)!=SQLITE_OK){if(raw)sqlite3_close(raw);return false;}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);sqlite3_busy_timeout(raw,10000);if(!sources::table(raw,"selection_execution"))return false;
    sources::Statement s(raw,"SELECT 1 FROM selection_execution WHERE plan_id=? AND source_key=? AND state='completed'");s.bind(1,plan);s.bind(2,reference);return sqlite3_step(s.value)==SQLITE_ROW;}
inline void finish(const std::string& database,const std::string& plan,const std::string& reference,const std::string& state,const std::string& error=""){
    sqlite3* raw=nullptr;if(sqlite3_open(database.c_str(),&raw)!=SQLITE_OK){if(raw)sqlite3_close(raw);return;}
    std::unique_ptr<sqlite3,decltype(&sqlite3_close)> db(raw,sqlite3_close);sqlite3_busy_timeout(raw,10000);schema(raw);
    sources::Statement s(raw,"INSERT INTO selection_execution VALUES(?,?,?,strftime('%s','now'),?) ON CONFLICT(plan_id,source_key) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at,error=excluded.error");
    s.bind(1,plan);s.bind(2,reference);s.bind(3,state);s.bind(4,error);if(sqlite3_step(s.value)!=SQLITE_DONE)throw std::runtime_error("SELECTION_PROGRESS_WRITE_FAILED");}
}
