#include "ThunderForensicBackupExtractor.h"

#include <openssl/evp.h>
#include <algorithm>
#include <array>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <limits>
#include <memory>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

// Containers above this size are indexed but not hashed end-to-end by default.
// A 53 GiB ThunderForensic container takes ~10 minutes to read on a typical
// evidence disk, which would make every task pay the cost up front. The
// manifest records container_sha256_status so the omission is explicit.
constexpr std::uint64_t kFullHashLimit = 4ULL << 30;
constexpr std::size_t kMaxEntries = 2000000;
constexpr std::size_t kMaxLongName = 1ULL << 20;
constexpr std::size_t kMaxPaxRecord = 4ULL << 20;
constexpr const char* kManifestMember = "ThunderForensic.json";
constexpr const char* kPhoneDataPrefix = "PhoneData/";
constexpr const char* kAdapterVersion = "thunderforensic-v2";

bool isUstarHeader(const unsigned char* block) {
    return std::memcmp(block + 257, "ustar", 5) == 0;
}

bool allZero(const unsigned char* block) {
    for (std::size_t i = 0; i < 512; ++i)
        if (block[i] != 0) return false;
    return true;
}

std::string fieldString(const unsigned char* block, std::size_t offset, std::size_t length) {
    const char* begin = reinterpret_cast<const char*>(block + offset);
    std::size_t used = 0;
    while (used < length && begin[used] != '\0') ++used;
    return std::string(begin, used);
}

// Octal numeric field (standard) with a base-256 fallback (GNU). Returns false
// for the obsolescent negative base-64 form; ThunderForensic only uses that
// for the gid field, which the index does not need.
bool parseNumeric(const unsigned char* field, std::size_t length, std::uint64_t& value) {
    if (length == 0) return false;
    if (field[0] & 0x80) {
        std::uint64_t result = field[0] & 0x7f;
        for (std::size_t i = 1; i < length; ++i)
            result = (result << 8) | field[i];
        value = result;
        return true;
    }
    std::size_t i = 0;
    while (i < length && (field[i] == ' ' || field[i] == '\0')) ++i;
    bool any = false;
    std::uint64_t result = 0;
    for (; i < length; ++i) {
        const unsigned char c = field[i];
        if (c == '\0' || c == ' ') break;
        if (c < '0' || c > '7') return false;
        result = result * 8 + (c - '0');
        any = true;
    }
    value = result;
    return any;
}

std::uint64_t roundBlocks(std::uint64_t size) {
    return ((size + 511) / 512) * 512;
}

// Read-only view over the evidence container. mmap keeps large containers
// fast (the kernel pages in only the header blocks actually touched); pread is
// the fallback when mapping is unavailable.
class MappedFile {
public:
    ~MappedFile() { close(); }
    MappedFile() = default;
    MappedFile(const MappedFile&) = delete;
    MappedFile& operator=(const MappedFile&) = delete;

    bool open(const fs::path& path, std::string& error) {
        close();
        fd_ = ::open(path.c_str(), O_RDONLY | O_CLOEXEC);
        if (fd_ < 0) {
            error = "THUNDERFORENSIC_TAR_OPEN_FAILED";
            return false;
        }
        struct stat info {};
        if (fstat(fd_, &info) != 0 || !S_ISREG(info.st_mode) || info.st_size < 0) {
            error = "THUNDERFORENSIC_TAR_OPEN_FAILED";
            close();
            return false;
        }
        size_ = static_cast<std::uint64_t>(info.st_size);
        if (size_ == 0) {
            error = "INVALID_THUNDERFORENSIC_BACKUP";
            close();
            return false;
        }
        void* mapped = mmap(nullptr, static_cast<std::size_t>(size_), PROT_READ, MAP_PRIVATE,
                            fd_, 0);
        if (mapped != MAP_FAILED) {
            map_ = static_cast<const unsigned char*>(mapped);
        }
        return true;
    }

    void close() {
        if (map_) munmap(const_cast<unsigned char*>(map_), static_cast<std::size_t>(size_));
        map_ = nullptr;
        if (fd_ >= 0) ::close(fd_);
        fd_ = -1;
        size_ = 0;
    }

    std::uint64_t size() const { return size_; }

