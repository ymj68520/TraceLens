#include "TarIndex.h"
#include <fstream>
#include <vector>
#include <algorithm>
#include <filesystem>
#include <cstdlib>
#include <unistd.h>
#include <cstring>
#include <limits>
#ifdef USE_ZLIB
#include <zlib.h>
#endif

namespace fs = std::filesystem;

namespace {

constexpr size_t kTarBlockBytes = 512;

bool createTemporaryFile(const fs::path& directory, std::string& path, std::ofstream& output) {
    if (directory.empty()) return false;

    std::string pattern = (directory / "tracelens-miui-XXXXXX").string();
    std::vector<char> writablePattern(pattern.begin(), pattern.end());
    writablePattern.push_back('\0');
    const int descriptor = mkstemp(writablePattern.data());
    if (descriptor == -1) return false;
    close(descriptor);

    path.assign(writablePattern.data());
    output.open(path, std::ios::binary | std::ios::trunc);
    if (!output) {
        std::remove(path.c_str());
        path.clear();
        return false;
    }
    return true;
}

bool parseOctal(const char* field, size_t width, uint64_t& value) {
    value = 0;
    size_t begin = 0;
    while (begin < width && field[begin] == ' ') ++begin;
    size_t end = width;
    while (end > begin && (field[end - 1] == '\0' || field[end - 1] == ' ')) --end;
    if (begin == end) return true;
    for (size_t index = begin; index < end; ++index) {
        const unsigned char ch = static_cast<unsigned char>(field[index]);
        if (ch < '0' || ch > '7') return false;
        const uint64_t digit = static_cast<uint64_t>(ch - '0');
        if (value > (std::numeric_limits<uint64_t>::max() - digit) / 8) return false;
        value = value * 8 + digit;
    }
    return true;
}

bool isZeroBlock(const std::vector<char>& block) {
    return std::all_of(block.begin(), block.end(), [](char value) { return value == '\0'; });
}

std::string tarText(const char* field, size_t width) {
    return std::string(field, strnlen(field, width));
}

}  // namespace

TarIndex::~TarIndex() {
    if (ownsTemp_) std::remove(dataFile_.c_str());
}

