#include "VivoBackupExtractor.h"
#include "VivoDeobfuscator.h"

#include <nlohmann/json.hpp>
#include <openssl/evp.h>

#include <algorithm>
#include <array>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

constexpr const char* kAdapterType = "vivo-backup";
constexpr const char* kAdapterVersion = "vivo-backup-v1";
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

std::string readFile(const fs::path& path, std::string* error) {
    std::ifstream input(path, std::ios::binary);
    if (!input) {
        if (error) *error = "FILE_UNREADABLE";
        return {};
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

}  // namespace

VivoBackupExtractor::VivoBackupExtractor(const std::string& rootPath,
                                         const std::string& indexPath)
    : rootPath_(rootPath), indexPath_(indexPath) {}

VivoBackupExtractor::~VivoBackupExtractor() = default;

std::string VivoBackupExtractor::normalizeLogical(const std::string& raw) {
    std::string value = raw;
    std::replace(value.begin(), value.end(), '\\', '/');
    while (!value.empty() && value[0] == '/') value.erase(value.begin());
    return value;
}

bool VivoBackupExtractor::recognizes(const std::string& rootPath) {
    std::error_code error;
    const fs::path root(rootPath);
    if (!fs::is_directory(root, error)) return false;
    const auto isBackup = [](const fs::path& candidate) {
        std::error_code inner;
        return fs::is_regular_file(candidate / ".backup", inner) &&
               fs::is_directory(candidate / "db", inner);
    };
    if (isBackup(root)) return true;
    for (const auto& child : fs::directory_iterator(root, error)) {
        if (error) return false;
        if (child.is_directory() && isBackup(child.path())) return true;
        if (!child.is_directory()) continue;
        std::error_code innerError;
        for (const auto& grandchild : fs::directory_iterator(child.path(), innerError)) {
            if (innerError) break;
            if (grandchild.is_directory() && isBackup(grandchild.path())) return true;
        }
    }
    return false;
}

bool VivoBackupExtractor::resolveBackupRoot() {
    std::error_code error;
    const fs::path root(rootPath_);
    if (!fs::is_directory(root, error)) {
        error_ = "VIVO_BACKUP_NOT_A_DIRECTORY";
        return false;
    }
    const auto isBackup = [](const fs::path& candidate) {
        std::error_code inner;
        return fs::is_regular_file(candidate / ".backup", inner) &&
               fs::is_directory(candidate / "db", inner);
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
    error_ = "VIVO_BACKUP_HEADER_NOT_FOUND";
    return false;
}

bool VivoBackupExtractor::loadHeader() {
    std::string readError;
    const std::string bytes = readFile(fs::path(backupRoot_) / ".backup", &readError);
    if (bytes.empty()) {
        error_ = "VIVO_BACKUP_HEADER_UNREADABLE";
        return false;
    }
    json header = json::parse(bytes, nullptr, false);
    if (header.is_discarded() || !header.is_object()) {
        error_ = "VIVO_BACKUP_HEADER_MALFORMED";
        return false;
    }
    model_ = header.value("model", "");
    backupTimeMs_ = header.value("createTime", 0LL);
    if (header.value("encrypted", false)) {
        error_ = "VIVO_BACKUP_ENCRYPTED";
        return false;
    }
    if (header.contains("backupPackageVer")) {
        backupVersion_ = std::to_string(header["backupPackageVer"].get<long long>());
    }
    return true;
}

bool VivoBackupExtractor::loadIndex() {
    fs::path index = indexPath_.empty() ? fs::path(backupRoot_) / "index.json"
                                        : fs::path(indexPath_);
    std::string readError;
    const std::string bytes = readFile(index, &readError);
    if (bytes.empty()) {
        error_ = "VIVO_BACKUP_INDEX_MISSING";
        return false;
    }
    json document = json::parse(bytes, nullptr, false);
    if (document.is_discarded() || !document.is_object()) {
        error_ = "VIVO_BACKUP_INDEX_MALFORMED";
        return false;
    }

    obfuscated_ = document.value("obfuscated", false);

    if (document.contains("items") && document["items"].is_array()) {
        for (const auto& entry : document["items"]) {
            if (!entry.is_object()) continue;
            Item item;
            item.category = entry.value("category", "");
            item.hash = entry.value("hash", "");
            item.originalPath = normalizeLogical(entry.value("original_path", ""));
            item.size = entry.value("size", 0LL);
            item.mtimeMs = entry.value("mtime_ms", 0LL);
            if (item.hash.empty()) continue;
            const std::size_t position = items_.size();
            items_.push_back(item);
            if (!item.originalPath.empty()) {
                byOriginalPath_[item.originalPath] = position;
            }
        }
    }

    if (document.contains("applications") && document["applications"].is_array()) {
        std::map<std::string, std::size_t> packageIndex;
        for (const auto& entry : document["applications"]) {
            if (!entry.is_object()) continue;
            Item item;
            item.category = "app";
            item.hash = entry.value("hash", "");
            item.package = entry.value("package", "");
            item.appName = entry.value("app_name", "");
            item.versionName = entry.value("version_name", "");
            item.size = entry.value("size", 0LL);
            item.originalPath = entry.value("file_name", "");
            if (item.hash.empty()) continue;
            items_.push_back(item);
            if (!item.package.empty()) packageIndex[item.package] = items_.size() - 1;
        }
        applicationCount_ = packageIndex.size();
    }
    return true;
}

bool VivoBackupExtractor::initialize() {
    if (!resolveBackupRoot()) return false;
    if (!loadHeader()) return false;
    if (!loadIndex()) return false;
    // Probe whether the obfuscation key actually decodes this package: decode a
    // few payload heads and require known container magic. This is evidence-
    // based rather than an assumption that any xor_obfuscated flag is reversible.
    if (obfuscated_) {
        int probed = 0;
        int confirmed = 0;
        for (const Item& item : items_) {
            if (probed >= 8) break;
            const fs::path payload = fs::path(backupRoot_) / item.hash;
            std::error_code probeError;
            if (!fs::is_regular_file(payload, probeError)) continue;
            std::string kind;
            vivo::describeDecodedType(payload.string(), &kind);
            ++probed;
            if (kind != "unknown") ++confirmed;
        }
        deobfuscationSucceeded_ = probed > 0 && confirmed * 2 >= probed;
        std::cout << "VivoBackupExtractor: obfuscation probe " << confirmed << "/" << probed
                  << " decoded to known formats" << std::endl;
    }

    initialized_ = true;
    std::cout << "VivoBackupExtractor initialized: " << backupRoot_
              << " (" << items_.size() << " indexed entries, "
              << applicationCount_ << " apps, obfuscated=" << (obfuscated_ ? "yes" : "no")
              << ")" << std::endl;
    return true;
}

bool VivoBackupExtractor::extractFileByPath(const std::string& imageRelPath,
                                            const std::string& outPath) {
    if (!initialized_) return false;
    const std::string logical = normalizeLogical(imageRelPath);
    const auto found = byOriginalPath_.find(logical);
    if (found == byOriginalPath_.end()) return false;

    const Item& item = items_[found->second];
    const fs::path payload = fs::path(backupRoot_) / item.hash;
    std::error_code error;
    if (!fs::is_regular_file(payload, error)) return false;

    try {
        const fs::path destination(outPath);
        if (!destination.parent_path().empty()) {
            fs::create_directories(destination.parent_path(), error);
        }
        fs::copy_file(payload, destination, fs::copy_options::overwrite_existing, error);
        if (error) {
            std::cerr << "VivoBackupExtractor: copy failed for " << imageRelPath
                      << ": " << error.message() << std::endl;
            return false;
        }
    } catch (const std::exception& exception) {
        std::cerr << "VivoBackupExtractor: copy threw for " << imageRelPath
                  << ": " << exception.what() << std::endl;
        return false;
    }

    // Reverse the position-based XOR when the package is obfuscated. The
    // transform is written back over the extracted copy, never over evidence.
    if (obfuscated_) {
        std::ifstream input(outPath, std::ios::binary);
        if (!input) return false;
        std::vector<std::uint8_t> bytes((std::istreambuf_iterator<char>(input)),
                                        std::istreambuf_iterator<char>());
        input.close();
        vivo::deobfuscateInPlace(bytes, 0);
        std::ofstream output(outPath, std::ios::binary | std::ios::trunc);
        if (!output) return false;
        output.write(reinterpret_cast<const char*>(bytes.data()),
                     static_cast<std::streamsize>(bytes.size()));
    }

    std::error_code sizeError;
    const std::size_t written = static_cast<std::size_t>(fs::file_size(outPath, sizeError));
    recordProvenance(item, written, sha256File(outPath));
    return true;
}

void VivoBackupExtractor::recordProvenance(const Item& item, std::size_t size,
                                           const std::string& sha256) const {
    AndroidSourceProvenance provenance;
    provenance.sourceContainer = backupRoot_;
    provenance.containerSha256 = "";
    provenance.sourceMemberPath = item.hash;
    provenance.normalizedAndroidPath = item.originalPath;
    provenance.memberSize = size;
    provenance.memberSha256 = sha256;
    provenance.adapterType = kAdapterType;
    provenance.adapterVersion = kAdapterVersion;
    used_[item.originalPath.empty() ? item.hash : item.originalPath] = provenance;
}

std::vector<AndroidSourceProvenance> VivoBackupExtractor::usedSourceProvenance() const {
    std::vector<AndroidSourceProvenance> result;
    result.reserve(used_.size());
    for (const auto& [path, provenance] : used_) {
        (void)path;
        result.push_back(provenance);
    }
    return result;
}

std::vector<std::string> VivoBackupExtractor::findPathsByFilename(
    const std::string& filename, std::size_t limit) const {
    std::vector<std::string> found;
    if (!initialized_ || filename.empty() || limit == 0) return found;
    for (const Item& item : items_) {
        if (fs::path(item.originalPath).filename() != filename) continue;
        if (item.originalPath.empty()) continue;
        found.push_back(item.originalPath);
        if (found.size() >= limit) break;
    }
    std::sort(found.begin(), found.end());
    return found;
}
