#include "KeyFileLoader.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <cctype>

namespace fs = std::filesystem;

std::optional<std::string> KeyFileLoader::readTrimmed(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) return std::nullopt;
    std::stringstream ss;
    ss << in.rdbuf();
    std::string s = ss.str();
    // Trim trailing whitespace / CR / LF (leading whitespace is significant for
    // some passwords, so only trailing is removed).
    while (!s.empty()) {
        char c = s.back();
        if (c == '\n' || c == '\r' || c == ' ' || c == '\t') {
            s.pop_back();
        } else {
            break;
        }
    }
    if (s.empty()) return std::nullopt;
    return s;
}

std::string KeyFileLoader::resolveDir(const std::string& imagePath, const std::string& keyFileDir) {
    if (!keyFileDir.empty()) return keyFileDir;
    return fs::path(imagePath).parent_path().string();
}

std::string KeyFileLoader::baseNameNoExt(const std::string& imagePath) {
    // E01 images are split-segment files like "img.E01". fs::path::stem() would
    // strip only ".E01" leaving "img" — which is what we want.
    return fs::path(imagePath).stem().string();
}

std::optional<std::string> KeyFileLoader::loadForPartition(
    const std::string& imagePath, int partitionNum, const std::string& keyFileDir) {

    std::string dir = resolveDir(imagePath, keyFileDir);
    std::string base = baseNameNoExt(imagePath);

    // 1. <base>.part<P>.key
    {
        std::string p = dir + "/" + base + ".part" + std::to_string(partitionNum) + ".key";
        auto v = readTrimmed(p);
        if (v) return v;
    }
    // 2. <base>.part<P>.txt
    {
        std::string p = dir + "/" + base + ".part" + std::to_string(partitionNum) + ".txt";
        auto v = readTrimmed(p);
        if (v) return v;
    }
    // 3. whole-image fallback
    return loadForImage(imagePath, keyFileDir);
}

std::optional<std::string> KeyFileLoader::loadForImage(
    const std::string& imagePath, const std::string& keyFileDir) {

    std::string dir = resolveDir(imagePath, keyFileDir);
    std::string base = baseNameNoExt(imagePath);

    for (const char* ext : {".key", ".password", ".txt"}) {
        std::string p = dir + "/" + base + ext;
        auto v = readTrimmed(p);
        if (v) return v;
    }
    return std::nullopt;
}

std::optional<std::string> KeyFileLoader::loadFvekForPartition(
    const std::string& imagePath, int partitionNum, const std::string& keyFileDir) {
    // FVEK files are binary (32 bytes), so we return the PATH, not contents.
    std::string dir = resolveDir(imagePath, keyFileDir);
    std::string base = baseNameNoExt(imagePath);

    // 1. <base>.part<P>.fvek
    auto validFvek = [](const std::string& path) {
        std::error_code ec;
        return fs::is_regular_file(path, ec) && fs::file_size(path, ec) == 32;
    };

    std::string p = dir + "/" + base + ".part" + std::to_string(partitionNum) + ".fvek";
    if (validFvek(p)) return p;
    // 2. <base>.fvek (whole-image)
    p = dir + "/" + base + ".fvek";
    if (validFvek(p)) return p;
    return std::nullopt;
}