bool TarIndex::build(const std::string& bakPath, uint64_t payloadOffset, bool doInflate,
                     const fs::path& requestedTemporaryRoot,
                     uint64_t maximumInflatedBytes) {
    entries_.clear();
    if (ownsTemp_) std::remove(dataFile_.c_str());
    dataFile_ = bakPath;
    ownsTemp_ = false;
    if (doInflate) {
#ifdef USE_ZLIB
        std::string tmp;
        std::ifstream in(bakPath, std::ios::binary);
        if (!in) return false;
        in.seekg(payloadOffset);
        if (!in) return false;
        std::ofstream out;
        fs::path temporaryRoot = requestedTemporaryRoot;
        if (temporaryRoot.empty()) {
            std::error_code tempError;
            temporaryRoot = fs::temp_directory_path(tempError);
            if (tempError) return false;
        }
        if (!createTemporaryFile(temporaryRoot, tmp, out)) return false;
        z_stream zs{};
        if (inflateInit(&zs) != Z_OK) {
            out.close(); std::remove(tmp.c_str());
            return false;
        }
        std::vector<char> ibuf(1<<20), obuf(1<<20);
        uint64_t totalInflated = 0;
        bool done = false;
        while (!done) {
            in.read(ibuf.data(), ibuf.size()); zs.avail_in = in.gcount();
            if (!zs.avail_in) break;
            zs.next_in = reinterpret_cast<Bytef*>(ibuf.data());
            do {
                zs.next_out = reinterpret_cast<Bytef*>(obuf.data());
                zs.avail_out = obuf.size();
                int r = inflate(&zs, Z_NO_FLUSH);
                const uint64_t produced = obuf.size() - zs.avail_out;
                if (produced > maximumInflatedBytes - totalInflated) {
                    inflateEnd(&zs); out.close(); std::remove(tmp.c_str()); return false;
                }
                out.write(obuf.data(), static_cast<std::streamsize>(produced));
                totalInflated += produced;
                if (!out) { inflateEnd(&zs); out.close(); std::remove(tmp.c_str()); return false; }
                if (r == Z_STREAM_END) { done = true; break; }
                if (r != Z_OK) { inflateEnd(&zs); out.close(); std::remove(tmp.c_str()); return false; }
            } while (zs.avail_out == 0);
        }
        inflateEnd(&zs);
        out.flush();
        const bool outputOk = out.good();
        out.close();
        if (!done || !outputOk || !out.good()) {
            std::remove(tmp.c_str());
            return false;
        }
        dataFile_ = tmp; ownsTemp_ = true; payloadOffset = 0;
#else
        return false; // zlib unavailable
#endif
    }
    std::ifstream f(dataFile_, std::ios::binary);
    if (!f) return false;
    f.seekg(payloadOffset);
    if (!f) return false;
    std::vector<char> hdr(kTarBlockBytes);
    while (true) {
        f.read(hdr.data(), static_cast<std::streamsize>(hdr.size()));
        if (f.gcount() != static_cast<std::streamsize>(hdr.size())) return false;
        if (isZeroBlock(hdr)) {
            std::vector<char> second(kTarBlockBytes);
            f.read(second.data(), static_cast<std::streamsize>(second.size()));
            return f.gcount() == static_cast<std::streamsize>(second.size()) && isZeroBlock(second);
        }

        std::string name = tarText(hdr.data(), 100);
        const std::string prefix = tarText(hdr.data() + 345, 155);
        if (!prefix.empty()) {
            static constexpr char kUstarMagic[] = {'u', 's', 't', 'a', 'r', '\0'};
            static constexpr char kUstarVersion[] = {'0', '0'};
            if (std::memcmp(hdr.data() + 257, kUstarMagic, sizeof(kUstarMagic)) != 0 ||
                std::memcmp(hdr.data() + 263, kUstarVersion, sizeof(kUstarVersion)) != 0) {
                return false;
            }
            name = prefix + "/" + name;
        }
        if (name.empty()) return false;

        uint64_t size = 0;
        uint64_t modifiedTime = 0;
        if (!parseOctal(hdr.data() + 124, 12, size) ||
            !parseOctal(hdr.data() + 136, 12, modifiedTime)) {
            return false;
        }
        const char typeFlag = hdr[156];
        const std::streampos position = f.tellg();
        if (position < 0) return false;
        const uint64_t dataOff = static_cast<uint64_t>(position);
        if (size > std::numeric_limits<uint64_t>::max() - 511) return false;
        const uint64_t padded = (size + 511) & ~uint64_t(511);
        if (dataOff > std::numeric_limits<uint64_t>::max() - padded) return false;
        entries_[name] = {dataOff, size, modifiedTime, typeFlag};
        f.seekg(static_cast<std::streamoff>(dataOff + padded));
        if (!f) return false;
    }
}

bool TarIndex::find(const std::string& memberName, TarEntry& out) const {
    auto it = entries_.find(memberName);
    if (it == entries_.end()) return false;
    out = it->second; return true;
}

bool TarIndex::readEntry(const TarEntry& e, const std::string& outPath) const {
    std::ifstream in(dataFile_, std::ios::binary);
    if (!in) return false;
    in.seekg(0, std::ios::end);
    uint64_t fileSize = (uint64_t)in.tellg();
    if (e.dataOffset > fileSize) return false;
    uint64_t remaining = fileSize - e.dataOffset;
    if (e.size > remaining) return false;   // reject oversized/corrupt tar header
    in.seekg(e.dataOffset);
    if (!in) return false;
    std::ofstream out(outPath, std::ios::binary | std::ios::trunc);
    if (!out) return false;

    constexpr size_t kBufferSize = 1 << 20;
    std::vector<char> buffer(kBufferSize);
    uint64_t remainingToRead = e.size;
    while (remainingToRead > 0) {
        const std::streamsize chunk = static_cast<std::streamsize>(
            std::min<uint64_t>(remainingToRead, buffer.size()));
        in.read(buffer.data(), chunk);
        if (in.gcount() != chunk) {
            out.close();
            std::remove(outPath.c_str());
            return false;
        }
        out.write(buffer.data(), chunk);
        if (!out) {
            out.close();
            std::remove(outPath.c_str());
            return false;
        }
        remainingToRead -= static_cast<uint64_t>(chunk);
    }
    out.flush();
    const bool outputOk = out.good();
    out.close();
    if (!outputOk || !out.good()) {
        std::remove(outPath.c_str());
        return false;
    }
    return true;
}
