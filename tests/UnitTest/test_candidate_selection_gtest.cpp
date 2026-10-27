#include <gtest/gtest.h>
#include "core/Selection/CandidateSelection.h"
#include "core/Selection/ModelBudget.h"
#include <filesystem>
#include <thread>
#include <atomic>

namespace sel=forensics::selection;
namespace src=forensics::sources;
struct SelectionFixture:testing::Test {
    std::filesystem::path root;std::string path;sqlite3* db=nullptr;
    void SetUp() override {
        root=std::filesystem::temp_directory_path()/("selection-"+std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));std::filesystem::create_directories(root);path=(root/"files.db").string();
        ASSERT_EQ(sqlite3_open(path.c_str(),&db),SQLITE_OK);
        src::sql(db,"CREATE TABLE files(path TEXT,name TEXT,size INTEGER,source_id TEXT,category TEXT,type TEXT,inode INTEGER,partition_num INTEGER,is_deleted INTEGER,mtime INTEGER)");
    }
    void TearDown() override {sqlite3_close(db);std::filesystem::remove_all(root);}
    void add(const std::string& file,int size=20){src::Statement s(db,"INSERT INTO files VALUES(?,?,?,?,?,'REG',1,1,0,100)");s.bind(1,file);s.bind(2,std::filesystem::path(file).filename().string());sqlite3_bind_int(s.value,3,size);s.bind(4,src::hash(file));s.bind(5,"Unknown Files");ASSERT_EQ(sqlite3_step(s.value),SQLITE_DONE);}
    sel::json build(size_t count=100,sel::Probe probe={}){sel::Budget b;b.files=count;b.candidates=500;b.probeFiles=500;
        if(!probe)probe=[](const auto& c,size_t limit){return sel::inspectBytes(c.path.substr(0,limit),false);};
        return sel::build({{path,"task"}},b,probe);}
};
TEST_F(SelectionFixture, RowOrderDoesNotChangeSelection) {
    add("/Users/u/Documents/A.txt");add("/Users/u/Documents/B.txt");add("/Users/u/Documents/C.txt");auto first=build(2);
    src::sql(db,"CREATE TABLE reversed AS SELECT * FROM files ORDER BY path DESC;DELETE FROM files;INSERT INTO files SELECT * FROM reversed");
    auto second=build(2);EXPECT_EQ(first["selected"],second["selected"]);
}
TEST_F(SelectionFixture, CoreUserAndBrowserSourcesSurviveCacheFlood) {
    for(int i=0;i<2000;++i)add("/Users/u/Code Cache/js/"+std::to_string(i));
    add("/Users/u/Desktop/notice.txt");add("/Users/u/Chrome/Default/History");add("/Users/u/Edge/Default/History");
    auto result=build();std::set<std::string> paths;for(auto& r:result["selected"])paths.insert(r["path"]);
    EXPECT_TRUE(paths.count("/Users/u/Desktop/notice.txt"));EXPECT_TRUE(paths.count("/Users/u/Chrome/Default/History"));EXPECT_TRUE(paths.count("/Users/u/Edge/Default/History"));
    EXPECT_LE(paths.size(),8u); // 3 factual candidates + at most five cache representatives.
}
TEST_F(SelectionFixture, MultipleUserDocumentsBeatGenericDirectoryHeads) {
    add("/Users/u/Desktop/notice.txt");add("/Users/u/Desktop/desktop.ini");
    add("/Users/u/Desktop/app/first.xml");add("/Users/u/Desktop/app/settings.xml");
    for(int i=0;i<1000;++i)add("/Users/u/AppData/vendor/"+std::to_string(i)+"/config.xml");
    auto result=build(100);std::set<std::string> paths;for(auto& value:result["selected"])paths.insert(value["path"]);
    EXPECT_TRUE(paths.count("/Users/u/Desktop/notice.txt"));EXPECT_TRUE(paths.count("/Users/u/Desktop/app/settings.xml"));
}

TEST_F(SelectionFixture, ServerConfigurationAndActivityBeatResourceFlood) {
    for(int i=0;i<400;++i)add("/www/wwwroot/site/vendor/pkg/"+std::to_string(i)+"/messages.json");
    for(int i=0;i<40;++i)add("/Users/u/AppData/Chrome/Extensions/app/1/_locales/"+std::to_string(i)+"/messages.json");
    for(auto p:{"/www/server/panel/vhost/nginx/site.conf","/www/wwwroot/site/application/database.php","/var/log/secure","/etc/centos-release","/root/.bash_history","/Users/u/Documents/license_contract.txt"})add(p);
    auto result=build(100);std::set<std::string> chosen;size_t resources=0,languages=0;
    for(auto& row:result["selected"]){chosen.insert(row["path"]);if(row["family"]=="resource")++resources;if(row["path"].get<std::string>().find("/_locales/")!=std::string::npos)++languages;}
    EXPECT_TRUE(chosen.count("/www/server/panel/vhost/nginx/site.conf"));
    EXPECT_TRUE(chosen.count("/www/wwwroot/site/application/database.php"));
    EXPECT_TRUE(chosen.count("/var/log/secure"));EXPECT_TRUE(chosen.count("/root/.bash_history"));
    EXPECT_TRUE(chosen.count("/Users/u/Documents/license_contract.txt"));
    EXPECT_LE(resources,5u);EXPECT_LE(languages,2u);
    EXPECT_GT(result["counts"]["indexed"].get<int>(),400); // Inventory is not deleted.
}