    bool read(std::uint64_t offset, void* destination, std::size_t length) const {
        if (offset > size_ || length > size_ - offset) return false;
        if (map_) {
            std::memcpy(destination, map_ + offset, length);
            return true;
        }
        auto* out = static_cast<unsigned char*>(destination);
        std::size_t done = 0;
        while (done < length) {
            const ssize_t got = pread(fd_, out + done, length - done,
                                      static_cast<off_t>(offset + done));
            if (got <= 0) return false;
            done += static_cast<std::size_t>(got);
        }
        return true;
    }

private:
    int fd_ = -1;
    const unsigned char* map_ = nullptr;
    std::uint64_t size_ = 0;
};

struct TarHeader {
    std::string name;
    std::uint64_t size = 0;
    std::int64_t modified = 0;
    char type = '0';
};

bool parseTarHeader(const unsigned char* block, std::uint64_t blockOffset,
                    std::uint64_t containerSize, TarHeader& header, std::string& error) {
    if (!isUstarHeader(block)) {
        error = "THUNDERFORENSIC_TAR_MALFORMED";
        return false;
    }
    std::uint64_t storedChecksum = 0;
    if (!parseNumeric(block + 148, 8, storedChecksum)) {
        error = "THUNDERFORENSIC_TAR_CHECKSUM";
        return false;
    }
    std::uint64_t calculated = 32 * 8;
    for (std::size_t i = 0; i < 512; ++i) {
        if (i >= 148 && i < 156) continue;
        calculated += block[i];
    }
    if (storedChecksum != calculated) {
        error = "THUNDERFORENSIC_TAR_CHECKSUM";
        return false;
    }

    std::uint64_t size = 0;
    if (!parseNumeric(block + 124, 12, size)) {
        error = "THUNDERFORENSIC_TAR_HEADER_UNSUPPORTED";
        return false;
    }
    const std::string name = fieldString(block, 0, 100);
    const std::string prefix = fieldString(block, 345, 155);
    header.name = prefix.empty() ? name : prefix + "/" + name;
    header.size = size;
    header.type = block[156] == 0 ? '0' : static_cast<char>(block[156]);
    std::uint64_t mtime = 0;
    if (parseNumeric(block + 136, 12, mtime))
        header.modified = static_cast<std::int64_t>(mtime);

    const std::uint64_t dataOffset = blockOffset + 512;
    if (dataOffset > containerSize || size > containerSize - dataOffset) {
        error = "THUNDERFORENSIC_TAR_MALFORMED";
        return false;
    }
    return true;
}

bool readMemberData(const MappedFile& file, std::uint64_t offset, std::uint64_t size,
                    std::size_t limit, std::string& out, std::string& error) {
    if (size > limit) {
        error = "THUNDERFORENSIC_TAR_HEADER_UNSUPPORTED";
        return false;
    }
    out.resize(static_cast<std::size_t>(size));
    if (!out.empty() && !file.read(offset, out.data(), out.size())) {
        error = "THUNDERFORENSIC_TAR_MALFORMED";
        return false;
    }
    return true;
}

std::string stripTrailingNul(std::string value) {
    const auto nul = value.find('\0');
    if (nul != std::string::npos) value.resize(nul);
    return value;
}

struct PaxFields {
    std::string path;
    std::optional<std::uint64_t> size;
    bool sparse = false;
};

bool parsePaxRecord(const std::string& data, PaxFields& fields) {
    std::size_t position = 0;
    while (position < data.size()) {
        const std::size_t space = data.find(' ', position);
        if (space == std::string::npos || space == position) break;
        std::uint64_t length = 0;
        try {
            length = std::stoull(data.substr(position, space - position));
        } catch (const std::exception&) {
            break;
        }
        if (length == 0 || position + length > data.size()) break;
        std::string record = data.substr(position, static_cast<std::size_t>(length));
        if (!record.empty() && record.back() == '\n') record.pop_back();
        const std::size_t recordSpace = record.find(' ');
        if (recordSpace != std::string::npos) {
            const std::string pair = record.substr(recordSpace + 1);
            const std::size_t equals = pair.find('=');
            if (equals != std::string::npos) {
                const std::string key = pair.substr(0, equals);
                const std::string value = pair.substr(equals + 1);
                if (key == "path") fields.path = value;
                else if (key == "size" && !value.empty()) {
                    try {
                        fields.size = std::stoull(value);
                    } catch (const std::exception&) {
                    }
                } else if (key == "GNU.sparse.name" && fields.path.empty()) {
                    fields.path = value;
                } else if (key.rfind("GNU.sparse.", 0) == 0) {
                    fields.sparse = true;
                }
            }
        }
        position += static_cast<std::size_t>(length);
    }
    return true;
}

