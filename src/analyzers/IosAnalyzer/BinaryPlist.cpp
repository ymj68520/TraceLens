#include "BinaryPlist.h"

#include <cstring>
#include <fstream>
#include <sstream>

namespace plist {
namespace {

constexpr const char kMagic[] = "bplist00";
constexpr std::size_t kMagicSize = 8;
constexpr std::size_t kTrailerSize = 32;
constexpr int kMaxDepth = 128;

std::uint64_t readBigEndian(const std::string& bytes, std::size_t position, std::size_t width) {
    std::uint64_t value = 0;
    for (std::size_t i = 0; i < width; ++i) {
        value = (value << 8) | static_cast<unsigned char>(bytes[position + i]);
    }
    return value;
}

class Parser {
public:
    Parser(const std::string& bytes) : bytes_(bytes) {}

    ValuePtr parse() {
        if (bytes_.size() < kMagicSize + kTrailerSize) return nullptr;
        if (std::memcmp(bytes_.data(), kMagic, kMagicSize) != 0) return nullptr;

        const std::size_t trailer = bytes_.size() - kTrailerSize;
        offsetSize_ = static_cast<unsigned char>(bytes_[trailer + 6]);
        referenceSize_ = static_cast<unsigned char>(bytes_[trailer + 7]);
        const std::uint64_t objectCount = readBigEndian(bytes_, trailer + 8, 8);
        const std::uint64_t topObject = readBigEndian(bytes_, trailer + 16, 8);
        const std::uint64_t offsetTable = readBigEndian(bytes_, trailer + 24, 8);

        if (offsetSize_ == 0 || offsetSize_ > 8 || referenceSize_ == 0 || referenceSize_ > 8) {
            return nullptr;
        }
        if (objectCount == 0 || objectCount > 10'000'000) return nullptr;
        if (offsetTable >= trailer) return nullptr;
        if (offsetTable + objectCount * offsetSize_ > trailer) return nullptr;
        if (topObject >= objectCount) return nullptr;

        offsets_.reserve(static_cast<std::size_t>(objectCount));
        for (std::uint64_t i = 0; i < objectCount; ++i) {
            const std::size_t position =
                static_cast<std::size_t>(offsetTable + i * offsetSize_);
            offsets_.push_back(readBigEndian(bytes_, position, offsetSize_));
        }
        objectCount_ = objectCount;
        return readObject(topObject, 0);
    }

private:
    ValuePtr readObject(std::uint64_t index, int depth) {
        if (depth > kMaxDepth) return nullptr;
        if (index >= objectCount_ || index >= offsets_.size()) return nullptr;
        const std::size_t start = offsets_[static_cast<std::size_t>(index)];
        if (start >= bytes_.size()) return nullptr;

        const unsigned char marker = static_cast<unsigned char>(bytes_[start]);
        const unsigned char type = marker >> 4;
        const unsigned char info = marker & 0x0F;

        switch (type) {
            case 0x0: {  // singletons: null, false, true, fill
                auto value = std::make_shared<Value>();
                if (info == 0x8) { value->kind = Value::Kind::Boolean; value->boolean = false; }
                else if (info == 0x9) { value->kind = Value::Kind::Boolean; value->boolean = true; }
                return value;
            }
            case 0x1: {  // integer, 2^info bytes
                const std::size_t width = std::size_t{1} << info;
                if (width > 8 || start + 1 + width > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::Integer;
                // Signed for 8-byte values, as Apple encodes negative numbers.
                if (width == 8) {
                    value->integer = static_cast<long long>(readBigEndian(bytes_, start + 1, 8));
                } else {
                    value->integer = static_cast<long long>(readBigEndian(bytes_, start + 1, width));
                }
                return value;
            }
            case 0x2: {  // real, 2^info bytes (4 or 8)
                const std::size_t width = std::size_t{1} << info;
                if ((width != 4 && width != 8) || start + 1 + width > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::Real;
                if (width == 8) {
                    std::uint64_t raw = readBigEndian(bytes_, start + 1, 8);
                    std::memcpy(&value->real, &raw, 8);
                } else {
                    std::uint32_t raw = static_cast<std::uint32_t>(readBigEndian(bytes_, start + 1, 4));
                    float single = 0.0f;
                    std::memcpy(&single, &raw, 4);
                    value->real = single;
                }
                return value;
            }
            case 0x3: {  // date: 8-byte big-endian double, seconds since 2001-01-01
                if (start + 9 > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::Date;
                std::uint64_t raw = readBigEndian(bytes_, start + 1, 8);
                double seconds = 0.0;
                std::memcpy(&seconds, &raw, 8);
                std::ostringstream text;
                text << seconds;
                value->text = text.str();
                value->real = seconds;
                return value;
            }
            case 0x4: {  // data
                std::size_t length = 0;
                std::size_t payload = 0;
                if (!readLength(info, start, &length, &payload)) return nullptr;
                if (payload + length > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::String;
                value->text = bytes_.substr(payload, length);
                return value;
            }
            case 0x5: {  // ASCII string
                std::size_t length = 0;
                std::size_t payload = 0;
                if (!readLength(info, start, &length, &payload)) return nullptr;
                if (payload + length > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::String;
                value->text = bytes_.substr(payload, length);
                return value;
            }
            case 0x6: {  // UTF-16BE string
                std::size_t length = 0;
                std::size_t payload = 0;
                if (!readLength(info, start, &length, &payload)) return nullptr;
                if (length > 100'000'000) return nullptr;
                if (payload + length * 2 > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::String;
                value->text = utf16ToUtf8(payload, length);
                return value;
            }
            case 0x8: {  // UID (keyed archives only)
                const std::size_t width = info + 1;
                if (start + 1 + width > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::Integer;
                value->integer = static_cast<long long>(readBigEndian(bytes_, start + 1, width));
                return value;
            }
            case 0xA:    // array
            case 0xB:    // ordered set
            case 0xC: {  // set
                std::size_t count = 0;
                std::size_t payload = 0;
                if (!readLength(info, start, &count, &payload)) return nullptr;
                if (count > 10'000'000) return nullptr;
                if (payload + count * referenceSize_ > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::Array;
                value->array.reserve(count);
                for (std::size_t i = 0; i < count; ++i) {
                    const std::uint64_t reference =
                        readBigEndian(bytes_, payload + i * referenceSize_, referenceSize_);
                    auto child = readObject(reference, depth + 1);
                    if (!child) return nullptr;
                    value->array.push_back(std::move(child));
                }
                return value;
            }
            case 0xD: {  // dictionary
                std::size_t count = 0;
                std::size_t payload = 0;
                if (!readLength(info, start, &count, &payload)) return nullptr;
                if (count > 10'000'000) return nullptr;
                if (payload + count * referenceSize_ * 2 > bytes_.size()) return nullptr;
                auto value = std::make_shared<Value>();
                value->kind = Value::Kind::Dictionary;
                for (std::size_t i = 0; i < count; ++i) {
                    const std::uint64_t keyReference =
                        readBigEndian(bytes_, payload + i * referenceSize_, referenceSize_);
                    const std::uint64_t valueReference =
                        readBigEndian(bytes_, payload + (count + i) * referenceSize_, referenceSize_);
                    auto key = readObject(keyReference, depth + 1);
                    auto child = readObject(valueReference, depth + 1);
                    if (!key || !child) return nullptr;
                    if (!key->isString()) continue;
                    value->dictionary[key->text] = std::move(child);
                }
                return value;
            }
            default:
                return nullptr;
        }
    }

    /** Decode the length that follows a marker; handles the 0xF extension. */
    bool readLength(unsigned char info, std::size_t start, std::size_t* length,
                    std::size_t* payload) const {
        if (info != 0x0F) {
            *length = info;
            *payload = start + 1;
            return true;
        }
        if (start + 2 > bytes_.size()) return false;
        const unsigned char marker = static_cast<unsigned char>(bytes_[start + 1]);
        if ((marker >> 4) != 0x1) return false;
        const std::size_t width = std::size_t{1} << (marker & 0x0F);
        if (width > 8 || start + 2 + width > bytes_.size()) return false;
        *length = static_cast<std::size_t>(readBigEndian(bytes_, start + 2, width));
        *payload = start + 2 + width;
        return true;
    }

    std::string utf16ToUtf8(std::size_t payload, std::size_t units) const {
        std::string out;
        out.reserve(units * 3);
        for (std::size_t i = 0; i < units; ++i) {
            std::uint32_t code = static_cast<std::uint32_t>(
                readBigEndian(bytes_, payload + i * 2, 2));
            // Surrogate pair.
            if (code >= 0xD800 && code <= 0xDBFF && i + 1 < units) {
                const std::uint32_t low = static_cast<std::uint32_t>(
                    readBigEndian(bytes_, payload + (i + 1) * 2, 2));
                if (low >= 0xDC00 && low <= 0xDFFF) {
                    code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00);
                    ++i;
                }
            }
            if (code < 0x80) {
                out.push_back(static_cast<char>(code));
            } else if (code < 0x800) {
                out.push_back(static_cast<char>(0xC0 | (code >> 6)));
                out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
            } else if (code < 0x10000) {
                out.push_back(static_cast<char>(0xE0 | (code >> 12)));
                out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
                out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
            } else {
                out.push_back(static_cast<char>(0xF0 | (code >> 18)));
                out.push_back(static_cast<char>(0x80 | ((code >> 12) & 0x3F)));
                out.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3F)));
                out.push_back(static_cast<char>(0x80 | (code & 0x3F)));
            }
        }
        return out;
    }

    const std::string& bytes_;
    std::vector<std::size_t> offsets_;
    std::uint64_t objectCount_ = 0;
    std::size_t offsetSize_ = 0;
    std::size_t referenceSize_ = 0;
};

/** Very small XML fallback: <key>K</key><string>V</string> pairs only. */
ValuePtr parseXml(const std::string& xml) {
    auto root = std::make_shared<Value>();
    root->kind = Value::Kind::Dictionary;
    std::size_t position = 0;
    while (true) {
        const std::size_t keyStart = xml.find("<key>", position);
        if (keyStart == std::string::npos) break;
        const std::size_t keyEnd = xml.find("</key>", keyStart);
        if (keyEnd == std::string::npos) break;
        const std::string key = xml.substr(keyStart + 5, keyEnd - keyStart - 5);
        position = keyEnd + 6;
        while (position < xml.size() &&
               std::isspace(static_cast<unsigned char>(xml[position]))) {
            ++position;
        }
        auto child = std::make_shared<Value>();
        if (xml.compare(position, 8, "<string>") == 0) {
            const std::size_t end = xml.find("</string>", position);
            if (end == std::string::npos) break;
            child->kind = Value::Kind::String;
            child->text = xml.substr(position + 8, end - position - 8);
            position = end + 9;
        } else if (xml.compare(position, 6, "<true/") == 0) {
            child->kind = Value::Kind::Boolean;
            child->boolean = true;
            position += 7;
        } else if (xml.compare(position, 7, "<false/") == 0) {
            child->kind = Value::Kind::Boolean;
            child->boolean = false;
            position += 8;
        } else if (xml.compare(position, 8, "<integer>") == 0) {
            const std::size_t end = xml.find("</integer>", position);
            if (end == std::string::npos) break;
            child->kind = Value::Kind::Integer;
            try {
                child->integer = std::stoll(xml.substr(position + 9, end - position - 9));
            } catch (...) {
                child->integer = 0;
            }
            position = end + 10;
        } else {
            continue;
        }
        root->dictionary[key] = std::move(child);
    }
    return root;
}

}  // namespace

ValuePtr Value::get(const std::string& key) const {
    if (kind != Kind::Dictionary) return nullptr;
    const auto found = dictionary.find(key);
    return found == dictionary.end() ? nullptr : found->second;
}

std::string Value::stringOr(const std::string& key, const std::string& fallback) const {
    const auto child = get(key);
    if (!child || !child->isString()) return fallback;
    return child->text;
}

long long Value::integerOr(const std::string& key, long long fallback) const {
    const auto child = get(key);
    if (!child || child->kind != Kind::Integer) return fallback;
    return child->integer;
}

bool Value::booleanOr(const std::string& key, bool fallback) const {
    const auto child = get(key);
    if (!child || !child->isBoolean()) return fallback;
    return child->boolean;
}

bool looksBinary(const std::string& bytes) {
    return bytes.size() >= kMagicSize && std::memcmp(bytes.data(), kMagic, kMagicSize) == 0;
}

ValuePtr parseBinaryPlist(const std::string& bytes) {
    Parser parser(bytes);
    return parser.parse();
}

ValuePtr parsePlistFile(const std::string& path, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error) *error = "PLIST_UNREADABLE";
        return nullptr;
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    const std::string bytes = buffer.str();
    if (bytes.empty()) {
        if (error) *error = "PLIST_EMPTY";
        return nullptr;
    }
    if (looksBinary(bytes)) {
        auto value = parseBinaryPlist(bytes);
        if (!value && error) *error = "PLIST_BINARY_MALFORMED";
        return value;
    }
    // XML plist; the fallback is intentionally shallow.
    if (bytes.find("<plist") != std::string::npos) {
        return parseXml(bytes);
    }
    if (error) *error = "PLIST_UNKNOWN_FORMAT";
    return nullptr;
}

}  // namespace plist
