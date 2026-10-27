#include "WindowsPrefetchParser.h"
#include <fstream>
#include <sstream>
#include <iomanip>
#include <cstring>
#ifdef HAVE_LIBSCCA
#include <libscca.h>
#endif

std::string PrefetchParser::libraryVersion() {
#ifdef HAVE_LIBSCCA
    return libscca_get_version();
#else
    return "unavailable";
#endif
}

bool PrefetchParser::parse() {
    valid_=false; status_="error"; lastError_.clear();
    version_=PrefetchVersion::UNKNOWN; runCount_=0;
    lastRunTime_.reset();
    executableName_.clear(); prefetchHash_.clear();
    allRunTimes_.clear(); rawRunTimes_.clear(); referencedFiles_.clear();
    char head[8]{};
    std::ifstream input(filepath_, std::ios::binary);
    if (!input.read(head, sizeof(head))) { lastError_="PREFETCH_TRUNCATED_OR_UNREADABLE"; return false; }
    const bool mam=std::memcmp(head,"MAM",3)==0 &&
        (static_cast<unsigned char>(head[3])==0x04 || static_cast<unsigned char>(head[3])==0x84);
    if (!mam && PrefetchHelpers::detectVersion(head)==PrefetchVersion::UNKNOWN) {
        lastError_="PREFETCH_INVALID_SIGNATURE_OR_VERSION"; return false;
    }
    if (mam) {
        const auto size=PrefetchHelpers::readUInt32LE(head+4);
        if (size<84 || size>64*1024*1024) { lastError_="PREFETCH_INVALID_DECOMPRESSED_SIZE"; return false; }
    }
#ifndef HAVE_LIBSCCA
    status_="unsupported"; lastError_="PREFETCH_PARSER_UNAVAILABLE"; return false;
#else
    parserVersion_=libscca_get_version();
    struct File {
        libscca_file_t* value=nullptr;
        ~File() { if (value) { libscca_file_close(value,nullptr); libscca_file_free(&value,nullptr); } }
    } file;
    if (libscca_file_initialize(&file.value,nullptr)!=1 ||
        libscca_file_open(file.value,filepath_.c_str(),LIBSCCA_OPEN_READ,nullptr)!=1) {
        lastError_="PREFETCH_PARSE_FAILED"; return false;
    }
    uint32_t format=0, hash=0;
    size_t nameSize=0;
    if (libscca_file_get_format_version(file.value,&format,nullptr)!=1 ||
        libscca_file_get_run_count(file.value,&runCount_,nullptr)!=1 ||
        libscca_file_get_prefetch_hash(file.value,&hash,nullptr)!=1 ||
        libscca_file_get_utf8_executable_filename_size(file.value,&nameSize,nullptr)!=1 ||
        nameSize==0 || nameSize>65536) {
        lastError_="PREFETCH_REQUIRED_FIELDS_UNAVAILABLE"; return false;
    }
    if (format!=17 && format!=23 && format!=26 && format!=30 && format!=31) {
        status_="unsupported"; lastError_="PREFETCH_VERSION_UNSUPPORTED"; return false;
    }
    version_=static_cast<PrefetchVersion>(format);
    std::vector<uint8_t> name(nameSize);
    if (libscca_file_get_utf8_executable_filename(file.value,name.data(),name.size(),nullptr)!=1) {
        lastError_="PREFETCH_NAME_UNAVAILABLE"; return false;
    }
    executableName_=reinterpret_cast<const char*>(name.data());
    std::ostringstream hashText; hashText << std::hex << std::setw(8) << std::setfill('0') << hash;
    prefetchHash_=hashText.str(); status_="ok";
    for (int i=0;i<((format==17 || format==23)?1:8);++i) {
        uint64_t raw=0;
        const auto rc=libscca_file_get_last_run_time(file.value,i,&raw,nullptr);
        if (rc<0) { status_="partial"; lastError_="PREFETCH_TIME_UNAVAILABLE"; continue; }
        if (!raw) continue;
        rawRunTimes_.push_back(raw);
        if (raw>2650467743999999999ULL) { status_="partial"; lastError_="PREFETCH_INVALID_TIME"; continue; }
        if (i==0) lastRunTime_=PrefetchHelpers::filetimeToUnixTime(raw);
        allRunTimes_.push_back(PrefetchHelpers::filetimeToUnixTime(raw));
    }
    if (runCount_>0 && !lastRunTime_) {
        status_="partial";
        if (lastError_.empty()) lastError_="PREFETCH_LATEST_TIME_UNAVAILABLE";
    }
    int count=0;
    if (libscca_file_get_number_of_filenames(file.value,&count,nullptr)!=1) {
        status_="partial"; lastError_="PREFETCH_REFERENCES_UNAVAILABLE";
    }
    for (int i=0;i<count && i<10000;++i) {
        size_t size=0;
        if (libscca_file_get_utf8_filename_size(file.value,i,&size,nullptr)!=1 || size==0 || size>65536) {
            status_="partial"; lastError_="PREFETCH_REFERENCE_UNAVAILABLE"; continue;
        }
        std::vector<uint8_t> text(size);
        if (libscca_file_get_utf8_filename(file.value,i,text.data(),size,nullptr)!=1) {
            status_="partial"; lastError_="PREFETCH_REFERENCE_UNAVAILABLE"; continue;
        }
        referencedFiles_.emplace_back(reinterpret_cast<const char*>(text.data()));
    }
    if (count>10000) { status_="partial"; lastError_="PREFETCH_REFERENCES_TRUNCATED"; }
    valid_=true;
    return true;
#endif
}