std::string deviceDisplayFromManifest(const json& manifest) {
    if (!manifest.is_object() || !manifest.contains("Device") ||
        !manifest["Device"].is_object())
        return {};
    const json& device = manifest["Device"];
    auto text = [&](const char* key) {
        if (!device.contains(key) || device[key].is_null()) return std::string{};
        if (device[key].is_string()) return device[key].get<std::string>();
        return device[key].dump();
    };
    std::string display = text("Brand");
    const std::string model = text("Model");
    if (!model.empty() && display.find(model) == std::string::npos)
        display = display.empty() ? model : display + " " + model;
    if (display.empty()) display = text("Name");
    if (display.empty()) display = text("Manufactor");
    return display;
}

bool scanHeaders(const fs::path& path, std::string* deviceBrand,
                 const std::function<bool(const std::string&, std::uint64_t, std::uint64_t,
                                          std::int64_t)>& onFile,
                 bool stopWhenMarkersFound, std::string& error) {
    MappedFile file;
    if (!file.open(path, error)) return false;
    const std::uint64_t containerSize = file.size();
    std::uint64_t offset = 0;
    std::size_t scanned = 0;
    bool sawManifest = false;
    bool sawPhoneData = false;
    std::string pendingLongName;
    PaxFields pendingPax;
    std::array<unsigned char, 512> block{};

    while (offset + 512 <= containerSize) {
        if (!file.read(offset, block.data(), block.size())) {
            error = "THUNDERFORENSIC_TAR_MALFORMED";
            return false;
        }
        if (allZero(block.data())) break;
        TarHeader header;
        if (!parseTarHeader(block.data(), offset, containerSize, header, error)) return false;
        if (++scanned > kMaxEntries) {
            error = "THUNDERFORENSIC_LIMIT_EXCEEDED";
            return false;
        }
        const std::uint64_t dataOffset = offset + 512;
        std::uint64_t effectiveSize = header.size;

        if (header.type == 'L') {
            std::string longName;
            if (!readMemberData(file, dataOffset, header.size, kMaxLongName, longName, error))
                return false;
            pendingLongName = stripTrailingNul(std::move(longName));
        } else if (header.type == 'K') {
            // Long link target: not needed for indexing.
        } else if (header.type == 'x') {
            std::string pax;
            if (!readMemberData(file, dataOffset, header.size, kMaxPaxRecord, pax, error))
                return false;
            parsePaxRecord(pax, pendingPax);
            if (pendingPax.sparse) {
                error = "THUNDERFORENSIC_TAR_SPARSE_UNSUPPORTED";
                return false;
            }
        } else if (header.type == 'g') {
            // Global PAX metadata is not needed for member names/sizes.
        } else {
            std::string name = header.name;
            if (!pendingPax.path.empty()) name = pendingPax.path;
            else if (!pendingLongName.empty()) name = pendingLongName;
            const std::uint64_t size = pendingPax.size.value_or(header.size);
            if (size > containerSize - dataOffset) {
                error = "THUNDERFORENSIC_TAR_MALFORMED";
                return false;
            }
            effectiveSize = size;
            pendingLongName.clear();
            pendingPax = {};

            if (header.type == '0' || header.type == '7') {
                if (name == kManifestMember) {
                    sawManifest = true;
                    if (deviceBrand) {
                        std::string bytes;
                        std::string readError;
                        if (size <= (8ULL << 20) &&
                            readMemberData(file, dataOffset, size, 8ULL << 20, bytes,
                                           readError)) {
                            try {
                                const json manifest = json::parse(bytes);
                                *deviceBrand = deviceDisplayFromManifest(manifest);
                            } catch (const std::exception&) {
                            }
                        }
                    }
                }
                if (name.starts_with(kPhoneDataPrefix)) sawPhoneData = true;
                if (onFile && !onFile(name, dataOffset, size, header.modified)) return false;
                if (stopWhenMarkersFound && sawManifest && sawPhoneData) return true;
            }
        }
        offset = dataOffset + roundBlocks(effectiveSize);
    }
    if (stopWhenMarkersFound && !(sawManifest && sawPhoneData)) return false;
    return true;
}

}  // namespace

namespace {

bool tarLooksLike(const fs::path& path, std::string* deviceBrand) {
    std::error_code ec;
    if (!fs::is_regular_file(path, ec) || fs::file_size(path, ec) < 1024) return false;
    // Cheap pre-filter: ThunderForensic writes plain ustar.
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    std::array<unsigned char, 512> block{};
    input.read(reinterpret_cast<char*>(block.data()), block.size());
    if (input.gcount() != static_cast<std::streamsize>(block.size()) ||
        !isUstarHeader(block.data()))
        return false;
    input.close();
    std::string error;
    return scanHeaders(path, deviceBrand, {}, true, error);
}

}  // namespace

