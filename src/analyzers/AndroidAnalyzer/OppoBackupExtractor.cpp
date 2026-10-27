#include "OppoBackupExtractor.h"
#include <archive.h>
#include <archive_entry.h>
#include <openssl/evp.h>
#include <algorithm>
#include <array>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {
constexpr std::uint64_t kMaxMember = 8ULL << 30;
constexpr std::size_t kMaxEntries = 500000;
// The recognition scan walks header blocks only (data is skipped by seek),
// but cap it anyway so a corrupt adversarial container cannot spin forever.
constexpr std::size_t kRecognitionMemberLimit = 200000;
constexpr const char* kManifestMember = "ThunderForensic.json";
constexpr const char* kPhoneDataPrefix = "PhoneData/";
constexpr const char* kAdapterVersion = "oppo-thunderforensic-v1";

bool isUstarHeader(const unsigned char* block) {
    static const unsigned char magic[5] = {'u', 's', 't', 'a', 'r'};
    return std::equal(magic, magic + 5, block + 257);
}

// Opens a plain tar and reports whether its member window carries the
// ThunderForensic markers. Header reads only; entries are skipped by seek.
bool scanTarForMarkers(const fs::path& path) {
    std::unique_ptr<archive, decltype(&archive_read_free)> reader(archive_read_new(),
                                                                  archive_read_free);
    if (!reader) return false;
    archive_read_support_format_tar(reader.get());
    archive_read_support_filter_none(reader.get());
    if (archive_read_open_filename(reader.get(), path.string().c_str(), 65536) != ARCHIVE_OK)
        return false;
    archive_entry* item = nullptr;
    bool sawManifest = false, sawPhoneData = false;
    std::size_t scanned = 0;
    int rc;
    while ((rc = archive_read_next_header(reader.get(), &item)) == ARCHIVE_OK) {
        if (++scanned > kRecognitionMemberLimit) return false;
        const char* name = archive_entry_pathname(item);
        if (name) {
            if (!sawManifest && std::string_view(name) == kManifestMember) sawManifest = true;
            if (!sawPhoneData && std::string_view(name).starts_with(kPhoneDataPrefix))
                sawPhoneData = true;
        }
        if (sawManifest && sawPhoneData) return true;
        if (archive_read_data_skip(reader.get()) != ARCHIVE_OK) return false;
    }
    return false;
}
}  // namespace

bool oppoTarLooksLikeThunderForensic(const fs::path& path) {
    std::error_code ec;
    if (!fs::is_regular_file(path, ec) || fs::file_size(path, ec) < 1024) return false;
    // Cheap pre-filter: only containers that claim ustar reach the scan.
    std::ifstream in(path, std::ios::binary);
    if (!in) return false;
    std::array<unsigned char, 512> block{};
    in.read(reinterpret_cast<char*>(block.data()), block.size());
    if (in.gcount() != static_cast<std::streamsize>(block.size()) || !isUstarHeader(block.data()))
        return false;
    in.close();
    return scanTarForMarkers(path);
}

OppoBackupExtractor::OppoBackupExtractor(std::string root) : root_(std::move(root)) {}

bool OppoBackupExtractor::recognizes(const std::string& path) {
    std::error_code ec;
    const fs::path p(path);
    if (fs::is_directory(p, ec)) {
        const fs::path tarDir = p / "filesystem" / "1" / "tar";
        if (!fs::is_directory(tarDir, ec)) return false;
        int candidates = 0;
        for (const auto& item : fs::directory_iterator(tarDir, ec)) {
            if (candidates > 16) return false;
            if (oppoTarLooksLikeThunderForensic(item.path())) ++candidates;
        }
        return candidates > 0;
    }
    return oppoTarLooksLikeThunderForensic(p);
}

void OppoBackupExtractor::setProgress(std::function<void(std::size_t)> progress,
                                      std::function<bool()> cancelled) {
    progress_ = std::move(progress);
    cancelled_ = std::move(cancelled);
}