TEST_F(SelectionFixture, ControllersSurviveViewAndFrameworkFlood) {
    for(int i=0;i<400;++i)add("/www/wwwroot/site/application/index/view/"+std::to_string(i)+".html");
    for(int i=0;i<400;++i)add("/www/wwwroot/site/thinkphp/library/"+std::to_string(i)+".php");
    for(auto name:{"Pay.php","User.php","Order.php","Withdraw.php"})add(std::string("/www/wwwroot/site/application/index/controller/")+name);
    auto plan=build(100);std::set<std::string> paths;for(auto& row:plan["selected"])paths.insert(row["path"]);
    for(auto name:{"Pay.php","User.php","Order.php","Withdraw.php"})EXPECT_TRUE(paths.count(std::string("/www/wwwroot/site/application/index/controller/")+name));
}
TEST_F(SelectionFixture, FrontendPluginsAndInstallHeadersCannotConsumeBusinessQuotas) {
    for(int i=0;i<200;++i)add("/www/wwwroot/site/public/static/plugs/editor/lang/"+std::to_string(i)+".js");
    for(int i=0;i<100;++i)add("/var/log/anaconda/package-"+std::to_string(i)+".hdr");
    for(int i=0;i<100;++i)add("/usr/src/kernels/1/drivers/"+std::to_string(i)+"/Kconfig");
    for(auto path:{"/www/wwwroot/site/application/index/controller/Pay.php","/www/wwwroot/site/public/js/checkout.js","/var/log/anaconda/anaconda.log","/var/log/secure"})add(path);
    auto plan=build(100);std::set<std::string> paths;size_t resources=0;
    for(auto& row:plan["selected"]){paths.insert(row["path"]);resources+=row["family"]=="resource";}
    EXPECT_LE(resources,5u);
    for(auto path:{"/www/wwwroot/site/application/index/controller/Pay.php","/www/wwwroot/site/public/js/checkout.js","/var/log/anaconda/anaconda.log","/var/log/secure"})EXPECT_TRUE(paths.count(path));
    EXPECT_EQ(plan["counts"]["indexed"],404);
}
TEST_F(SelectionFixture, EmptyAndFailedContentDoNotConsumeAnalysisSlots) {
    add("/Users/u/Desktop/empty.txt",0);add("/Users/u/Desktop/a.txt");add("/Users/u/Desktop/b.txt");
    auto result=build(100,[](const auto& c,size_t){return sel::json{{"state",c.name=="a.txt"?"metadata_only":"error"}};});
    EXPECT_EQ(result["counts"]["zero_bytes"],1);EXPECT_TRUE(result["selected"].empty());
}
TEST_F(SelectionFixture, SameBytesGroupWithoutDeletingSourceRecords) {
    add("/Users/u/Desktop/a.txt");add("/Users/u/Desktop/b.txt");
    auto result=build(10,[](const auto&,size_t){return sel::inspectBytes("same exact content",true);});
    EXPECT_EQ(result["selected"].size(),1u);EXPECT_EQ(result["candidates"].size(),2u);
    EXPECT_NE(result["candidates"][0]["source_id"],result["candidates"][1]["source_id"]);
}
TEST_F(SelectionFixture, SameSQLitePrimaryIsNotEnoughForDeduplication) {
    add("/Users/u/Desktop/a.db");add("/Users/u/Desktop/b.db");
    auto result=build(10,[](const auto&,size_t){return sel::inspectBytes(std::string("SQLite format 3\0",16)+"data",true);});
    EXPECT_EQ(result["selected"].size(),2u);
}
TEST_F(SelectionFixture, MagicWordsDoNotMakeOrdinaryTextExecutable) {
    EXPECT_EQ(sel::inspectBytes("MZ is a quoted string in this note",true)["format"],"text");
    std::string pe(68,'\0');pe[0]='M';pe[1]='Z';pe[60]=64;pe[64]='P';pe[65]='E';
    EXPECT_EQ(sel::inspectBytes(pe,true)["format"],"executable");
}
TEST_F(SelectionFixture, EmptyEvtxNeedsVerifiedHeadersAndNeverMeansRecoveredRecordsAbsent) {
    std::string header(4096,'\0');header.replace(0,8,std::string("ElfFile\0",8));
    header[36]=2;header[38]=3;header[41]=16;
    auto crc=sel::crc32(header.substr(0,120));for(int i=0;i<4;++i)header[124+i]=static_cast<char>(crc>>(i*8));
    const auto empty=sel::inspectBytes(header,true);
    EXPECT_EQ(empty["state"],"metadata_only");EXPECT_EQ(empty["coverage"]["recovered_records_included"],false);
    header[124]^=1;EXPECT_NE(sel::inspectBytes(header,true)["state"],"metadata_only");
}
TEST_F(SelectionFixture, EmptyEvtxChunkRequiresKnownFlagsChecksumsAndNoVisibleRecords) {
    std::string data(4608,'\0');
    auto put=[&](size_t offset,uint32_t value){for(int i=0;i<4;++i)data[offset+i]=static_cast<char>(value>>(8*i));};
    auto checksums=[&]{put(124,sel::crc32(data.substr(0,120)));put(4096+124,sel::crc32(data.substr(4096,120)+data.substr(4096+128,384)));};
    data.replace(0,8,std::string("ElfFile\0",8));data[36]=2;data[38]=3;data[41]=16;data[42]=1;
    data.replace(4096,8,std::string("ElfChnk\0",8));put(4096+40,128);put(4096+48,512);put(4096+120,1);checksums();
    constexpr uint64_t size=4096+65536;
    EXPECT_TRUE(sel::verifiedEmptyEvtxHeaders(data,size));
    auto result=sel::inspectBytes(data,false,size);EXPECT_EQ(result["state"],"metadata_only");
    EXPECT_EQ(result["coverage"]["record_scope"],"standard_visible_headers");
    EXPECT_EQ(result["coverage"]["recovered_records_included"],false);
    EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data,size-1));
    EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data.substr(0,4607),size));
    data[124]^=1;EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data,size));checksums();
    data[4096+124]^=1;EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data,size));checksums();
    for(uint32_t flag:{0u,2u,3u,4u,0xffffffffu}){put(4096+120,flag);checksums();EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data,size));}
    put(4096+120,1);
    for(auto [offset,value]:std::vector<std::pair<size_t,uint32_t>>{{44,512},{48,1024},{52,1}}){
        auto previous=sel::little(data,4096+offset);put(4096+offset,value);checksums();
        EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data,size));put(4096+offset,previous);
    }
    data[42]=2;checksums();EXPECT_FALSE(sel::verifiedEmptyEvtxHeaders(data,size+65536));
}
TEST_F(SelectionFixture, ExplicitSourcesKeepDuplicateAndCacheOccurrencesWithinHardBudgets) {
    sel::Budget b;b.files=10;b.candidates=20;b.probeFiles=20;
    for(int i=0;i<10;++i){auto p="/Users/u/Cache/"+std::to_string(i)+".txt";add(p,std::string("identical complete body").size());b.fileReferences.push_back(p);}
    auto plan=sel::build({{path,"task"}},b,[](const auto&,size_t){return sel::inspectBytes("identical complete body",true);});
    ASSERT_EQ(plan["selected"].size(),10u);
    for(const auto& item:plan["selected"])EXPECT_EQ(item["lane"],"explicit");
    b.files=3;plan=sel::build({{path,"task"}},b,[](const auto&,size_t){return sel::inspectBytes("identical complete body",true);});
    EXPECT_EQ(plan["selected"].size(),3u);
}
TEST_F(SelectionFixture, ReadBudgetsAreReservedBeforeProbe) {
    for(int i=0;i<10;++i)add("/Users/u/Desktop/"+std::to_string(i)+".txt",100);
    sel::Budget b;b.files=10;b.candidates=10;b.probeFiles=3;b.probeBytes=15;b.probePerFile=10;size_t used=0,calls=0;
    auto p=sel::build({{path,"task"}},b,[&](const auto&,size_t limit){used+=limit;++calls;return sel::json{{"state","unprobed"},{"bytes",limit}};});
    EXPECT_EQ(used,15u);EXPECT_EQ(calls,2u);EXPECT_LE(p["selected"].size(),10u);
}
TEST_F(SelectionFixture, AtomicCallReservationsIncludeRetriesAndDoNotReset) {
    sel::Budget b;auto p=sel::json::object();sel::save(path,"plan",p,7,700);
    std::atomic<int> admitted{0};std::vector<std::thread> threads;
    for(int i=0;i<20;++i)threads.emplace_back([&]{if(sel::reserveModelCall(path,"plan","source",60,40))++admitted;});
    for(auto& t:threads)t.join();EXPECT_EQ(admitted,7);
    sel::save(path,"plan",p,100,10000);EXPECT_FALSE(sel::reserveModelCall(path,"plan","source",1,1));
    sel::finish(path,"plan","source","completed");EXPECT_TRUE(sel::finished(path,"plan","source"));
}
