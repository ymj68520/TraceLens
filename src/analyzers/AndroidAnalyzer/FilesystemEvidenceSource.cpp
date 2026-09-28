#include "FilesystemEvidenceSource.h"
#include "AndroidPathMapper.h"

#include <nlohmann/json.hpp>
#include <openssl/evp.h>

#include <algorithm>
#include <array>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <unordered_set>
#ifndef _WIN32
#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>
extern char** environ;
#endif

namespace fs = std::filesystem;
using json = nlohmann::json;
namespace {
constexpr std::size_t kMaxIndexed = 1'000'000;
constexpr std::uint64_t kMaxExtract = 8ULL * 1024 * 1024 * 1024;

TSK_IMG_INFO* openImage(const std::string& path) {
    const char* paths[] = {path.c_str()};
    return tsk_img_open(1, paths, TSK_IMG_TYPE_DETECT, 0);
}

bool safePath(const std::string& path) {
    std::string cleaned, reason;
    return AndroidPathMapper::safeMemberPath(path, cleaned, reason) && cleaned == path;
}

std::vector<FilesystemEvidenceEntry> listEntries(
    const std::map<std::string, FilesystemEvidenceEntry>& entries, const std::string& path) {
    std::vector<FilesystemEvidenceEntry> result;
    if (!path.empty() && !safePath(path)) return result;
    const std::string prefix = path.empty() ? "" : path + "/";
    for (const auto& [key, entry] : entries) {
        if (key.rfind(prefix, 0) != 0) continue;
        if (key.find('/', prefix.size()) == std::string::npos) result.push_back(entry);
    }
    return result;
}

std::vector<std::string> regularPaths(const std::map<std::string, FilesystemEvidenceEntry>& entries) {
    std::vector<std::string> result;
    result.reserve(entries.size());
    for (const auto& [path, entry] : entries) if (!entry.directory) result.push_back(path);
    return result;
}

std::string sha256(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    EVP_MD_CTX* ctx = EVP_MD_CTX_new();
    if (!ctx) return {};
    bool ok = EVP_DigestInit_ex(ctx, EVP_sha256(), nullptr) == 1;
    std::array<char, 1 << 20> block{};
    while (ok && input) {
        input.read(block.data(), block.size());
        if (input.gcount() > 0)
            ok = EVP_DigestUpdate(ctx, block.data(), static_cast<std::size_t>(input.gcount())) == 1;
    }
    unsigned char digest[EVP_MAX_MD_SIZE]{};
    unsigned int length = 0;
    ok = ok && !input.bad() && EVP_DigestFinal_ex(ctx, digest, &length) == 1;
    EVP_MD_CTX_free(ctx);
    if (!ok) return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned int i = 0; i < length; ++i) out << std::setw(2) << static_cast<int>(digest[i]);
    return out.str();
}

struct BridgeResult { int exitCode = -1; std::string output, error; };