bool thunderForensicTarLooksLike(const fs::path& path, std::string* deviceBrand) {
    return tarLooksLike(path, deviceBrand);
}

ThunderForensicBackupExtractor::ThunderForensicBackupExtractor(std::string root)
    : root_(std::move(root)) {}

bool isThunderForensicSource(const std::string& source) {
    return source == kThunderForensicSource || source == kLegacyOppoSource;
}

bool ThunderForensicBackupExtractor::recognizes(const std::string& path,
                                                std::string* deviceBrand) {
    std::error_code ec;
    const fs::path root(path);
    if (fs::is_directory(root, ec)) {
        // A ThunderForensic project directory keeps the container under
        // filesystem/1/tar; accept a tar placed directly in the folder too.
        std::vector<fs::path> directories{root / "filesystem" / "1" / "tar", root};
        for (const auto& directory : directories) {
            if (!fs::is_directory(directory, ec)) continue;
            int recognized = 0;
            std::error_code iterEc;
            for (const auto& item : fs::directory_iterator(directory, iterEc)) {
                std::error_code itemEc;
                if (!fs::is_regular_file(item.path(), itemEc)) continue;
                if (item.path().extension() != ".tar") continue;
                std::string brand;
                if (tarLooksLike(item.path(), &brand)) {
                    ++recognized;
                    if (deviceBrand && !brand.empty()) *deviceBrand = brand;
                }
                if (recognized > 16) return false;
            }
            if (recognized > 0) return true;
        }
        return false;
    }
    return tarLooksLike(root, deviceBrand);
}

void ThunderForensicBackupExtractor::setProgress(std::function<void(std::size_t)> progress,
                                                 std::function<bool()> cancelled) {
    progress_ = std::move(progress);
    cancelled_ = std::move(cancelled);
}

bool ThunderForensicBackupExtractor::resolveContainer() {
    std::error_code ec;
    std::vector<fs::path> candidates;
    if (fs::is_directory(root_, ec)) {
        const fs::path tarDir = root_ / "filesystem" / "1" / "tar";
        auto collect = [&](const fs::path& directory) {
            if (!fs::is_directory(directory, ec)) return;
            std::error_code iterEc;
            for (const auto& item : fs::directory_iterator(directory, iterEc)) {
                std::error_code itemEc;
                if (fs::is_regular_file(item.path(), itemEc) &&
                    item.path().extension() == ".tar")
                    candidates.push_back(item.path());
            }
        };
        collect(tarDir);
        if (candidates.empty()) collect(root_);
        std::vector<fs::path> recognized;
        for (const auto& candidate : candidates) {
            if (tarLooksLike(candidate, nullptr)) recognized.push_back(candidate);
            if (recognized.size() > 16) break;
        }
        if (recognized.empty()) {
            error_ = "INVALID_THUNDERFORENSIC_BACKUP";
            return false;
        }
        if (recognized.size() > 1) {
            error_ = "AMBIGUOUS_THUNDERFORENSIC_CONTAINER";
            return false;
        }
        container_ = recognized.front();
        projectRoot_ = root_;
    } else if (fs::is_regular_file(root_, ec)) {
        if (!tarLooksLike(root_, nullptr)) {
            error_ = "INVALID_THUNDERFORENSIC_BACKUP";
            return false;
        }
        container_ = root_;
        projectRoot_.clear();
    } else {
        error_ = "INVALID_THUNDERFORENSIC_BACKUP";
        return false;
    }
    if (fs::is_symlink(fs::symlink_status(container_, ec))) {
        error_ = "INVALID_THUNDERFORENSIC_BACKUP";
        return false;
    }
    containerSize_ = fs::file_size(container_, ec);
    containerTime_ = fs::last_write_time(container_, ec).time_since_epoch().count();
    return true;
}

