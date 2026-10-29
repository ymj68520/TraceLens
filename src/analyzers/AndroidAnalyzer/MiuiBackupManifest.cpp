#include "MiuiBackupManifest.h"

#include <pugixml.hpp>

#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#include <algorithm>
#include <charconv>
#include <filesystem>
#include <fstream>
#include <limits>
#include <set>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr uint64_t kMaximumManifestBytes = 16ULL * 1024 * 1024;
constexpr size_t kMaximumManifestPackages = 100000;
constexpr size_t kMaximumManifestFieldBytes = 4096;
constexpr size_t kMaximumManifestMetadataBytes = 16ULL * 1024 * 1024;
constexpr const char* kMaximumManifestPackagesEnvironment = "TRACELENS_MIUI_MAX_MANIFEST_PACKAGES";
constexpr const char* kMaximumManifestFieldBytesEnvironment = "TRACELENS_MIUI_MAX_MANIFEST_FIELD_BYTES";
constexpr const char* kMaximumManifestMetadataBytesEnvironment = "TRACELENS_MIUI_MAX_MANIFEST_METADATA_BYTES";

size_t boundedManifestLimit(const char* environment, size_t maximum) {
    const char* configured = std::getenv(environment);
    if (!configured || *configured == '\0') return maximum;
    uint64_t value = 0;
    const char* end = configured + std::char_traits<char>::length(configured);
    const auto [parsedEnd, error] = std::from_chars(configured, end, value, 10);
    if (error != std::errc{} || parsedEnd != end || value == 0 || value > maximum) return maximum;
    return static_cast<size_t>(value);
}

bool parseU64(const char* text, uint64_t& value) {
    value = 0;
    if (!text || *text == '\0') return true;
    const char* end = text + std::char_traits<char>::length(text);
    const auto [parsedEnd, error] = std::from_chars(text, end, value, 10);
    return error == std::errc{} && parsedEnd == end;
}

bool parseInt(const char* text, int& value) {
    uint64_t parsed = 0;
    if (!parseU64(text, parsed) || parsed > static_cast<uint64_t>(std::numeric_limits<int>::max())) {
        return false;
    }
    value = static_cast<int>(parsed);
    return true;
}

bool isWithin(const fs::path& root, const fs::path& child) {
    const auto relative = child.lexically_relative(root);
    return !relative.empty() && relative != "." && !relative.is_absolute() &&
           *relative.begin() != "..";
}

bool readManifestFile(const fs::path& root, std::vector<char>& bytes) {
    const fs::path manifest = root / "descript.xml";
#ifndef _WIN32
    const int descriptor = ::open(manifest.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (descriptor < 0) return false;
    struct stat status{};
    const bool valid = ::fstat(descriptor, &status) == 0 && S_ISREG(status.st_mode) &&
                       status.st_size >= 0 &&
                       static_cast<uint64_t>(status.st_size) <= kMaximumManifestBytes;
    if (!valid) {
        ::close(descriptor);
        return false;
    }
    bytes.resize(static_cast<size_t>(status.st_size));
    size_t offset = 0;
    while (offset < bytes.size()) {
        const ssize_t count = ::read(descriptor, bytes.data() + offset, bytes.size() - offset);
        if (count <= 0) {
            ::close(descriptor);
            return false;
        }
        offset += static_cast<size_t>(count);
    }
    ::close(descriptor);
    return true;
#else
    std::error_code error;
    if (fs::is_symlink(fs::symlink_status(manifest, error)) || error ||
        !fs::is_regular_file(manifest, error) || error) {
        return false;
    }
    const uint64_t size = fs::file_size(manifest, error);
    if (error || size > kMaximumManifestBytes) return false;
    bytes.resize(static_cast<size_t>(size));
    std::ifstream input(manifest, std::ios::binary);
    input.read(bytes.data(), static_cast<std::streamsize>(bytes.size()));
    return input.good() || (input.eof() && input.gcount() == static_cast<std::streamsize>(bytes.size()));
#endif
}

bool boundedText(const char* value, size_t maximumBytes, std::string& output) {
    output = value ? value : "";
    return output.size() <= maximumBytes;
}

bool addMetadataBytes(size_t amount, size_t maximumBytes, size_t& total) {
    if (amount > maximumBytes - total) return false;
    total += amount;
    return true;
}

bool parsePackage(const pugi::xml_node& node, size_t maximumFieldBytes,
                  size_t maximumMetadataBytes, BackupPackage& package, size_t& metadataBytes) {
    if (node.type() != pugi::node_element || std::string(node.name()) != "package") return false;
    const pugi::xml_node name = node.child("packageName");
    const pugi::xml_node bak = node.child("bakFile");
    if (!name || !bak || name.next_sibling("packageName") || bak.next_sibling("bakFile")) return false;
    if (!boundedText(name.text().as_string(), maximumFieldBytes, package.packageName) ||
        !boundedText(bak.text().as_string(), maximumFieldBytes, package.bakFile) ||
        package.packageName.empty() || package.bakFile.empty() ||
        !addMetadataBytes(package.packageName.size() + package.bakFile.size(), maximumMetadataBytes,
                          metadataBytes)) {
        return false;
    }
    return parseInt(node.child("bakType").text().as_string(), package.bakType) &&
           parseInt(node.child("error").text().as_string(), package.error) &&
           parseInt(node.child("state").text().as_string(), package.state) &&
           parseU64(node.child("pkgSize").text().as_string(), package.pkgSize) &&
           parseU64(node.child("sdSize").text().as_string(), package.sdSize);
}

}  // namespace

