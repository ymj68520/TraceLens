// PrefetchParser.cpp
// Implementation of Windows Prefetch (.pf) file parser

#include "WindowsPrefetchParser.h"
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cstring>
#include <array>

// ============================================================================
// PrefetchHelpers Implementation
// ============================================================================

namespace PrefetchHelpers {

// ---------------------------------------------------------------------------
// XPRESS Huffman (MS-XCA) decompressor
//
// Mirrors dissect.util.compression.lzxpress_huffman.decompress. The bit
// stream is MSB-first: mask holds the next 32 bits and lookup(n) reads the
// top n. Keeping this structure (rather than a byte-oriented reader) is what
// makes the symbol stream decode correctly — an LSB-first reader reproduces
// the first few literals and then diverges.
// ---------------------------------------------------------------------------
namespace {

struct HuffmanNode {
    int children[2] = {0, 0};
    int symbol = -1;
    bool is_leaf = false;
};

class XpressBitReader {
public:
    XpressBitReader(const std::vector<uint8_t>& data, size_t offset)
        : data_(data), pos_(offset) {}

    bool init() {
        uint16_t hi = 0, lo = 0;
        if (!readU16(hi) || !readU16(lo)) return false;
        mask_ = (static_cast<uint32_t>(hi) << 16) + lo;
        bits_ = 32;
        return true;
    }

    uint32_t lookup(int n) const {
        if (n == 0) return 0;
        return mask_ >> (32 - n);
    }

    void skip(int n) {
        mask_ = (mask_ << n) & 0xFFFFFFFFu;
        bits_ -= n;
        if (bits_ < 16) {
            uint16_t next = 0;
            if (readU16(next)) {
                mask_ += static_cast<uint32_t>(next) << (16 - bits_);
            }
            bits_ += 16;
        }
    }

    bool readByte(uint8_t& out) {
        if (pos_ >= data_.size()) return false;
        out = data_[pos_++];
        return true;
    }

    size_t position() const { return pos_; }
    bool exhausted() const { return pos_ >= data_.size() && bits_ <= 0; }

private:
    bool readU16(uint16_t& out) {
        if (pos_ + 2 > data_.size()) return false;
        out = static_cast<uint16_t>(data_[pos_] | (data_[pos_ + 1] << 8));
        pos_ += 2;
        return true;
    }