bool OppoBackupExtractor::indexTar(const fs::path& tarPath) {
    std::unique_ptr<archive, decltype(&archive_read_free)> reader(archive_read_new(),
                                                                  archive_read_free);
    if (!reader) return false;
    archive_read_support_format_tar(reader.get());
    archive_read_support_filter_none(reader.get());
    if (archive_read_open_filename(reader.get(), tarPath.string().c_str(), 65536) != ARCHIVE_OK) {
        error_ = "OPPO_TAR_OPEN_FAILED";
        return false;
    }
    archive_entry* item = nullptr;
    int rc;
    while ((rc = archive_read_next_header(reader.get(), &item)) == ARCHIVE_OK) {
        if (cancelled_ && cancelled_()) {
            error_ = "CANCELLED";
            return false;
        }
        if (archive_entry_filetype(item) != AE_IFREG || archive_entry_symlink(item) ||
            archive_entry_hardlink(item)) {
            archive_read_data_skip(reader.get());
            continue;
        }
        const char* raw = archive_entry_pathname(item);
        if (!raw || !archive_entry_size_is_set(item) || archive_entry_size(item) < 0) {
            error_ = "OPPO_TAR_MEMBER_UNNAMED";
            return false;
        }
        // libarchive reports the data offset after any GNU/PAX header bytes;
        // the container must stay untouched for these offsets to remain valid.
        const auto offset = archive_filter_bytes(reader.get(), 0);
        if (offset < 0) {
            error_ = "OPPO_TAR_OFFSET_UNAVAILABLE";
            return false;
        }
        Entry entry;
        entry.path = raw;
        entry.offset = static_cast<std::uint64_t>(offset);
        entry.size = static_cast<std::uint64_t>(archive_entry_size(item));
        entry.modified = archive_entry_mtime(item);
        if (entry.size > kMaxMember || entries_.size() >= kMaxEntries) {
            error_ = "OPPO_LIMIT_EXCEEDED";
            return false;
        }
        const auto [_, inserted] = entries_.emplace(entry.path, std::move(entry));
        if (!inserted) {
            error_ = "OPPO_DUPLICATE_MEMBER";
            return false;
        }
        if (progress_ && entries_.size() % 256 == 0) progress_(entries_.size());
        if (archive_read_data_skip(reader.get()) != ARCHIVE_OK) {
            error_ = "OPPO_TAR_SKIP_FAILED";
            return false;
        }
    }
    if (rc != ARCHIVE_EOF) {
        error_ = "OPPO_TAR_MALFORMED";
        return false;
    }
    return !entries_.empty();
}

bool OppoBackupExtractor::initialize() {
    entries_.clear();
    used_.clear();
    error_.clear();
    try {
        root_ = fs::absolute(root_).lexically_normal();
        std::error_code ec;
        if (fs::is_directory(root_, ec)) {
            const fs::path tarDir = root_ / "filesystem" / "1" / "tar";
            std::vector<fs::path> recognized;
            std::error_code iterEc;
            for (const auto& item : fs::directory_iterator(tarDir, iterEc)) {
                if (oppoTarLooksLikeThunderForensic(item.path())) recognized.push_back(item.path());
            }
            if (recognized.empty()) {
                error_ = "INVALID_OPPO_BACKUP";
                return false;
            }
            if (recognized.size() > 1) {
                error_ = "AMBIGUOUS_OPPO_CONTAINER";
                return false;
            }
            container_ = recognized.front();
        } else if (fs::is_regular_file(root_, ec)) {
            if (!oppoTarLooksLikeThunderForensic(root_)) {
                error_ = "INVALID_OPPO_BACKUP";
                return false;
            }
            container_ = root_;
        } else {
            error_ = "INVALID_OPPO_BACKUP";
            return false;
        }
        if (fs::is_symlink(fs::symlink_status(container_, ec))) {
            error_ = "INVALID_OPPO_BACKUP";
            return false;
        }
        containerSize_ = fs::file_size(container_, ec);
        containerTime_ = fs::last_write_time(container_, ec).time_since_epoch().count();
        if (!indexTar(container_)) return false;
        if (!loadManifest()) return false;
        if (progress_) progress_(entries_.size());
        return true;
    } catch (const std::exception& e) {
        error_ = e.what();
        return false;
    }
}