bool parseMiuiManifest(const std::string& backupFolder, BackupMeta& out) {
    out = BackupMeta{};
    std::error_code error;
    const fs::path root = fs::canonical(backupFolder, error);
    if (error || !fs::is_directory(root, error) || error) return false;

    const fs::path manifestPath = root / "descript.xml";
    const fs::path weakManifest = fs::weakly_canonical(manifestPath, error);
    if (error || !isWithin(root, weakManifest) || weakManifest.parent_path() != root) return false;

    std::vector<char> bytes;
    if (!readManifestFile(root, bytes) || bytes.empty()) return false;

    pugi::xml_document document;
    const pugi::xml_parse_result result = document.load_buffer(
        bytes.data(), bytes.size(), pugi::parse_default | pugi::parse_ws_pcdata,
        pugi::encoding_utf8);
    if (!result) return false;

    const pugi::xml_node rootNode = document.document_element();
    if (!rootNode || std::string(rootNode.name()) != "MIUI-backup" ||
        rootNode.next_sibling()) {
        return false;
    }
    const pugi::xml_node packages = rootNode.child("packages");
    if (!packages || packages.next_sibling("packages")) return false;

    const size_t maximumPackages = boundedManifestLimit(
        kMaximumManifestPackagesEnvironment, kMaximumManifestPackages);
    const size_t maximumFieldBytes = boundedManifestLimit(
        kMaximumManifestFieldBytesEnvironment, kMaximumManifestFieldBytes);
    const size_t maximumMetadataBytes = boundedManifestLimit(
        kMaximumManifestMetadataBytesEnvironment, kMaximumManifestMetadataBytes);
    size_t metadataBytes = 0;
    if (!boundedText(rootNode.child("device").text().as_string(), maximumFieldBytes, out.device) ||
        !boundedText(rootNode.child("miuiVersion").text().as_string(), maximumFieldBytes,
                     out.miuiVersion) ||
        !addMetadataBytes(out.device.size() + out.miuiVersion.size(), maximumMetadataBytes,
                          metadataBytes)) {
        return false;
    }
    if (!parseU64(rootNode.child("date").text().as_string(), out.date) ||
        !parseU64(rootNode.child("size").text().as_string(), out.totalSize)) {
        return false;
    }
    out.sourceFolder = root.string();

    for (pugi::xml_node child = packages.first_child(); child; child = child.next_sibling()) {
        if (child.type() == pugi::node_pcdata && std::string(child.value()).find_first_not_of(" \t\r\n") == std::string::npos) {
            continue;
        }
        BackupPackage package;
        if (out.packages.size() >= maximumPackages ||
            !parsePackage(child, maximumFieldBytes, maximumMetadataBytes, package, metadataBytes)) {
            return false;
        }
        out.packages.push_back(std::move(package));
    }
    return true;
}

namespace {

// "短信设置(com.android.mms).bak" -> "com.android.mms". The display name may
// contain spaces and CJK, so the trailing "(<package>)" group is the anchor.
std::string packageFromBakFilename(const std::string& filename) {
    const std::string extension = ".bak";
    if (filename.size() <= extension.size()) return "";
    const std::string base = filename.substr(0, filename.size() - extension.size());
    if (filename.compare(filename.size() - extension.size(), extension.size(), extension) != 0) {
        return "";
    }
    const size_t open = base.rfind('(');
    if (open == std::string::npos || base.empty() || base.back() != ')') return "";
    const std::string candidate = base.substr(open + 1, base.size() - open - 2);
    if (candidate.empty() || candidate.find('/') != std::string::npos ||
        candidate.find('\\') != std::string::npos || candidate.find_first_of(" \t\r\n") != std::string::npos) {
        return "";
    }
    return candidate;
}

// Fallback for .bak files whose name does not follow the MIUI convention: the
// header's second line is "<packageName> <displayName>".
std::string packageFromBakHeader(const fs::path& bakPath) {
    std::ifstream input(bakPath, std::ios::binary);
    if (!input) return "";
    std::string line;
    if (!std::getline(input, line) || line.rfind("MIUI BACKUP", 0) != 0) return "";
    if (!std::getline(input, line)) return "";      // MIUI format version
    if (!std::getline(input, line)) return "";      // "<package> <display>"
    if (!line.empty() && line.back() == '\r') line.pop_back();
    const size_t space = line.find(' ');
    const std::string package = space == std::string::npos ? line : line.substr(0, space);
    if (package.empty() || package.size() > kMaximumManifestFieldBytes) return "";
    return package;
}

}  // namespace

