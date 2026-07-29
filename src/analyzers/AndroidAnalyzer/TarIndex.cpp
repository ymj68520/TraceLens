#include "TarIndex.h"
#include <fstream>
#include <vector>
#include <cstring>
#include <sstream>
#ifdef USE_ZLIB
#include <zlib.h>
#endif

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
        std::string tmp = bakPath + ".inflated.tmp";
        std::ifstream in(bakPath, std::ios::binary);
        in.seekg(payloadOffset);
        std::ofstream out(tmp, std::ios::binary);
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
                if (r == Z_STREAM_END) { done = true; break; }
                if (r != Z_OK) { inflateEnd(&zs); out.close(); std::remove(tmp.c_str()); return false; }
            } while (zs.avail_out == 0);
        }
        inflateEnd(&zs);
        out.close();
        if (!done) {
            // truncated zlib stream (input ended without Z_STREAM_END)
            std::remove(tmp.c_str());
            return false;
        }
        dataFile_ = tmp; ownsTemp_ = true; payloadOffset = 0;
#else
        return false; // zlib unavailable
#endif
    }
    std::ifstream f(dataFile_, std::ios::binary);
    f.seekg(payloadOffset);
    std::vector<char> hdr(512);
    while (true) {
        f.read(hdr.data(), 512);
        if (f.gcount() != 512) break;
        if (hdr[0] == 0) break; // end-of-archive zero block
        std::string name(hdr.data(), strnlen(hdr.data(), 100));
        if (name.empty()) break;
        uint64_t size = parseOctal(hdr.data() + 124, 12);
        uint64_t dataOff = (uint64_t)f.tellg();  // position after the 512-byte header == start of file data
        entries_[name] = { dataOff, size };
        uint64_t padded = (size + 511) & ~uint64_t(511);
        f.seekg((uint64_t)f.tellg() + padded);
    }
    return true;
}

bool TarIndex::find(const std::string& memberName, TarEntry& out) const {
    auto it = entries_.find(memberName);
    if (it == entries_.end()) return false;
    out = it->second; return true;
}

bool TarIndex::readEntry(const TarEntry& e, const std::string& outPath) const {
    std::ifstream in(dataFile_, std::ios::binary);
    in.seekg(0, std::ios::end);
    uint64_t fileSize = (uint64_t)in.tellg();
    if (e.dataOffset > fileSize) return false;
    uint64_t remaining = fileSize - e.dataOffset;
    if (e.size > remaining) return false;   // reject oversized/corrupt tar header
    in.seekg(e.dataOffset);
    std::vector<char> buf(e.size);
    in.read(buf.data(), e.size);
    if ((uint64_t)in.gcount() != e.size) return false;
    std::ofstream out(outPath, std::ios::binary);
    out.write(buf.data(), e.size);
    return out.good();
}
