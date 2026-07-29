#include "MiuiBackupManifest.h"

#include <pugixml.hpp>

#ifndef _WIN32
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>
#endif

#include <charconv>
#include <filesystem>
#include <fstream>
#include <limits>
#include <string>
#include <vector>

namespace fs = std::filesystem;

namespace {

constexpr uint64_t kMaximumManifestBytes = 16ULL * 1024 * 1024;

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

bool parsePackage(const pugi::xml_node& node, BackupPackage& package) {
    if (node.type() != pugi::node_element || std::string(node.name()) != "package") return false;
    const pugi::xml_node name = node.child("packageName");
    const pugi::xml_node bak = node.child("bakFile");
    if (!name || !bak || name.next_sibling("packageName") || bak.next_sibling("bakFile")) return false;
    package.packageName = name.text().as_string();
    package.bakFile = bak.text().as_string();
    if (package.packageName.empty() || package.bakFile.empty()) return false;
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

    out.device = rootNode.child("device").text().as_string();
    out.miuiVersion = rootNode.child("miuiVersion").text().as_string();
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
        if (!parsePackage(child, package)) return false;
        out.packages.push_back(std::move(package));
    }
    return true;
}