    const std::vector<uint8_t>& data_;
    size_t pos_;
    uint32_t mask_ = 0;
    int bits_ = 0;
};

// Builds the decode tree the same way the reference does: symbols are sorted
// by (length, symbol index) and leaves are woven into a 1024-node arena.
int buildTree(const uint8_t* table, std::array<HuffmanNode, 1024>& nodes) {
    struct Sym { int length; int symbol; };
    std::vector<Sym> symbols;
    symbols.reserve(512);
    for (int i = 0; i < 256; ++i) {
        symbols.push_back({table[i] & 0x0F, i * 2});
        symbols.push_back({(table[i] >> 4) & 0x0F, i * 2 + 1});
    }
    std::sort(symbols.begin(), symbols.end(), [](const Sym& a, const Sym& b) {
        if (a.length != b.length) return a.length < b.length;
        return a.symbol < b.symbol;
    });

    int start = 0;
    while (start < 512 && symbols[start].length == 0) ++start;

    uint32_t mask = 0;
    int bits = 1;
    int treeIndex = 1;

    for (int symbolIndex = start; symbolIndex < 512; ++symbolIndex) {
        const Sym& s = symbols[symbolIndex];

        HuffmanNode& node = nodes[treeIndex];
        node.symbol = s.symbol;
        node.is_leaf = true;

        mask = (mask << (s.length - bits)) & 0xFFFFFFFFu;
        bits = s.length;

        // _add_leaf: walk down `bits - 1` levels creating children as needed.
        int idx = treeIndex;
        HuffmanNode* cur = &nodes[0];
        int i = idx + 1;
        int remaining = bits;
        while (remaining > 1) {
            --remaining;
            int childIndex = (mask >> remaining) & 1;
            if (cur->children[childIndex] == 0) {
                cur->children[childIndex] = i;
                nodes[i].is_leaf = false;
                ++i;
            }
            cur = &nodes[cur->children[childIndex]];
        }
        cur->children[mask & 1] = idx;
        treeIndex = i;
        ++mask;
    }
    return treeIndex;
}

bool decodeSymbol(XpressBitReader& reader, const std::array<HuffmanNode, 1024>& nodes, int& out) {
    int idx = 0;
    int guard = 0;
    while (!nodes[idx].is_leaf) {
        if (++guard > 32) return false;
        uint32_t bit = reader.lookup(1);
        reader.skip(1);
        int next = nodes[idx].children[bit];
        if (next == 0 && !nodes[next].is_leaf) {
            // node 0 is the root; a zero child means an invalid code
            if (idx != 0) return false;
        }
        idx = next;
    }
    out = nodes[idx].symbol;
    return true;
}

} // namespace

bool decompressXpressHuffman(const std::vector<uint8_t>& src, std::vector<uint8_t>& dst,
                             size_t expectedSize) {
    dst.clear();
    if (src.size() < 256) return false;

    // Exactly one Huffman table precedes the whole bit stream. The MS-XCA
    // chunk loop below (65536 uncompressed bytes per chunk) is what delimits
    // blocks; re-entering an outer loop re-reads the table and duplicates
    // output (a 36076-byte .pf came back as 65538 bytes).
    std::array<HuffmanNode, 1024> nodes{};
    buildTree(src.data(), nodes);

    XpressBitReader reader(src, 256);
    if (!reader.init()) return false;

    // The caller knows the expected size (MAM header / SCCA 0x0C). Stop at it:
    // once the bit stream is exhausted the reader keeps returning zero bits,
    // which decode as valid symbols and inflate the output with garbage.
    size_t limit = expectedSize;
    if (limit == 0) {
        // No declared size: stop as soon as the source is consumed.
        limit = static_cast<size_t>(-1);
    }

    size_t chunk = 0;
    while (chunk < 65536 && dst.size() < limit && reader.position() <= src.size()) {
        int symbol = 0;
        if (!decodeSymbol(reader, nodes, symbol)) break;

        if (symbol < 256) {
            dst.push_back(static_cast<uint8_t>(symbol));
            ++chunk;
        } else {
            symbol -= 256;
            int length = symbol & 0x0F;
            int offsetBits = symbol >> 4;

            size_t distance = (static_cast<size_t>(1) << offsetBits) + reader.lookup(offsetBits);

            if (length == 15) {
                uint8_t extra = 0;
                if (!reader.readByte(extra)) return !dst.empty();
                length = extra + 15;
                if (length == 270) {
                    if (reader.position() + 2 > src.size()) return !dst.empty();
                    length = src[reader.position()] | (src[reader.position() + 1] << 8);
                    reader.skip(16);
                }
            }

            reader.skip(offsetBits);
            length += 3;

            if (distance == 0 || distance > dst.size()) return !dst.empty();

            size_t remaining = static_cast<size_t>(length);
            while (remaining > 0) {
                size_t matchSize = std::min(remaining, distance);
                size_t start = dst.size() - distance;
                for (size_t i = 0; i < matchSize; ++i) {
                    dst.push_back(dst[start + i]);
                }
                remaining -= matchSize;
            }
            chunk += static_cast<size_t>(length);
        }
    }
    return !dst.empty();
}


PrefetchVersion detectVersion(const char* header) {
    // The caller always passes a DECOMPRESSED image here (MAM containers are
    // expanded in PrefetchParser::parse), so the header is plain SCCA:
    //   +0x00 u32 version, +0x04 "SCCA".
    // Reading a version field at +4/+8 was only meaningful for the raw
    // compressed container and produced garbage once decompression landed.
    if (std::memcmp(header + 4, "SCCA", 4) != 0) {
        return PrefetchVersion::UNKNOWN;
    }
    switch (readUInt32LE(header)) {
        case 17: return PrefetchVersion::VERSION_17;
        case 23: return PrefetchVersion::VERSION_23;
        case 26: return PrefetchVersion::VERSION_26;
        case 30: return PrefetchVersion::VERSION_30;
        case 31: return PrefetchVersion::VERSION_31;
        default: return PrefetchVersion::UNKNOWN;
    }
}

int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0) return 0;

    // Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
    // Unix timestamp: seconds since January 1, 1970 UTC
    // Difference: 11,644,473,600 seconds (369 years)
    const uint64_t TICKS_PER_SECOND = 10000000;
    const uint64_t EPOCH_DIFFERENCE = 11644473600ULL;

    return static_cast<int64_t>((filetime / TICKS_PER_SECOND) - EPOCH_DIFFERENCE);
}

