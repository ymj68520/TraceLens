#include "ArchiveFileExtractor.h"
#include "AndroidBackupStream.h"

#include <archive.h>
#include <archive_entry.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>

#include <algorithm>
#include <cctype>
#include <array>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <memory>
#include <sstream>
#include <unordered_map>

namespace fs = std::filesystem;

namespace {
constexpr std::size_t kMaxMembers = 100000;
constexpr std::uint64_t kMaxMemberBytes = 8ULL * 1024 * 1024 * 1024;
constexpr std::uint64_t kMaxExpandedBytes = 2ULL * 1024 * 1024 * 1024 * 1024;
constexpr std::uint64_t kMaxExpansionRatio = 1000;
constexpr const char* kAdapterVersion = "archive-logical-v1";

struct Reader {
    struct archive* handle = nullptr;
    std::unique_ptr<AndroidBackupStream> backup;
    ~Reader() { if (handle) archive_read_free(handle); }
};

std::string hexDigest(const unsigned char* data, std::size_t length) {
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < length; ++i) out << std::setw(2) << static_cast<int>(data[i]);
    return out.str();
}

std::string fileSha256(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) return {};
    std::array<char, 1 << 20> bytes{};
    unsigned char digest[EVP_MAX_MD_SIZE]{};
    unsigned int length = 0;
    bool ok = EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr) == 1;
    while (ok && input) {
        input.read(bytes.data(), bytes.size());
        const auto size = input.gcount();
        if (size > 0) ok = EVP_DigestUpdate(ctx, bytes.data(), static_cast<std::size_t>(size)) == 1;
    }
    ok = ok && !input.bad() && EVP_DigestFinal_ex(ctx, digest, &length) == 1;
    EVP_MD_CTX_free(ctx);
    return ok ? hexDigest(digest, length) : std::string();
}