BridgeResult bridge(const std::vector<std::string>& args, int timeoutSeconds = 180) {
    BridgeResult result;
#ifndef _WIN32
    int outPipe[2], errPipe[2];
    if (pipe(outPipe) || pipe(errPipe)) { result.error = "BRIDGE_PIPE_FAILED"; return result; }
    // posix_spawn is safe in the multithreaded HTTP server; no C++ work occurs
    // in a post-fork child before exec.
    const char* fieldValue = std::getenv("TRACELENS_FIELD_AUTH");
    const char* releaseRequired = std::getenv("TRACELENS_REQUIRE_RELEASE_LAYOUT");
    const bool fieldRelease = fieldValue && std::string(fieldValue) == "enabled" &&
        releaseRequired && std::string(releaseRequired) == "1";
    std::string script;
    std::string python = "/usr/bin/python3";
    if (fieldRelease) {
        const char* configuredRoot = std::getenv("TRACELENS_RELEASE_ROOT");
        const char* configuredPython = std::getenv("TRACELENS_PYTHON_BIN");
        if (!configuredRoot || !configuredPython ||
            !fs::path(configuredRoot).is_absolute() ||
            !fs::path(configuredPython).is_absolute()) {
            result.error = "BRIDGE_NOT_CONFIGURED"; return result;
        }
        std::error_code ec;
        const fs::path release = fs::canonical(configuredRoot, ec);
        if (ec || !fs::is_directory(release)) {
            result.error = "BRIDGE_NOT_CONFIGURED"; return result;
        }
        script = (release / "scripts/android_image_reader_bridge.py").string();
        python = configuredPython;
        if (!fs::is_regular_file(script) || !fs::is_regular_file(python)) {
            result.error = "BRIDGE_NOT_CONFIGURED"; return result;
        }
    } else {
#ifdef TRACELENS_SOURCE_ROOT
        script = std::string(TRACELENS_SOURCE_ROOT) + "/scripts/android_image_reader_bridge.py";
#else
        script = "scripts/android_image_reader_bridge.py";
#endif
    }
    std::vector<std::string> command{python, script};
    command.insert(command.end(), args.begin(), args.end());
    std::vector<char*> argv;
    for (auto& value : command) argv.push_back(value.data());
    argv.push_back(nullptr);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_adddup2(&actions, outPipe[1], STDOUT_FILENO);
    posix_spawn_file_actions_adddup2(&actions, errPipe[1], STDERR_FILENO);
    posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addclose(&actions, outPipe[0]);
    posix_spawn_file_actions_addclose(&actions, errPipe[0]);
    posix_spawn_file_actions_addclose(&actions, outPipe[1]);
    posix_spawn_file_actions_addclose(&actions, errPipe[1]);
    pid_t pid = -1;
    const int spawned = posix_spawn(&pid, command[0].c_str(), &actions,
                                    nullptr, argv.data(), environ);
    posix_spawn_file_actions_destroy(&actions);
    if (spawned != 0) {
        close(outPipe[0]); close(outPipe[1]); close(errPipe[0]); close(errPipe[1]);
        result.error = "BRIDGE_SPAWN_FAILED"; return result;
    }
    close(outPipe[1]); close(errPipe[1]);
    fcntl(outPipe[0], F_SETFL, O_NONBLOCK);
    fcntl(errPipe[0], F_SETFL, O_NONBLOCK);
    bool outOpen = true, errOpen = true;
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeoutSeconds);
    bool exceeded = false;
    while (outOpen || errOpen) {
        if (std::chrono::steady_clock::now() >= deadline) { exceeded = true; break; }
        pollfd fds[2]{{outPipe[0], static_cast<short>(outOpen ? POLLIN : 0), 0},
                      {errPipe[0], static_cast<short>(errOpen ? POLLIN : 0), 0}};
        if (poll(fds, 2, 200) < 0) { exceeded = true; break; }
        auto drain = [&](int fd, bool& opened, std::string& buffer, std::size_t limit) {
            if (!opened) return;
            std::array<char, 8192> bytes{};
            const ssize_t n = read(fd, bytes.data(), bytes.size());
            if (n == 0) { opened = false; close(fd); }
            else if (n > 0) {
                if (buffer.size() + static_cast<std::size_t>(n) > limit) exceeded = true;
                else buffer.append(bytes.data(), static_cast<std::size_t>(n));
            }
        };
        if (fds[0].revents) drain(outPipe[0], outOpen, result.output, 128 * 1024 * 1024);
        if (fds[1].revents) drain(errPipe[0], errOpen, result.error, 8192);
        if (exceeded) break;
    }
    if (outOpen) close(outPipe[0]);
    if (errOpen) close(errPipe[0]);
    if (exceeded) kill(pid, SIGKILL);
    int status = 0;
    waitpid(pid, &status, 0);
    result.exitCode = !exceeded && WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    if (exceeded) result.error = "BRIDGE_LIMIT_OR_TIMEOUT";
#else
    (void)args; (void)timeoutSeconds;
    result.error = "BRIDGE_UNAVAILABLE_ON_THIS_PLATFORM";
#endif
    return result;
}

bool readViaTemporary(IFilesystemEvidenceSource& source, const std::string& path,
                      std::vector<std::uint8_t>& bytes, std::size_t limit) {
#ifndef _WIN32
    std::string pattern = (fs::temp_directory_path() / "tracelens-fs-read-XXXXXX").string();
    std::vector<char> name(pattern.begin(), pattern.end()); name.push_back('\0');
    char* dir = mkdtemp(name.data());
    if (!dir) return false;
    fs::path output = fs::path(dir) / "content";
    bool okay = false;
    if (source.extractFileByPath(path, output.string())) {
        std::error_code ec;
        const auto size = fs::file_size(output, ec);
        if (!ec && size <= limit) {
            std::ifstream in(output, std::ios::binary);
            bytes.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
            okay = in.eof() && bytes.size() == size;
        }
    }
    std::error_code ec;
    fs::remove(output, ec); fs::remove(dir, ec);
    return okay;
#else
    (void)source; (void)path; (void)bytes; (void)limit;
    return false;
#endif
}
} // namespace