uint16_t readUInt16LE(const char* data) {
    return static_cast<uint16_t>(
        static_cast<unsigned char>(data[0]) |
        (static_cast<unsigned char>(data[1]) << 8)
    );
}

uint32_t readUInt32LE(const char* data) {
    return static_cast<uint32_t>(
        static_cast<unsigned char>(data[0]) |
        (static_cast<unsigned char>(data[1]) << 8) |
        (static_cast<unsigned char>(data[2]) << 16) |
        (static_cast<unsigned char>(data[3]) << 24)
    );
}

uint64_t readUInt64LE(const char* data) {
    return static_cast<uint64_t>(
        static_cast<uint64_t>(static_cast<unsigned char>(data[0])) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[1])) << 8) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[2])) << 16) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[3])) << 24) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[4])) << 32) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[5])) << 40) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[6])) << 48) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[7])) << 56)
    );
}

std::string extractExecutableNameFromFilename(const std::string& filename) {
    // Extract base filename without path
    size_t lastSlash = filename.find_last_of("/\\");
    std::string basename = (lastSlash != std::string::npos) ?
        filename.substr(lastSlash + 1) : filename;

    // Remove .pf extension
    size_t dotPos = basename.find_last_of('.');
    if (dotPos != std::string::npos) {
        basename = basename.substr(0, dotPos);
    }

    // Extract executable name (before hash)
    // Format: EXENAME-HASH or EXENAME-HASH-DEL
    size_t dashPos = basename.find('-');
    if (dashPos != std::string::npos) {
        return basename.substr(0, dashPos);
    }

    return basename;
}

std::string extractHashFromFilename(const std::string& filename) {
    size_t lastSlash = filename.find_last_of("/\\");
    std::string basename = (lastSlash != std::string::npos) ?
        filename.substr(lastSlash + 1) : filename;

    size_t dotPos = basename.find_last_of('.');
    if (dotPos != std::string::npos) {
        basename = basename.substr(0, dotPos);
    }

    size_t firstDash = basename.find('-');
    if (firstDash != std::string::npos) {
        size_t secondDash = basename.find('-', firstDash + 1);
        if (secondDash != std::string::npos) {
            // EXENAME-HASH-DEL format
            return basename.substr(firstDash + 1, secondDash - firstDash - 1);
        }
        // EXENAME-HASH format
        return basename.substr(firstDash + 1);
    }

    return "";
}

bool isValidPrefetchFile(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) return false;

    char header[4];
    file.read(header, 4);
    if (file.gcount() < 4) return false;

    // Check for valid signatures
    if (std::memcmp(header, "MAM", 3) == 0 || std::memcmp(header, "SCCA", 4) == 0) {
        return true;
    }

    return false;
}

std::string calculatePrefetchHash(const std::string& executableName) {
    // This is a simplified placeholder
    // The real prefetch hash algorithm is more complex and involves:
    // 1. Converting executable name to uppercase
    // 2. Normalizing the path
    // 3. Computing a checksum/hash
    // For now, return a placeholder based on string length
    std::ostringstream oss;
    oss << std::hex << std::setw(8) << std::setfill('0')
        << (std::hash<std::string>{}(executableName) & 0xFFFFFFFF);
    return oss.str();
}

} // namespace PrefetchHelpers
