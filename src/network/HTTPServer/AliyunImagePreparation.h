#pragma once
#include <functional>
#include <nlohmann/json.hpp>
#include <string>

struct AliyunImageResult {
    bool okay = false;
    std::string code = "ALIYUN_PREPARATION_FAILED";
    nlohmann::json manifest;
};

AliyunImageResult prepareAliyunImage(const std::string& source, const std::string& work,
    const std::string& sha256, const std::function<void(uint64_t, uint64_t)>& progress,
    const std::function<bool()>& cancelled);