TskFilesystemEvidenceSource::TskFilesystemEvidenceSource(std::string image, FilesystemSourceMetadata metadata)
    : image_(std::move(image)), metadata_(std::move(metadata)) {}

TskFilesystemEvidenceSource::~TskFilesystemEvidenceSource() {
    if (filesystem_) tsk_fs_close(filesystem_);
    if (imageHandle_) tsk_img_close(imageHandle_);
}

TSK_WALK_RET_ENUM TskFilesystemEvidenceSource::walkCallback(
    TSK_FS_FILE* file, const char* parent, void* context) {
    auto* self = static_cast<TskFilesystemEvidenceSource*>(context);
    if (!file || !file->name || !file->meta || !file->name->name) return TSK_WALK_CONT;
    if (file->name->flags & TSK_FS_NAME_FLAG_UNALLOC) return TSK_WALK_CONT;
    if (!(file->meta->flags & TSK_FS_META_FLAG_ALLOC)) return TSK_WALK_CONT;
    if (file->meta->type != TSK_FS_META_TYPE_REG && file->meta->type != TSK_FS_META_TYPE_DIR)
        return TSK_WALK_CONT;
    const std::string name = file->name->name;
    if (name == "." || name == "..") return TSK_WALK_CONT;
    const std::string path = std::string(parent ? parent : "") + name;
    if (std::count(path.begin(), path.end(), '/') >= 63) {
        self->metadata_.error = "FILESYSTEM_DEPTH_LIMIT";
        return TSK_WALK_STOP;
    }
    if (!safePath(path)) return TSK_WALK_CONT;
    if (self->entries_.size() >= kMaxIndexed) {
        self->metadata_.error = "FILESYSTEM_INDEX_LIMIT";
        return TSK_WALK_STOP;
    }
    FilesystemEvidenceEntry entry;
    entry.path = path;
    entry.objectId = file->name->meta_addr;
    entry.size = std::max<std::int64_t>(0, file->meta->size);
    entry.mtime = file->meta->mtime;
    entry.ctime = file->meta->ctime;
    entry.atime = file->meta->atime;
    entry.directory = file->meta->type == TSK_FS_META_TYPE_DIR;
    if (!self->entries_.emplace(path, std::move(entry)).second)
        self->metadata_.error = "AMBIGUOUS_FILESYSTEM_PATH";
    return self->metadata_.error.empty() ? TSK_WALK_CONT : TSK_WALK_STOP;
}

