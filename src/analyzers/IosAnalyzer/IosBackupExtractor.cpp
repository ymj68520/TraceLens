#include "IosBackupExtractor.h"
#include "BinaryPlist.h"

#include <openssl/evp.h>
#include <sqlite3.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>

namespace fs = std::filesystem;

namespace {

constexpr const char* kAdapterType = "ios-backup";
constexpr const char* kAdapterVersion = "ios-backup-v1";
constexpr std::size_t kMaxIndexEntries = 2'000'000;
constexpr std::size_t kCopyChunk = 64 * 1024;

std::string sha256File(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    EVP_MD_CTX* context = EVP_MD_CTX_new();
    if (!context) return {};
    std::string result;
    if (EVP_DigestInit_ex(context, EVP_sha256(), nullptr) == 1) {
        std::array<char, kCopyChunk> buffer{};
        while (input.read(buffer.data(), buffer.size()) || input.gcount() > 0) {
            EVP_DigestUpdate(context, buffer.data(), static_cast<std::size_t>(input.gcount()));
            if (!input) break;
        }
        unsigned char digest[EVP_MAX_MD_SIZE];
        unsigned int length = 0;
        if (EVP_DigestFinal_ex(context, digest, &length) == 1) {
            std::ostringstream hex;
            for (unsigned int i = 0; i < length; ++i) {
                hex << std::hex << std::setw(2) << std::setfill('0')
                    << static_cast<unsigned int>(digest[i]);
            }
            result = hex.str();
        }
    }
    EVP_MD_CTX_free(context);
    return result;
}

}  // namespace

IosBackupExtractor::IosBackupExtractor(const std::string& rootPath)
    : rootPath_(rootPath) {}

IosBackupExtractor::~IosBackupExtractor() = default;

std::string IosBackupExtractor::normalizeLogical(const std::string& raw) {
    std::string value = raw;
    std::replace(value.begin(), value.end(), '\\', '/');
    while (!value.empty() && value[0] == '/') value.erase(value.begin());
    return value;
}

bool IosBackupExtractor::recognizes(const std::string& rootPath) {
    std::error_code error;
    const fs::path root(rootPath);
    if (!fs::is_directory(root, error)) return false;
    if (fs::is_regular_file(root / "Manifest.db", error) &&
        fs::is_regular_file(root / "Manifest.plist", error)) {
        return true;
    }
    // Extracted archives nest the backup one or two levels deep.
    for (const auto& child : fs::directory_iterator(root, error)) {
        if (error) return false;
        if (!child.is_directory()) continue;
        if (fs::is_regular_file(child.path() / "Manifest.db", error) &&
            fs::is_regular_file(child.path() / "Manifest.plist", error)) {
            return true;
        }
        std::error_code innerError;
        for (const auto& grandchild : fs::directory_iterator(child.path(), innerError)) {
            if (innerError) break;
            if (!grandchild.is_directory()) continue;
            if (fs::is_regular_file(grandchild.path() / "Manifest.db", innerError) &&
                fs::is_regular_file(grandchild.path() / "Manifest.plist", innerError)) {
                return true;
            }
        }
    }
    return false;
}

bool IosBackupExtractor::resolveBackupRoot() {
    std::error_code error;
    const fs::path root(rootPath_);
    if (!fs::is_directory(root, error)) {
        error_ = "IOS_BACKUP_NOT_A_DIRECTORY";
        return false;
    }
    const auto isBackup = [](const fs::path& candidate) {
        std::error_code inner;
        return fs::is_regular_file(candidate / "Manifest.db", inner) &&
               fs::is_regular_file(candidate / "Manifest.plist", inner);
    };
    if (isBackup(root)) {
        backupRoot_ = fs::weakly_canonical(root, error).string();
        return !backupRoot_.empty();
    }
    for (const auto& child : fs::directory_iterator(root, error)) {
        if (error) break;
        if (!child.is_directory()) continue;
        if (isBackup(child.path())) {
            backupRoot_ = fs::weakly_canonical(child.path(), error).string();
            return !backupRoot_.empty();
        }
        std::error_code innerError;
        for (const auto& grandchild : fs::directory_iterator(child.path(), innerError)) {
            if (innerError) break;
            if (!grandchild.is_directory()) continue;
            if (isBackup(grandchild.path())) {
                backupRoot_ = fs::weakly_canonical(grandchild.path(), error).string();
                return !backupRoot_.empty();
            }
        }
    }
    error_ = "IOS_BACKUP_MANIFEST_NOT_FOUND";
    return false;
}

