#pragma once
#include <nlohmann/json.hpp>
#include <openssl/sha.h>
#include <string>

namespace forensics::source_names {
inline constexpr const char* policy="lossless-component-bytes:v1";
inline constexpr const char* prefix="__source_bytes_";
inline std::string hex(const std::string& bytes) {
    const char* digits="0123456789abcdef";std::string result;result.reserve(bytes.size()*2);
    for(unsigned char value:bytes){result+=digits[value>>4];result+=digits[value&15];}return result;
}
inline bool safe(const std::string& value) {
    if(value.rfind(prefix,0)==0)return false;
    for(unsigned char c:value)if(c<32 || c==127 || c=='\\')return false;
    try{nlohmann::json(value).dump();return true;}catch(const nlohmann::json::type_error&){return false;}
}
inline std::string component(const std::string& bytes) {
    if(safe(bytes))return bytes;
    // Escape the reserved prefix too, so a real literal filename cannot be
    // confused with an escaped filename. Complete bytes live in the locator.
    if(bytes.size()<=96)return std::string(prefix)+"x"+hex(bytes)+"__";
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char*>(bytes.data()),bytes.size(),digest);
    return std::string(prefix)+"h"+hex(std::string(reinterpret_cast<char*>(digest),sizeof(digest)))+"__";
}
inline std::string path(const std::string& bytes) {
    std::string result;size_t start=0;
    for(;;){const auto end=bytes.find('/',start);result+=component(bytes.substr(start,end==std::string::npos?end:end-start));
        if(end==std::string::npos)break;result+='/';start=end+1;}
    return result;
}
}