bool TskFilesystemEvidenceSource::initialize() {
    const auto start = std::chrono::steady_clock::now();
    imageHandle_ = openImage(image_);
    if (!imageHandle_) { metadata_.error = "IMAGE_OPEN_FAILED"; return false; }
    filesystem_ = tsk_fs_open_img(imageHandle_, metadata_.partitionOffset, TSK_FS_TYPE_DETECT);
    if (!filesystem_ || !TSK_FS_TYPE_ISEXT(filesystem_->ftype)) {
        metadata_.error = "EXT4_OPEN_FAILED"; return false;
    }
    metadata_.reader = "The Sleuth Kit";
    metadata_.readerVersion = tsk_version_get_str();
    const auto flags = static_cast<TSK_FS_DIR_WALK_FLAG_ENUM>(
        TSK_FS_DIR_WALK_FLAG_RECURSE | TSK_FS_DIR_WALK_FLAG_ALLOC | TSK_FS_DIR_WALK_FLAG_NOORPHAN);
    if (tsk_fs_dir_walk(filesystem_, filesystem_->root_inum, flags, walkCallback, this) != 0 ||
        !metadata_.error.empty()) {
        if (metadata_.error.empty()) metadata_.error = "EXT4_WALK_FAILED";
        return false;
    }
    // TSK reads the bytes, but its generic TSK_FS_META does not expose the
    // ext4 EXT4_ENCRYPT_FL inode bit. If the filesystem advertises fscrypt,
    // require a second, pinned read-only metadata pass; otherwise fail closed
    // rather than ever staging ciphertext as a SQLite database.
    std::array<unsigned char, 4> incompat{};
    if (tsk_img_read(imageHandle_, metadata_.partitionOffset + 1024 + 96,
                     reinterpret_cast<char*>(incompat.data()), incompat.size()) !=
        static_cast<ssize_t>(incompat.size())) {
        metadata_.error = "EXT4_FEATURE_READ_FAILED"; return false;
    }
    const std::uint32_t features = static_cast<std::uint32_t>(incompat[0]) |
        (static_cast<std::uint32_t>(incompat[1]) << 8) |
        (static_cast<std::uint32_t>(incompat[2]) << 16) |
        (static_cast<std::uint32_t>(incompat[3]) << 24);
    if (features & 0x10000U) {
        const auto process = bridge({"list-ext4", image_,
                                     std::to_string(metadata_.partitionOffset)}, 600);
        if (process.exitCode != 0) {
            metadata_.error = "EXT4_ENCRYPTION_METADATA_UNAVAILABLE: " + process.error;
            return false;
        }
        std::istringstream lines(process.output);
        std::string line;
        bool ended = false;
        while (std::getline(lines, line)) {
            try {
                const auto row = json::parse(line);
                const std::string status = row.value("status", std::string());
                if (status == "END") { ended = true; continue; }
                if (status == "NAME_ENCRYPTED_OR_UNAVAILABLE") {
                    FilesystemEvidenceEntry unnamed;
                    unnamed.objectId = row.at("inode").get<std::uint64_t>();
                    unnamed.encrypted = true;
                    unnamed.nameState = "encrypted_or_unavailable";
                    unknownNames_.push_back(std::move(unnamed));
                    continue;
                }
                if (!status.empty()) { metadata_.error = "MALFORMED_EXT4_METADATA_IPC"; return false; }
                const auto path = row.at("path").get<std::string>();
                const auto found = entries_.find(path);
                if (found != entries_.end()) found->second.encrypted = row.value("encrypted", false);
            } catch (const json::exception&) {
                metadata_.error = "MALFORMED_EXT4_METADATA_IPC"; return false;
            }
        }
        if (!ended) { metadata_.error = "INCOMPLETE_EXT4_METADATA_IPC"; return false; }
    }
    metadata_.walkMilliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start).count();
    metadata_.indexedFiles = regularPaths().size();
    return true;
}

std::vector<FilesystemEvidenceEntry> TskFilesystemEvidenceSource::list(const std::string& path) const {
    return listEntries(entries_, path);
}
std::optional<FilesystemEvidenceEntry> TskFilesystemEvidenceSource::stat(const std::string& path) const {
    const auto it = entries_.find(path); return it == entries_.end() ? std::nullopt : std::optional(it->second);
}
std::vector<std::string> TskFilesystemEvidenceSource::regularPaths() const { return ::regularPaths(entries_); }
bool TskFilesystemEvidenceSource::readFile(const std::string& path, std::vector<std::uint8_t>& bytes,
                                           std::size_t limit) {
    const auto entry = stat(path);
    if (!entry || entry->directory || entry->encrypted || entry->size > limit) return false;
    return readViaTemporary(*this, path, bytes, limit);
}
bool TskFilesystemEvidenceSource::extractFileByPath(const std::string& path, const std::string& output) {
    const auto entry = stat(path);
    if (!entry || entry->directory || entry->encrypted || entry->size > kMaxExtract || !filesystem_) return false;
    TSK_FS_FILE* file = tsk_fs_file_open_meta(filesystem_, nullptr, entry->objectId);
    if (!file || !file->meta || file->meta->type != TSK_FS_META_TYPE_REG ||
        file->meta->size != static_cast<TSK_OFF_T>(entry->size)) {
        if (file) tsk_fs_file_close(file);
        return false;
    }
    std::error_code ec;
    if (fs::is_symlink(fs::symlink_status(output, ec))) { tsk_fs_file_close(file); return false; }
    fs::create_directories(fs::path(output).parent_path(), ec);
    std::ofstream sink(output, std::ios::binary | std::ios::trunc);
    bool okay = static_cast<bool>(sink);
    std::array<char, 1 << 20> bytes{};
    std::uint64_t offset = 0;
    while (okay && offset < entry->size) {
        const auto want = std::min<std::uint64_t>(bytes.size(), entry->size - offset);
        const auto n = tsk_fs_file_read(file, offset, bytes.data(), want, TSK_FS_FILE_READ_FLAG_NONE);
        if (n <= 0) { okay = false; break; }
        sink.write(bytes.data(), n);
        offset += n;
        okay = static_cast<bool>(sink);
    }
    sink.close();
    tsk_fs_file_close(file);
    if (!okay || offset != entry->size) { fs::remove(output, ec); return false; }
    ++metadata_.extractedFiles;
    metadata_.bytesRead += offset;
    return true;
}