bool ThunderForensicBackupExtractor::indexTar(const fs::path& tarPath) {
    std::size_t duplicates = 0;
    const bool ok = scanHeaders(
        tarPath, nullptr,
        [&](const std::string& name, std::uint64_t offset, std::uint64_t size,
            std::int64_t modified) {
            if (cancelled_ && cancelled_()) {
                error_ = "CANCELLED";
                return false;
            }
            if (entries_.size() >= kMaxEntries) {
                error_ = "THUNDERFORENSIC_LIMIT_EXCEEDED";
                return false;
            }
            Entry entry;
            entry.path = name;
            entry.offset = offset;
            entry.size = size;
            entry.modified = modified;
            const auto [_, inserted] = entries_.emplace(entry.path, std::move(entry));
            if (!inserted) {
                // ThunderForensic can emit the same app-data path more than
                // once. Keep the first occurrence (the one the index resolves
                // by name) and account for the rest in coverage.
                ++duplicates;
                return true;
            }
            if (progress_ && entries_.size() % 256 == 0) progress_(entries_.size());
            return true;
        },
        false, error_);
    if (!ok) {
        if (error_.empty()) error_ = "THUNDERFORENSIC_TAR_MALFORMED";
        return false;
    }
    if (entries_.empty()) {
        error_ = "INVALID_THUNDERFORENSIC_BACKUP";
        return false;
    }
    duplicateMembers_ = duplicates;
    return true;
}

bool ThunderForensicBackupExtractor::initialize() {
    entries_.clear();
    used_.clear();
    projectRoot_.clear();
    manifest_ = json::object();
    deviceBrand_.clear();
    containerSha256_.clear();
    containerHashStatus_.clear();
    duplicateMembers_ = 0;
    error_.clear();
    try {
        root_ = fs::absolute(root_).lexically_normal();
        if (!resolveContainer()) return false;
        if (!indexTar(container_)) return false;
        if (!loadManifest()) return false;
        if (progress_) progress_(entries_.size());
        return true;
    } catch (const std::exception& e) {
        error_ = e.what();
        return false;
    }
}

bool ThunderForensicBackupExtractor::loadManifest() {
    const auto found = entries_.find(kManifestMember);
    if (found == entries_.end()) {
        error_ = "THUNDERFORENSIC_MANIFEST_MISSING";
        return false;
    }
    std::string bytes;
    if (!readMemberBytes(kManifestMember, bytes, 8ULL << 20)) {
        error_ = "THUNDERFORENSIC_MANIFEST_UNREADABLE";
        return false;
    }
    try {
        manifest_ = json::parse(bytes);
    } catch (const std::exception&) {
        error_ = "THUNDERFORENSIC_MANIFEST_PARSE_FAILED";
        return false;
    }
    if (!manifest_.is_object() || !manifest_.contains("Device") ||
        !manifest_["Device"].is_object()) {
        error_ = "THUNDERFORENSIC_MANIFEST_SCHEMA_UNSUPPORTED";
        return false;
    }
    deviceBrand_ = deviceDisplayFromManifest(manifest_);
    manifest_["platform"] = "Android";
    manifest_["adapter_version"] = kAdapterVersion;
    manifest_["container"] = container_.filename().string();
    manifest_["container_size"] = containerSize_;
    manifest_["duplicate_members"] = duplicateMembers_;
    if (containerSize_ <= kFullHashLimit) {
        containerSha256_ = sha256(container_, cancelled_);
        if (containerSha256_.empty()) {
            containerHashStatus_ = (cancelled_ && cancelled_())
                ? "cancelled" : "hash_failed";
        } else {
            containerHashStatus_ = "sha256";
        }
    } else {
        containerHashStatus_ = "not_computed_large_container";
    }
    manifest_["container_sha256"] = containerSha256_;
    manifest_["container_sha256_status"] = containerHashStatus_;
    // Re-record the manifest now that the container digest is known.
    recordManifestProvenance(found->second,
                             sha256Bytes(bytes));
    return true;
}

std::string ThunderForensicBackupExtractor::sha256Bytes(const std::string& bytes) {
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned size = 0;
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),
                                                                    EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(context.get(), bytes.data(), bytes.size()) != 1 ||
        EVP_DigestFinal_ex(context.get(), digest, &size) != 1)
        return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned i = 0; i < size; ++i) out << std::setw(2) << unsigned(digest[i]);
    return out.str();
}

std::string ThunderForensicBackupExtractor::sha256(const fs::path& path,
                                                   const std::function<bool()>& cancelled) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),
                                                                    EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1) return {};
    std::vector<char> buffer(4ULL << 20);
    while (input) {
        if (cancelled && cancelled()) return {};
        input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
        if (input.gcount() &&
            EVP_DigestUpdate(context.get(), buffer.data(),
                             static_cast<std::size_t>(input.gcount())) != 1)
            return {};
    }
    if (input.bad()) return {};
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned size = 0;
    if (EVP_DigestFinal_ex(context.get(), digest, &size) != 1) return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned i = 0; i < size; ++i) out << std::setw(2) << unsigned(digest[i]);
    return out.str();
}

