#pragma once

#include <functional>
#include <nlohmann/json.hpp>
#include <string>

struct AndroidContainerNormalizationResult {
    bool okay = false;
    std::string code;
    nlohmann::json manifest;
};

AndroidContainerNormalizationResult normalizeAndroidContainer(
    const std::string& source, const std::string& taskDirectory,
    const std::string& expectedSourceHash, const std::string& expectedPlanHash,
    int selectedSlot, const std::function<void()>& heartbeat,
    const std::function<bool()>& cancelled);