F2fsFilesystemEvidenceSource::F2fsFilesystemEvidenceSource(std::string image, FilesystemSourceMetadata metadata)
    : image_(std::move(image)), metadata_(std::move(metadata)) {}

bool F2fsFilesystemEvidenceSource::initialize() {
    const auto start = std::chrono::steady_clock::now();
    const auto process = bridge({"list", image_, std::to_string(metadata_.partitionOffset)}, 600);
    if (process.exitCode != 0) { metadata_.error = "F2FS_WALK_FAILED: " + process.error; return false; }
    std::istringstream lines(process.output);
    std::string line;
    bool ended = false;
    while (std::getline(lines, line)) {
        try {
            const auto row = json::parse(line);
            if (row.value("status", std::string()) == "END") {
                metadata_.reader = "qnxprobe";
                metadata_.readerVersion = row.at("reader").get<std::string>();
                ended = true;
                continue;
            }
            if (row.value("status", std::string()) == "NAME_ENCRYPTED_OR_UNAVAILABLE") {
                FilesystemEvidenceEntry unnamed;
                unnamed.objectId = row.at("inode").get<std::uint64_t>();
                unnamed.nameState = "encrypted_or_unavailable";
                unnamed.encrypted = true;
                unknownNames_.push_back(std::move(unnamed));
                continue; // Never synthesize a pathname.
            }
            if (row.contains("status")) { metadata_.error = "UNKNOWN_F2FS_IPC_STATUS"; return false; }
            FilesystemEvidenceEntry entry;
            entry.path = row.at("path").get<std::string>();
            if (!safePath(entry.path)) { metadata_.error = "UNSAFE_F2FS_NAME"; return false; }
            entry.objectId = row.at("inode").get<std::uint64_t>();
            entry.size = row.at("size").get<std::uint64_t>();
            entry.mtime = row.value("mtime", 0LL);
            entry.ctime = row.value("ctime", 0LL);
            entry.atime = row.value("atime", 0LL);
            entry.directory = (row.at("mode").get<unsigned>() & 0170000) == 0040000;
            entry.encrypted = row.value("encrypted", false);
            entry.compressed = row.value("compressed", false);
            entry.nameState = row.value("name_state", std::string("clear"));
            if (entries_.size() >= kMaxIndexed || !entries_.emplace(entry.path, std::move(entry)).second) {
                metadata_.error = "F2FS_INDEX_LIMIT_OR_AMBIGUOUS_PATH"; return false;
            }
        } catch (const json::exception&) { metadata_.error = "MALFORMED_F2FS_IPC"; return false; }
    }
    if (!ended) { metadata_.error = "INCOMPLETE_F2FS_IPC"; return false; }
    metadata_.walkMilliseconds = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start).count();
    metadata_.indexedFiles = regularPaths().size();
    return true;
}
std::vector<FilesystemEvidenceEntry> F2fsFilesystemEvidenceSource::list(const std::string& path) const {
    return listEntries(entries_, path);
}
std::optional<FilesystemEvidenceEntry> F2fsFilesystemEvidenceSource::stat(const std::string& path) const {
    const auto it = entries_.find(path); return it == entries_.end() ? std::nullopt : std::optional(it->second);
}
std::vector<std::string> F2fsFilesystemEvidenceSource::regularPaths() const { return ::regularPaths(entries_); }
bool F2fsFilesystemEvidenceSource::readFile(const std::string& path, std::vector<std::uint8_t>& bytes,
                                            std::size_t limit) {
    const auto entry = stat(path);
    if (!entry || entry->directory || entry->size > limit || entry->encrypted || entry->compressed) return false;
    return readViaTemporary(*this, path, bytes, limit);
}
bool F2fsFilesystemEvidenceSource::extractFileByPath(const std::string& path, const std::string& output) {
    const auto entry = stat(path);
    if (!entry || entry->directory || entry->encrypted || entry->compressed || entry->size > kMaxExtract)
        return false;
    std::error_code ec;
    if (fs::is_symlink(fs::symlink_status(output, ec))) return false;
    fs::create_directories(fs::path(output).parent_path(), ec);
    if (ec) return false;
    fs::path part = output + ".f2fs-part";
    if (fs::exists(part, ec) || fs::is_symlink(fs::symlink_status(part, ec))) return false;
    const auto process = bridge({"extract", image_, std::to_string(metadata_.partitionOffset),
                                 std::to_string(entry->objectId), std::to_string(entry->size), part.string()}, 600);
    if (process.exitCode != 0) { fs::remove(part, ec); metadata_.error = process.error; return false; }
    try {
        const auto response = json::parse(process.output);
        if (response.at("status") != "OK" || response.at("bytes") != entry->size ||
            fs::file_size(part) != entry->size) { fs::remove(part, ec); return false; }
    } catch (const std::exception&) { fs::remove(part, ec); return false; }
    fs::rename(part, output, ec);
    if (ec) { fs::remove(part, ec); return false; }
    ++metadata_.extractedFiles;
    metadata_.bytesRead += entry->size;
    return true;
}