bool ThunderForensicBackupExtractor::readMemberBytes(const std::string& path, std::string& out,
                                                     std::uint64_t maxBytes) {
    std::string key = path.starts_with('/') ? path.substr(1) : path;
    const auto found = entries_.find(key);
    if (found == entries_.end() || found->second.size > maxBytes) return false;
    std::ifstream input(container_, std::ios::binary);
    if (!input) return false;
    input.seekg(static_cast<std::streamoff>(found->second.offset));
    if (!input) return false;
    out.resize(static_cast<std::size_t>(found->second.size));
    input.read(out.data(), static_cast<std::streamsize>(out.size()));
    if (input.gcount() != static_cast<std::streamsize>(out.size())) return false;
    const std::string digest = sha256Bytes(out);
    if (!digest.empty()) {
        if (!manifest_.is_null() && manifest_.is_object())
            recordProvenance(found->second, digest);
    }
    return true;
}

void ThunderForensicBackupExtractor::recordProvenance(const Entry& entry,
                                                      const std::string& memberSha256) {
    used_[entry.path] = {container_.string(),
                         manifest_.value("container_sha256", ""),
                         entry.path,
                         entry.path,
                         static_cast<std::size_t>(entry.size),
                         memberSha256,
                         kThunderForensicSource,
                         kAdapterVersion};
}

void ThunderForensicBackupExtractor::recordManifestProvenance(
    const Entry& entry, const std::string& memberSha256) {
    if (memberSha256.empty()) return;
    recordProvenance(entry, memberSha256);
}

bool ThunderForensicBackupExtractor::extractFileByPath(const std::string& path,
                                                       const std::string& output) {
    try {
        std::string key = path.starts_with('/') ? path.substr(1) : path;
        const auto found = entries_.find(key);
        if (found == entries_.end()) return false;
        const auto& entry = found->second;
        std::error_code ec;
        if (fs::file_size(container_, ec) != containerSize_ ||
            fs::last_write_time(container_, ec).time_since_epoch().count() != containerTime_) {
            error_ = "EVIDENCE_CHANGED_AFTER_INDEX";
            return false;
        }
        // Never write back into the evidence itself.
        const fs::path dest = fs::absolute(output).lexically_normal();
        const auto relative = fs::weakly_canonical(dest).lexically_relative(
            fs::weakly_canonical(root_));
        if (!relative.empty() && *relative.begin() != "..") return false;
        if (fs::is_symlink(fs::symlink_status(dest, ec))) return false;
        fs::create_directories(dest.parent_path());
        std::ifstream input(container_, std::ios::binary);
        if (!input) return false;
        input.seekg(static_cast<std::streamoff>(entry.offset));
        if (!input) return false;
        std::ofstream out(dest, std::ios::binary | std::ios::trunc);
        if (!out) return false;
        std::array<char, 1 << 16> buffer{};
        std::uint64_t left = entry.size;
        while (left) {
            if (cancelled_ && cancelled_()) {
                error_ = "CANCELLED";
                return false;
            }
            const auto chunk = static_cast<std::streamsize>(
                std::min<std::uint64_t>(left, buffer.size()));
            input.read(buffer.data(), chunk);
            if (input.gcount() != chunk) {
                error_ = "SHORT_THUNDERFORENSIC_READ";
                return false;
            }
            out.write(buffer.data(), chunk);
            if (!out) {
                error_ = "THUNDERFORENSIC_OUTPUT_FAILED";
                return false;
            }
            left -= static_cast<std::uint64_t>(chunk);
        }
        out.close();
        if (!out) return false;
        recordProvenance(entry, sha256(dest));
        if (progress_) progress_(used_.size());
        return true;
    } catch (const std::exception& e) {
        error_ = e.what();
        return false;
    }
}

std::vector<std::string> ThunderForensicBackupExtractor::findPathsByFilename(
    const std::string& filename, std::size_t limit) const {
    std::vector<std::string> out;
    for (const auto& [path, entry] : entries_) {
        if (out.size() >= limit) break;
        if (fs::path(path).filename() == filename) out.push_back(path);
    }
    return out;
}

std::vector<AndroidSourceProvenance> ThunderForensicBackupExtractor::usedSourceProvenance()
    const {
    std::vector<AndroidSourceProvenance> result;
    for (const auto& [_, provenance] : used_) result.push_back(provenance);
    return result;
}
