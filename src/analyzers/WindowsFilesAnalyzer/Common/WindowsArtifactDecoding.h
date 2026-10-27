#pragma once
#include "WindowsDataTypes.h"
#include <cstdint>
#include <filesystem>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace forensics::windows_decoding {
inline std::string utf16le(const char* data, size_t size) {
    if (size % 2) throw std::invalid_argument("UTF16_ODD_BYTE_COUNT");
    std::string output;
    auto unit=[&](size_t i){return uint16_t(uint8_t(data[i])) | (uint16_t(uint8_t(data[i+1]))<<8);};
    for (size_t i=0;i<size;i+=2) {
        uint32_t code=unit(i);
        if (!code) break;
        if (code>=0xd800 && code<=0xdbff) {
            if (i+3>=size) throw std::invalid_argument("UTF16_TRUNCATED_SURROGATE");
            const auto low=unit(i+2);
            if (low<0xdc00 || low>0xdfff) throw std::invalid_argument("UTF16_INVALID_SURROGATE");
            code=0x10000+((code-0xd800)<<10)+(low-0xdc00);i+=2;
        } else if (code>=0xdc00 && code<=0xdfff) throw std::invalid_argument("UTF16_INVALID_SURROGATE");
        if(code<0x80) output+=char(code);
        else if(code<0x800){output+=char(0xc0|(code>>6));output+=char(0x80|(code&63));}
        else if(code<0x10000){output+=char(0xe0|(code>>12));output+=char(0x80|((code>>6)&63));output+=char(0x80|(code&63));}
        else {output+=char(0xf0|(code>>18));output+=char(0x80|((code>>12)&63));output+=char(0x80|((code>>6)&63));output+=char(0x80|(code&63));}
    }
    return output;
}

inline RecycleBinEntry recycle(const std::vector<char>& bytes,const std::string& source) {
    auto integer=[&](size_t offset,size_t count){
        if(offset>bytes.size() || count>bytes.size()-offset) throw std::invalid_argument("RECYCLE_TRUNCATED_HEADER");
        uint64_t value=0;for(size_t i=0;i<count;++i)value|=uint64_t(uint8_t(bytes[offset+i]))<<(8*i);return value;
    };
    const auto version=integer(0,8), size=integer(8,8), timestamp=integer(16,8);
    if(size>uint64_t(std::numeric_limits<int64_t>::max())) throw std::invalid_argument("RECYCLE_SIZE_OUT_OF_RANGE");
    const size_t offset=version==1?24:28;
    size_t pathBytes=0;
    if(version==1) pathBytes=520;
    else if(version==2) {
        const auto units=integer(24,4);
        if(!units || units>32768) throw std::invalid_argument("RECYCLE_PATH_LENGTH_INVALID");
        pathBytes=size_t(units)*2; // v2 stores UTF-16 code units, including NUL.
    } else throw std::invalid_argument("RECYCLE_VERSION_UNSUPPORTED");
    if(offset>bytes.size() || pathBytes>bytes.size()-offset) throw std::invalid_argument("RECYCLE_PATH_TRUNCATED");
    bool terminated=false;
    for(size_t i=0;i<pathBytes;i+=2)if(bytes[offset+i]==0 && bytes[offset+i+1]==0){terminated=true;break;}
    if(!terminated) throw std::invalid_argument("RECYCLE_PATH_UNTERMINATED");
    RecycleBinEntry result{};result.recycleFilePath=source;result.originalSize=int64_t(size);
    result.originalPath=utf16le(bytes.data()+offset,pathBytes);
    if(result.originalPath.empty()) throw std::invalid_argument("RECYCLE_PATH_EMPTY");
    // Zero means unknown in the native contract; the database stores NULL.
    if(timestamp) {
        const int64_t seconds=int64_t(timestamp/10000000)-11644473600LL;
        if(seconds<0 || seconds>253402300799LL) throw std::invalid_argument("RECYCLE_TIME_OUT_OF_RANGE");
        result.deletionTime=seconds;
    }
    const auto path=std::filesystem::path(source);
    const auto parent=path.parent_path().filename().string();
    if(parent.rfind("S-1-",0)==0) result.userSid=parent;
    const auto name=path.filename().string();
    if(name.rfind("$I",0)==0)result.fileName="$R"+name.substr(2);
    return result;
}
}