std::unique_ptr<IFilesystemEvidenceSource> openAndroidFilesystemImage(
    const std::string& image, std::string& error,
    std::optional<std::uint64_t> expectedOffset) {
    error = "ANDROID_USERDATA_NOT_FOUND";
    TSK_IMG_INFO* img = openImage(image);
    if (!img) { error = "IMAGE_OPEN_FAILED"; return {}; }
    struct Candidate { std::uint64_t offset; int number; std::string name; std::string kind; };
    std::vector<Candidate> candidates;
    TSK_VS_INFO* vs = tsk_vs_open(img, 0, TSK_VS_TYPE_DETECT);
    if (vs) {
        for (TSK_PNUM_T i = 0; i < vs->part_count; ++i) {
            const TSK_VS_PART_INFO* part = tsk_vs_part_get(vs, i);
            if (part && (part->flags & TSK_VS_PART_FLAG_ALLOC))
                candidates.push_back({part->start * vs->block_size, static_cast<int>(i),
                                      part->desc ? part->desc : "", ""});
        }
        tsk_vs_close(vs);
    } else candidates.push_back({0, 0, "single_partition", ""});
    const std::string container = TSK_IMG_TYPE_ISEWF(img->itype) ? "e01" : "raw";
    std::unique_ptr<IFilesystemEvidenceSource> best;
    int bestScore = 0;
    for (auto& candidate : candidates) {
        if (expectedOffset && candidate.offset != *expectedOffset) continue;
        std::array<char, 1082> header{};
        if (tsk_img_read(img, candidate.offset, header.data(), header.size()) !=
            static_cast<ssize_t>(header.size())) continue;
        const bool f2fs = static_cast<unsigned char>(header[1024]) == 0x10 &&
                          static_cast<unsigned char>(header[1025]) == 0x20 &&
                          static_cast<unsigned char>(header[1026]) == 0xf5 &&
                          static_cast<unsigned char>(header[1027]) == 0xf2;
        const bool ext4 = static_cast<unsigned char>(header[1080]) == 0x53 &&
                          static_cast<unsigned char>(header[1081]) == 0xef;
        if (!f2fs && !ext4) continue;
        FilesystemSourceMetadata metadata;
        metadata.imagePath = image;
        metadata.containerType = container;
        metadata.partitionName = candidate.name;
        metadata.partitionNumber = candidate.number;
        metadata.partitionOffset = candidate.offset;
        metadata.filesystemType = f2fs ? "f2fs" : "ext4";
        std::unique_ptr<IFilesystemEvidenceSource> source = f2fs
            ? std::unique_ptr<IFilesystemEvidenceSource>(
                std::make_unique<F2fsFilesystemEvidenceSource>(image, metadata))
            : std::unique_ptr<IFilesystemEvidenceSource>(
                std::make_unique<TskFilesystemEvidenceSource>(image, metadata));
        if (!source->initialize()) { error = source->sourceMetadata().error; continue; }
        const auto mapping = AndroidPathMapper::buildUserdata(source->regularPaths());
        if (!mapping.valid) continue;
        int score = 0;
        for (const auto& [normalized, _] : mapping.normalizedToMember) {
            if (normalized.rfind("data/data/com.", 0) == 0) score += 3;
            else if (normalized.rfind("data/user/0/com.", 0) == 0) score += 2;
            else if (normalized == "data/system/packages.xml") score += 3;
            else if (normalized == "data/misc/wifi/WifiConfigStore.xml") score += 2;
        }
        if (score > bestScore) { bestScore = score; best = std::move(source); }
    }
    tsk_img_close(img);
    if (best) error.clear();
    return best;
}