bool recoverUnlistedBackupPackages(const std::string& backupFolder, BackupMeta& manifest) {
    std::error_code error;
    const fs::path root = fs::canonical(backupFolder, error);
    if (error || !fs::is_directory(root, error) || error) return false;

    std::set<std::string> listed;
    for (const auto& package : manifest.packages) listed.insert(package.bakFile);

    std::vector<std::string> unlisted;
    for (fs::directory_iterator it(root, error), end; !error && it != end; it.increment(error)) {
        const fs::path& path = it->path();
        if (path.extension() != ".bak") continue;
        const std::string name = path.filename().string();
        if (listed.count(name)) continue;
        std::error_code statusError;
        if (!fs::is_regular_file(path, statusError) || statusError) continue;
        unlisted.push_back(name);
    }
    if (error) return false;
    std::sort(unlisted.begin(), unlisted.end());
    unlisted.erase(std::unique(unlisted.begin(), unlisted.end()), unlisted.end());

    for (const auto& bakFile : unlisted) {
        if (manifest.packages.size() >= kMaximumManifestPackages) break;
        BackupPackage package;
        package.bakFile = bakFile;
        package.packageName = packageFromBakFilename(bakFile);
        if (package.packageName.empty()) {
            package.packageName = packageFromBakHeader(root / bakFile);
        }
        std::error_code sizeError;
        package.pkgSize = fs::file_size(root / bakFile, sizeError);
        if (sizeError) package.pkgSize = 0;
        package.state = 1;
        package.discoveredOnDisk = true;
        manifest.packages.push_back(std::move(package));
        manifest.totalSize += manifest.packages.back().pkgSize;
    }
    if (!unlisted.empty()) manifest.recoveredMissingPackages = true;
    return true;
}

namespace {

bool holdsManifest(const fs::path& directory) {
    std::error_code error;
    return fs::is_regular_file(directory / "descript.xml", error) && !error;
}

bool holdsBakFiles(const fs::path& directory) {
    std::error_code error;
    for (fs::directory_iterator it(directory, error), end; !error && it != end;
         it.increment(error)) {
        if (it->path().extension() == ".bak") return true;
    }
    return false;
}

}  // namespace

bool resolveMiuiBackupLayout(const std::string& requestedPath, MiuiBackupLayout& out) {
    out = MiuiBackupLayout{};
    std::error_code error;
    const fs::path requested = fs::canonical(requestedPath, error);
    if (error || !fs::is_directory(requested, error) || error) return false;

    // Case 1: the requested folder is the backup root itself.
    if (holdsManifest(requested)) {
        out.backupRoot = requested.string();
        const fs::path external = requested.parent_path() / "sdcard";
        if (fs::is_directory(external, error) && !error) out.externalRoot = external.string();
        return true;
    }

    // Case 2: the requested folder is the export parent holding miui_backup/
    // and sdcard/ side by side. Only a bounded set of names is probed so an
    // unrelated directory tree cannot turn this into a deep scan.
    static const char* kCandidateNames[] = {"miui_backup", "MIUI-BACKUP", "backup"};
    for (const char* name : kCandidateNames) {
        const fs::path candidate = requested / name;
        if (!holdsManifest(candidate)) continue;
        out.backupRoot = candidate.string();
        out.nested = true;
        const fs::path external = requested / "sdcard";
        if (fs::is_directory(external, error) && !error) out.externalRoot = external.string();
        return true;
    }

    // Case 3: the requested folder is one level above the export parent (some
    // archives wrap everything in a device-named directory).
    for (fs::directory_iterator it(requested, error), end; !error && it != end;
         it.increment(error)) {
        std::error_code childError;
        if (!fs::is_directory(it->path(), childError) || childError) continue;
        for (const char* name : kCandidateNames) {
            const fs::path candidate = it->path() / name;
            if (!holdsManifest(candidate) || !holdsBakFiles(candidate)) continue;
            out.backupRoot = candidate.string();
            out.nested = true;
            const fs::path external = it->path() / "sdcard";
            if (fs::is_directory(external, childError) && !childError) {
                out.externalRoot = external.string();
            }
            return true;
        }
    }
    return false;
}