bool IosBackupExtractor::loadManifestPlist() {
    const fs::path plist = fs::path(backupRoot_) / "Manifest.plist";
    std::string parseError;
    const plist::ValuePtr root = plist::parsePlistFile(plist.string(), &parseError);
    if (!root || !root->isDictionary()) {
        error_ = "IOS_BACKUP_MANIFEST_PLIST_UNREADABLE";
        return false;
    }

    encrypted_ = root->booleanOr("IsEncrypted", false);
    backupVersion_ = root->stringOr("Version");

    // Device identity lives under the <Lockdown> dict. Fall back to searching
    // the root so a plist variant that flattens the keys still identifies the
    // device rather than silently reporting an empty one.
    const plist::ValuePtr lockdown = root->get("Lockdown");
    const auto lookup = [&](const std::string& key) -> std::string {
        if (lockdown && lockdown->isDictionary()) {
            const std::string value = lockdown->stringOr(key);
            if (!value.empty()) return value;
        }
        return root->stringOr(key);
    };
    device_["product_type"] = lookup("ProductType");
    device_["product_version"] = lookup("ProductVersion");
    device_["build_version"] = lookup("BuildVersion");
    device_["unique_device_id"] = lookup("UniqueDeviceID");
    device_["serial_number"] = lookup("SerialNumber");
    device_["imei"] = lookup("IMEI");

    // Applications is a dict of bundle id -> metadata; its size is the
    // cheapest honest count of apps in the backup.
    const plist::ValuePtr applications = root->get("Applications");
    if (applications && applications->isDictionary()) {
        applicationCount_ = applications->dictionary.size();
    }

    if (encrypted_) {
        // Parsing an encrypted backup needs the user password; refuse rather
        // than silently reporting zero artifacts.
        error_ = "IOS_BACKUP_ENCRYPTED";
        return false;
    }
    return true;
}

bool IosBackupExtractor::loadManifestIndex() {
    const fs::path manifest = fs::path(backupRoot_) / "Manifest.db";
    manifestSha256_ = sha256File(manifest);

    sqlite3* db = nullptr;
    // Read-only: the backup is evidence and must not be written.
    const std::string uri = "file:" + manifest.string() + "?mode=ro";
    if (sqlite3_open_v2(uri.c_str(), &db, SQLITE_OPEN_READONLY | SQLITE_OPEN_URI, nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        error_ = "IOS_BACKUP_MANIFEST_DB_UNREADABLE";
        return false;
    }
    sqlite3_exec(db, "PRAGMA query_only=ON;", nullptr, nullptr, nullptr);

    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT fileID, domain, relativePath, flags FROM Files WHERE flags = 1";
    if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        error_ = "IOS_BACKUP_MANIFEST_SCHEMA_MISMATCH";
        return false;
    }

    std::size_t loaded = 0;
    while (sqlite3_step(statement) == SQLITE_ROW && loaded < kMaxIndexEntries) {
        const char* fileId = reinterpret_cast<const char*>(sqlite3_column_text(statement, 0));
        const char* domain = reinterpret_cast<const char*>(sqlite3_column_text(statement, 1));
        const char* relative = reinterpret_cast<const char*>(sqlite3_column_text(statement, 2));
        if (!fileId || !domain || !relative) continue;
        Entry entry;
        entry.fileId = fileId;
        entry.domain = domain;
        entry.relativePath = relative;
        const std::string logical = std::string(domain) + "/" + normalizeLogical(relative);
        const fs::path shard = fs::path(backupRoot_) / entry.fileId.substr(0, 2) / entry.fileId;
        std::error_code sizeError;
        entry.size = fs::is_regular_file(shard, sizeError)
                         ? static_cast<long long>(fs::file_size(shard, sizeError))
                         : 0;
        index_[logical] = entry;
        byDomain_[entry.domain].push_back(logical);
        ++loaded;
    }
    sqlite3_finalize(statement);
    sqlite3_close(db);
    entryCount_ = loaded;

    for (auto& [domain, paths] : byDomain_) {
        (void)domain;
        std::sort(paths.begin(), paths.end());
    }
    return true;
}