FilesystemEvidenceFileExtractor::FilesystemEvidenceFileExtractor(
    std::string image, std::optional<std::uint64_t> expectedOffset)
    : image_(std::move(image)), expectedOffset_(expectedOffset) {}
bool FilesystemEvidenceFileExtractor::initialize() {
    source_ = openAndroidFilesystemImage(image_, error_, expectedOffset_);
    if (!source_) return false;
    if (sourceHash_.empty()) sourceHash_ = sha256(image_);
    if (sourceHash_.size() != 64) { error_ = "SOURCE_HASH_FAILED"; source_.reset(); return false; }
    const auto mapping = AndroidPathMapper::buildUserdata(source_->regularPaths());
    if (!mapping.valid) { error_ = mapping.reason; source_.reset(); return false; }
    normalizedToSource_ = std::map<std::string, std::string>(
        mapping.normalizedToMember.begin(), mapping.normalizedToMember.end());
    return true;
}
bool FilesystemEvidenceFileExtractor::extractFileByPath(const std::string& path,
                                                        const std::string& output) {
    error_.clear();
    std::string normalized;
    if (!source_ || !AndroidPathMapper::normalizeRequest(path, normalized)) return false;
    const auto it = normalizedToSource_.find(normalized);
    if (it == normalizedToSource_.end()) return false;
    const auto entry = source_->stat(it->second);
    if (!entry || entry->encrypted || entry->compressed || entry->nameState != "clear") {
        error_ = entry && entry->encrypted ? "ENCRYPTED_FILE" : "FILE_UNREADABLE";
        return false;
    }
    if (!source_->extractFileByPath(it->second, output)) {
        error_ = source_->sourceMetadata().error;
        return false;
    }
    AndroidSourceProvenance provenance;
    const auto metadata = source_->sourceMetadata();
    provenance.sourceContainer = image_;
    provenance.containerSha256 = sourceHash_;
    provenance.sourceMemberPath = it->second;
    provenance.normalizedAndroidPath = normalized;
    provenance.memberSize = entry->size;
    provenance.memberSha256 = sha256(output);
    if (provenance.memberSha256.size() != 64) {
        error_ = "EXTRACTED_FILE_HASH_FAILED";
        std::error_code ec;
        fs::remove(output, ec);
        return false;
    }
    provenance.adapterType = metadata.filesystemType + "-filesystem";
    provenance.adapterVersion = metadata.readerVersion;
    provenance.partitionNumber = metadata.partitionNumber;
    provenance.partitionName = metadata.partitionName;
    provenance.partitionStartOffset = metadata.partitionOffset;
    provenance.filesystemType = metadata.filesystemType;
    provenance.filesystemObjectId = std::to_string(entry->objectId);
    provenance.filesystemReader = metadata.reader;
    provenance.imageContainerType = metadata.containerType;
    used_.push_back(std::move(provenance));
    return true;
}
std::vector<std::string> FilesystemEvidenceFileExtractor::findPathsByFilename(
    const std::string& filename, std::size_t limit) const {
    std::vector<std::string> paths;
    if (filename.empty() || filename.find('/') != std::string::npos) return paths;
    for (const auto& [normalized, _] : normalizedToSource_) {
        if (fs::path(normalized).filename() == filename) {
            paths.push_back(normalized);
            if (paths.size() == limit) break;
        }
    }
    return paths;
}
FilesystemSourceMetadata FilesystemEvidenceFileExtractor::sourceMetadata() const {
    return source_ ? source_->sourceMetadata() : FilesystemSourceMetadata{};
}
std::vector<FilesystemEvidenceEntry> FilesystemEvidenceFileExtractor::entries() const {
    if (!source_) return {};
    std::vector<FilesystemEvidenceEntry> result;
    for (const auto& path : source_->regularPaths()) {
        auto entry = source_->stat(path);
        if (entry) result.push_back(std::move(*entry));
    }
    const auto unnamed = source_->unavailableNames();
    result.insert(result.end(), unnamed.begin(), unnamed.end());
    return result;
}
