#include "TarIndex.h"
#include <fstream>
#include <vector>
#include <algorithm>
#include <filesystem>
#include <cstdlib>
#include <unistd.h>
#include <cstring>
#include <sstream>
#ifdef USE_ZLIB
#include <zlib.h>
#endif

namespace fs = std::filesystem;

namespace {

bool createTemporaryFile(std::string& path, std::ofstream& output) {
    fs::path directory;
    try {
        directory = fs::temp_directory_path();
    } catch (const fs::filesystem_error&) {
        return false;
    }

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

}  // namespace

TarIndex::~TarIndex() {
    if (ownsTemp_) std::remove(dataFile_.c_str());
}

static uint64_t parseOctal(const char* s, int width) {
    uint64_t v = 0;
    for (int i = 0; i < width && s[i]; ++i) {
        if (s[i] >= '0' && s[i] <= '7') v = v * 8 + (s[i] - '0');
    }
    return v;
}

bool TarIndex::build(const std::string& bakPath, uint64_t payloadOffset, bool doInflate) {
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
        if (!createTemporaryFile(tmp, out)) return false;
        z_stream zs{};
        if (inflateInit(&zs) != Z_OK) {
            out.close(); std::remove(tmp.c_str());
            return false;
        }
        std::vector<char> ibuf(1<<20), obuf(1<<20);
        bool done = false;
        while (!done) {
            in.read(ibuf.data(), ibuf.size()); zs.avail_in = in.gcount();
            if (!zs.avail_in) break;
            zs.next_in = reinterpret_cast<Bytef*>(ibuf.data());
            do {
                zs.next_out = reinterpret_cast<Bytef*>(obuf.data());
                zs.avail_out = obuf.size();
                int r = inflate(&zs, Z_NO_FLUSH);
                out.write(obuf.data(), obuf.size() - zs.avail_out);
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
    std::vector<char> hdr(512);
    bool sawEnd = false;
    while (true) {
        f.read(hdr.data(), 512);
        if (f.gcount() == 0 && f.eof()) break;
        if (f.gcount() != 512) return false;
        if (hdr[0] == 0) {
            sawEnd = true;
            break;
        }
        std::string name(hdr.data(), strnlen(hdr.data(), 100));
        if (name.empty()) return false;
        uint64_t size = parseOctal(hdr.data() + 124, 12);
        uint64_t dataOff = (uint64_t)f.tellg();  // position after the 512-byte header == start of file data
        entries_[name] = { dataOff, size };
        uint64_t padded = (size + 511) & ~uint64_t(511);
        f.seekg((uint64_t)f.tellg() + padded);
        if (!f) return false;
    }
    return sawEnd;
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