bool IosBackupExtractor::initialize() {
    if (!resolveBackupRoot()) return false;
    manifestPlistSha256_ = sha256File(fs::path(backupRoot_) / "Manifest.plist");
    if (!loadManifestPlist()) return false;
    if (!loadManifestIndex()) return false;
    initialized_ = true;
    std::cout << "IosBackupExtractor initialized: " << backupRoot_
              << " (" << entryCount_ << " indexed files, "
              << applicationCount_ << " apps)" << std::endl;
    return true;
}

std::string IosBackupExtractor::shardPathFor(const std::string& imageRelPath) const {
    const std::string logical = normalizeLogical(imageRelPath);
    const auto found = index_.find(logical);
    if (found == index_.end()) return {};
    std::error_code error;
    const fs::path shard = fs::path(backupRoot_) / found->second.fileId.substr(0, 2) / found->second.fileId;
    if (!fs::is_regular_file(shard, error)) return {};
    return shard.string();
}

bool IosBackupExtractor::extractFileByPath(const std::string& imageRelPath,
                                           const std::string& outPath) {
    if (!initialized_) return false;
    const std::string logical = normalizeLogical(imageRelPath);
    const auto found = index_.find(logical);
    if (found == index_.end()) return false;

    const Entry& entry = found->second;
    const fs::path shard = fs::path(backupRoot_) / entry.fileId.substr(0, 2) / entry.fileId;
    std::error_code error;
    if (!fs::is_regular_file(shard, error)) return false;

    try {
        const fs::path destination(outPath);
        if (!destination.parent_path().empty()) {
            fs::create_directories(destination.parent_path(), error);
        }
        fs::copy_file(shard, destination, fs::copy_options::overwrite_existing, error);
        if (error) {
            std::cerr << "IosBackupExtractor: copy failed for " << imageRelPath
                      << ": " << error.message() << std::endl;
            return false;
        }
    } catch (const std::exception& exception) {
        std::cerr << "IosBackupExtractor: copy threw for " << imageRelPath
                  << ": " << exception.what() << std::endl;
        return false;
    }

    std::error_code sizeError;
    const std::size_t written = static_cast<std::size_t>(fs::file_size(outPath, sizeError));
    recordProvenance(logical, entry, written, sha256File(outPath));
    return true;
}

void IosBackupExtractor::recordProvenance(const std::string& logicalPath,
                                          const Entry& entry,
                                          std::size_t size,
                                          const std::string& sha256) const {
    AndroidSourceProvenance provenance;
    provenance.sourceContainer = backupRoot_;
    provenance.containerSha256 = manifestSha256_;
    provenance.sourceMemberPath = entry.fileId;
    provenance.normalizedAndroidPath = logicalPath;
    provenance.memberSize = size;
    provenance.memberSha256 = sha256;
    provenance.adapterType = kAdapterType;
    provenance.adapterVersion = kAdapterVersion;
    used_[logicalPath] = provenance;
}

std::vector<AndroidSourceProvenance> IosBackupExtractor::usedSourceProvenance() const {
    std::vector<AndroidSourceProvenance> result;
    result.reserve(used_.size());
    for (const auto& [path, provenance] : used_) {
        (void)path;
        result.push_back(provenance);
    }
    return result;
}

std::vector<std::string> IosBackupExtractor::findPathsByFilename(
    const std::string& filename, std::size_t limit) const {
    std::vector<std::string> found;
    if (!initialized_ || filename.empty() || limit == 0) return found;
    for (const auto& [logical, entry] : index_) {
        const fs::path path(entry.relativePath);
        if (path.filename() != filename) continue;
        found.push_back(logical);
        if (found.size() >= limit) break;
    }
    std::sort(found.begin(), found.end());
    return found;
}

std::vector<std::string> IosBackupExtractor::listDomain(const std::string& domain) const {
    const auto found = byDomain_.find(domain);
    return found == byDomain_.end() ? std::vector<std::string>{} : found->second;
}

std::vector<std::string> IosBackupExtractor::domains() const {
    std::vector<std::string> names;
    names.reserve(byDomain_.size());
    for (const auto& [domain, paths] : byDomain_) {
        (void)paths;
        names.push_back(domain);
    }
    return names;
}