std::unique_ptr<Reader> openReader(const std::string& source, AndroidArchiveKind kind,
                                   const std::string& password, std::string& error) {
    auto reader = std::make_unique<Reader>();
    reader->handle = archive_read_new();
    if (!reader->handle) { error = "ARCHIVE_INIT_FAILED"; return {}; }
    if (kind == AndroidArchiveKind::SevenZip) {
        archive_read_support_format_7zip(reader->handle);
        archive_read_support_filter_all(reader->handle);
        if (!password.empty() && archive_read_add_passphrase(reader->handle, password.c_str()) != ARCHIVE_OK) {
            error = "UNSUPPORTED_ARCHIVE_VARIANT"; return {};
        }
    } else {
        archive_read_support_format_tar(reader->handle);
        if (kind == AndroidArchiveKind::Tar) {
            archive_read_support_filter_gzip(reader->handle);
            archive_read_support_filter_xz(reader->handle);
            archive_read_support_filter_none(reader->handle);
        } else {
            archive_read_support_filter_none(reader->handle);
        }
    }
    int opened = ARCHIVE_FATAL;
    if (kind == AndroidArchiveKind::AndroidBackup) {
        reader->backup = AndroidBackupStream::open(source, password, error);
        if (!reader->backup) return {};
        opened = reader->backup->attach(reader->handle) ? ARCHIVE_OK : ARCHIVE_FATAL;
    } else {
        opened = archive_read_open_filename(reader->handle, source.c_str(), 1 << 16);
    }
    if (opened != ARCHIVE_OK) {
        if (error.empty()) {
            const char* raw = archive_error_string(reader->handle);
            std::string detail = raw ? raw : "";
            std::transform(detail.begin(), detail.end(), detail.begin(),
                           [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
            const bool locked = detail.find("passphrase") != std::string::npos ||
                                detail.find("password") != std::string::npos ||
                                detail.find("encrypted") != std::string::npos;
            error = kind == AndroidArchiveKind::AndroidBackup ? "MALFORMED_BACKUP" :
                    kind == AndroidArchiveKind::SevenZip && locked
                        ? (password.empty() ? "LOCKED_ARCHIVE" :
                           detail.find("not currently supported") != std::string::npos ||
                           detail.find("unsupported") != std::string::npos
                               ? "UNSUPPORTED_ARCHIVE_VARIANT" : "LOCKED_ARCHIVE")
                        : "MALFORMED_ARCHIVE";
        }
        return {};
    }
    return reader;
}

bool expectedFormat(struct archive* reader, AndroidArchiveKind kind) {
    const int format = archive_format(reader);
    return kind == AndroidArchiveKind::SevenZip
        ? format == ARCHIVE_FORMAT_7ZIP
        : (format & ARCHIVE_FORMAT_BASE_MASK) == ARCHIVE_FORMAT_TAR;
}
} // namespace

ArchiveFileExtractor::ArchiveFileExtractor(std::string source, AndroidArchiveKind kind,
                                           std::string password)
    : source_(std::move(source)), kind_(kind), password_(std::move(password)),
      passwordSupplied_(!password_.empty()) {}

ArchiveFileExtractor::~ArchiveFileExtractor() {
    if (!password_.empty()) OPENSSL_cleanse(password_.data(), password_.size());
}

bool ArchiveFileExtractor::initialize() {
    initialized_ = false;
    members_.clear();
    used_.clear();
    coverage_.clear();
    errorCode_.clear();
    mapping_ = {};
    memberCount_ = skippedLinks_ = 0;
    std::error_code ec;
    if (!fs::is_regular_file(source_, ec) || ec) { errorCode_ = "SOURCE_NOT_REGULAR_FILE"; return false; }
    const auto sourceBytes = fs::file_size(source_, ec);
    if (ec || sourceBytes == 0) { errorCode_ = "MALFORMED_ARCHIVE"; return false; }
    containerSha256_ = fileSha256(source_);
    if (containerSha256_.empty()) { errorCode_ = "SOURCE_HASH_FAILED"; return false; }
    auto reader = openReader(source_, kind_, password_, errorCode_);
    if (!reader) return false;

    std::vector<std::string> regular;
    std::unordered_map<std::string, std::uint64_t> rawSizes;
    std::uint64_t expanded = 0;
    struct archive_entry* entry = nullptr;
    int status;
    while ((status = archive_read_next_header(reader->handle, &entry)) == ARCHIVE_OK) {
        if (!expectedFormat(reader->handle, kind_)) { errorCode_ = "UNSUPPORTED_ARCHIVE_VARIANT"; return false; }
        if (++memberCount_ > kMaxMembers) { errorCode_ = "RISK_REJECTED: member_count"; return false; }
        const char* raw = archive_entry_pathname_utf8(entry);
        if (!raw) raw = archive_entry_pathname(entry);
        if (!raw) { errorCode_ = "RISK_REJECTED: missing_member_path"; return false; }
        std::string cleaned, reason;
        if (!AndroidPathMapper::safeMemberPath(raw, cleaned, reason)) {
            errorCode_ = "RISK_REJECTED: " + reason;
            return false;
        }
        if (archive_entry_filetype(entry) != AE_IFREG || archive_entry_hardlink(entry) ||
            archive_entry_symlink(entry)) {
            if (archive_entry_hardlink(entry) || archive_entry_symlink(entry)) ++skippedLinks_;
            archive_read_data_skip(reader->handle);
            continue;
        }
        if (!archive_entry_size_is_set(entry) || archive_entry_size(entry) < 0 ||
            static_cast<std::uint64_t>(archive_entry_size(entry)) > kMaxMemberBytes) {
            errorCode_ = "RISK_REJECTED: member_size"; return false;
        }
        const auto size = static_cast<std::uint64_t>(archive_entry_size(entry));
        if (size > kMaxExpandedBytes - expanded) { errorCode_ = "RISK_REJECTED: total_expanded_size"; return false; }
        expanded += size;
        regular.emplace_back(raw);
        if (!rawSizes.emplace(raw, size).second) { errorCode_ = "RISK_REJECTED: duplicate_member"; return false; }
        if (archive_read_data_skip(reader->handle) < ARCHIVE_OK) {
            errorCode_ = kind_ == AndroidArchiveKind::AndroidBackup ? "MALFORMED_BACKUP" :
                         kind_ == AndroidArchiveKind::SevenZip &&
                         archive_read_has_encrypted_entries(reader->handle) > 0
                             ? (password_.empty() ? "LOCKED_ARCHIVE" : "UNSUPPORTED_ARCHIVE_VARIANT")
                             : "MALFORMED_ARCHIVE";
            return false;
        }
    }
    if (status != ARCHIVE_EOF) {
        const char* message = archive_error_string(reader->handle);
        std::string detail = message ? message : "";
        std::transform(detail.begin(), detail.end(), detail.begin(),
                       [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
        if (kind_ == AndroidArchiveKind::SevenZip &&
            (detail.find("passphrase") != std::string::npos ||
             detail.find("password") != std::string::npos ||
             detail.find("encrypted") != std::string::npos))
            errorCode_ = password_.empty() ? "LOCKED_ARCHIVE" :
                detail.find("unsupported") != std::string::npos ||
                detail.find("not currently supported") != std::string::npos
                    ? "UNSUPPORTED_ARCHIVE_VARIANT" : "LOCKED_ARCHIVE";
        else errorCode_ = kind_ == AndroidArchiveKind::AndroidBackup
                              ? "MALFORMED_BACKUP" : "MALFORMED_ARCHIVE";
        return false;
    }
    if (reader->backup && !reader->backup->finish()) {
        errorCode_ = "MALFORMED_BACKUP";
        return false;
    }
    if (kind_ == AndroidArchiveKind::SevenZip && password_.empty() &&
        archive_read_has_encrypted_entries(reader->handle) > 0) {
        errorCode_ = "LOCKED_ARCHIVE";
        return false;
    }
    if (sourceBytes < kMaxExpandedBytes / kMaxExpansionRatio &&
        expanded > sourceBytes * kMaxExpansionRatio &&
        expanded > 16ULL * 1024 * 1024) {
        errorCode_ = "RISK_REJECTED: expansion_ratio"; return false;
    }
    mapping_ = AndroidPathMapper::build(regular, kind_ == AndroidArchiveKind::AndroidBackup);
    if (!mapping_.valid) {
        errorCode_ = mapping_.reason == "no_demonstrable_android_root"
                         ? "UNSUPPORTED_ANDROID_ROOT" : mapping_.reason;
        return false;
    }
    if (fileSha256(source_) != containerSha256_) {
        errorCode_ = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
        return false;
    }
    for (const auto& [normalized, raw] : mapping_.normalizedToMember)
        members_.emplace(normalized, Member{raw, rawSizes.at(raw)});
    initialized_ = true;
    return true;
}

bool ArchiveFileExtractor::extractFileByPath(const std::string& androidRelativePath,
                                             const std::string& outPath) {
    std::string normalized;
    if (!initialized_ || !AndroidPathMapper::normalizeRequest(androidRelativePath, normalized)) return false;
    const auto hit = members_.find(normalized);
    if (hit == members_.end()) {
        coverage_[normalized] = ArchiveCoverageEvent{source_, normalized, "NOT_FOUND", "normalized path absent from container inventory"};
        return false;
    }
    std::string openError;
    auto reader = openReader(source_, kind_, password_, openError);
    if (!reader) {
        errorCode_ = openError;
        coverage_[normalized] = ArchiveCoverageEvent{hit->second.sourcePath, normalized, "EXTRACT_FAILED", openError};
        return false;
    }
    struct archive_entry* entry = nullptr;
    int status;
    while ((status = archive_read_next_header(reader->handle, &entry)) == ARCHIVE_OK) {
        const char* raw = archive_entry_pathname_utf8(entry);
        if (!raw) raw = archive_entry_pathname(entry);
        if (!raw || hit->second.sourcePath != raw) {
            archive_read_data_skip(reader->handle);
            continue;
        }
        if (archive_entry_filetype(entry) != AE_IFREG || archive_entry_hardlink(entry) ||
            archive_entry_symlink(entry)) return false;
        const fs::path target(outPath);
        std::error_code ec;
        fs::create_directories(target.parent_path(), ec);
        if (ec || fs::is_symlink(fs::symlink_status(target, ec))) return false;
        const fs::path temporary = target.string() + ".archive-partial";
        std::ofstream output(temporary, std::ios::binary | std::ios::trunc);
        if (!output) return false;
        EVP_MD_CTX* digestContext = EVP_MD_CTX_new();
        if (!digestContext) { output.close(); fs::remove(temporary, ec); return false; }
        bool okay = EVP_DigestInit_ex(digestContext, EVP_sha256(), nullptr) == 1;
        std::array<char, 1 << 16> buffer{};
        std::uint64_t written = 0;
        la_ssize_t amount = 0;
        while (okay && (amount = archive_read_data(reader->handle, buffer.data(), buffer.size())) > 0) {
            if (static_cast<std::uint64_t>(amount) > kMaxMemberBytes - written) { okay = false; break; }
            output.write(buffer.data(), static_cast<std::streamsize>(amount));
            written += static_cast<std::uint64_t>(amount);
            okay = output.good() && EVP_DigestUpdate(digestContext, buffer.data(), static_cast<std::size_t>(amount)) == 1;
        }
        if (amount < 0 || written != hit->second.size) okay = false;
        unsigned char digest[EVP_MAX_MD_SIZE]{};
        unsigned int length = 0;
        okay = okay && EVP_DigestFinal_ex(digestContext, digest, &length) == 1;
        EVP_MD_CTX_free(digestContext);
        output.close();
        if (!output.good()) okay = false;
        if (!okay) {
            fs::remove(temporary, ec); errorCode_ = "EXTRACT_FAILED";
            coverage_[normalized] = ArchiveCoverageEvent{hit->second.sourcePath, normalized, "EXTRACT_FAILED", "member bytes could not be staged"};
            return false;
        }
        fs::rename(temporary, target, ec);
        if (ec) { fs::remove(temporary, ec); errorCode_ = "EXTRACT_FAILED"; return false; }
        used_.push_back(AndroidSourceProvenance{
            source_, containerSha256_, hit->second.sourcePath, normalized,
            static_cast<std::size_t>(written), hexDigest(digest, length),
            kind_ == AndroidArchiveKind::Tar ? "tar" :
            kind_ == AndroidArchiveKind::SevenZip ? "seven-zip" : "android-backup",
            kAdapterVersion});
        coverage_[normalized] = ArchiveCoverageEvent{hit->second.sourcePath, normalized, "FOUND", "source bytes staged"};
        return true;
    }
    errorCode_ = "EXTRACT_FAILED";
    return false;
}

std::vector<std::string> ArchiveFileExtractor::findPathsByFilename(
    const std::string& filename, std::size_t limit) const {
    std::vector<std::string> found;
    if (!initialized_ || filename.empty() || limit == 0) return found;
    for (const auto& [path, member] : members_) {
        (void)member;
        if (fs::path(path).filename() == filename) {
            found.push_back(path);
            if (found.size() >= limit) break;
        }
    }
    return found;
}

std::optional<std::uint64_t> ArchiveFileExtractor::statMember(
    const std::string& normalizedPath) const {
    const auto found = members_.find(normalizedPath);
    if (found == members_.end()) return std::nullopt;
    return found->second.size;
}

std::vector<AndroidSourceProvenance> ArchiveFileExtractor::usedSourceProvenance() const {
    return used_;
}

std::vector<ArchiveCoverageEvent> ArchiveFileExtractor::coverageEvents() const {
    std::vector<ArchiveCoverageEvent> out;
    out.reserve(coverage_.size());
    for (const auto& [path, event] : coverage_) { (void)path; out.push_back(event); }
    return out;
}