bool OppoBackupExtractor::loadManifest() {
    std::string bytes;
    if (!readMemberBytes(kManifestMember, bytes, 8ULL << 20)) {
        error_ = "OPPO_MANIFEST_UNREADABLE";
        return false;
    }
    try {
        manifest_ = json::parse(bytes);
    } catch (const std::exception&) {
        error_ = "OPPO_MANIFEST_PARSE_FAILED";
        return false;
    }
    if (!manifest_.is_object() || !manifest_.contains("Device")) {
        error_ = "OPPO_MANIFEST_SCHEMA_UNSUPPORTED";
        return false;
    }
    manifest_["platform"] = "Android";
    manifest_["adapter_version"] = kAdapterVersion;
    manifest_["container"] = container_.filename().string();
    manifest_["container_sha256"] = sha256(container_);
    return true;
}

std::string OppoBackupExtractor::sha256(const fs::path& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return {};
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),
                                                                    EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1) return {};
    std::array<char, 1 << 20> buffer{};
    while (f) {
        f.read(buffer.data(), buffer.size());
        if (f.gcount() && EVP_DigestUpdate(context.get(), buffer.data(), f.gcount()) != 1) return {};
    }
    if (f.bad()) return {};
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned size = 0;
    if (EVP_DigestFinal_ex(context.get(), digest, &size) != 1) return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned i = 0; i < size; ++i) out << std::setw(2) << unsigned(digest[i]);
    return out.str();
}

bool OppoBackupExtractor::readMemberBytes(const std::string& path, std::string& out,
                                          std::uint64_t maxBytes) {
    std::string key = path.starts_with('/') ? path.substr(1) : path;
    const auto found = entries_.find(key);
    if (found == entries_.end() || found->second.size > maxBytes) return false;
    std::ifstream in(container_, std::ios::binary);
    if (!in) return false;
    in.seekg(static_cast<std::streamoff>(found->second.offset));
    if (!in) return false;
    out.resize(found->second.size);
    in.read(out.data(), static_cast<std::streamsize>(out.size()));
    return in.gcount() == static_cast<std::streamsize>(out.size());
}

void OppoBackupExtractor::recordProvenance(const Entry& entry, const std::string& memberSha256) {
    used_[entry.path] = {container_.string(), manifest_.value("container_sha256", ""),
                         entry.path, entry.path, static_cast<std::size_t>(entry.size),
                         memberSha256, "oppo-backup", "oppo-thunderforensic-v1"};
}

bool OppoBackupExtractor::extractFileByPath(const std::string& path, const std::string& output) {
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
        std::ifstream in(container_, std::ios::binary);
        if (!in) return false;
        in.seekg(static_cast<std::streamoff>(entry.offset));
        if (!in) return false;
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
            in.read(buffer.data(), chunk);
            if (in.gcount() != chunk) {
                error_ = "SHORT_OPPO_READ";
                return false;
            }
            out.write(buffer.data(), chunk);
            if (!out) {
                error_ = "OPPO_OUTPUT_FAILED";
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

std::vector<std::string> OppoBackupExtractor::findPathsByFilename(const std::string& filename,
                                                                  std::size_t limit) const {
    std::vector<std::string> out;
    for (const auto& [path, entry] : entries_) {
        if (out.size() >= limit) break;
        if (fs::path(path).filename() == filename) out.push_back(path);
    }
    return out;
}

std::vector<AndroidSourceProvenance> OppoBackupExtractor::usedSourceProvenance() const {
    std::vector<AndroidSourceProvenance> result;
    for (const auto& [_, provenance] : used_) result.push_back(provenance);
    return result;
}
