#include "HarmonyBackupExtractor.h"
#include <archive.h>
#include <archive_entry.h>
#include <openssl/evp.h>
#include <algorithm>
#include <array>
#include <fstream>
#include <iomanip>
#include <memory>
#include <set>
#include <sstream>

namespace fs = std::filesystem;
using json = nlohmann::json;
namespace {
constexpr std::uint64_t maxMember = 8ULL << 30;
constexpr std::size_t maxEntries = 500000;
std::int64_t stamp(const fs::path& p) { return fs::last_write_time(p).time_since_epoch().count(); }
bool component(const std::string& s) {
    return !s.empty() && s != "." && s != ".." && s.size() < 256 &&
        s.find_first_of("/\\:\0", 0, 4) == std::string::npos;
}
// Byte-preserving, ASCII-safe paths also preserve names that are not UTF-8.
std::string encode(const std::string& s) {
    static const char* hex = "0123456789ABCDEF";
    std::string out;
    for (unsigned char c : s) {
        if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') || c == '/' || c == '.' || c == '_' || c == '-') out += c;
        else { out += '%'; out += hex[c >> 4]; out += hex[c & 15]; }
    }
    return out;
}
std::string originalDisplay(const std::string& s) {
    try { (void)json(s).dump(); return s; } catch (...) { return encode(s); }
}
bool validOriginal(const std::string& s) {
    if (s.empty() || s.size() > 8192 || s.find('\0') != std::string::npos ||
        s.find('\\') != std::string::npos || s.find("//") != std::string::npos) return false;
    if (s.rfind("/data/storage/", 0) != 0 && s.rfind("/storage/", 0) != 0) return false;
    for (const auto& part : fs::path(s).relative_path())
        if (part == ".." || part == ".") return false;
    return true;
}
json readJson(const fs::path& p) {
    if (fs::file_size(p) > (8ULL << 20)) throw std::runtime_error("MANIFEST_TOO_LARGE");
    std::ifstream f(p, std::ios::binary);
    return json::parse(f);
}
std::string col(sqlite3_stmt* s, int i) {
    const auto* p = sqlite3_column_text(s, i);
    return p ? reinterpret_cast<const char*>(p) : "";
}
std::string hexDigest(const unsigned char* bytes, unsigned size) {
    std::ostringstream s; s << std::hex << std::setfill('0');
    for (unsigned i = 0; i < size; ++i) s << std::setw(2) << unsigned(bytes[i]);
    return s.str();
}
}

HarmonyBackupExtractor::HarmonyBackupExtractor(std::string root) : root_(std::move(root)) {}
bool HarmonyBackupExtractor::recognizes(const std::string& root) {
    try {
        const fs::path p(root);
        if (!fs::is_directory(p / "files") || !fs::is_regular_file(p / ".info.json")) return false;
        auto j = readJson(p / ".info.json");
        return j.contains("BackupFileHeaderInfo") && j["BackupFileHeaderInfo"].is_object() &&
            j.contains("BackupFileModuleInfo") && j["BackupFileModuleInfo"].is_array();
    } catch (...) { return false; }
}
std::string HarmonyBackupExtractor::scopedPath(const std::string& bundle, int index, const std::string& original) {
    if (!component(bundle) || index < 0 || !validOriginal(original)) return {};
    return "/harmony/" + encode(bundle) + "/" + std::to_string(index) + encode(original);
}
void HarmonyBackupExtractor::setProgress(std::function<void(std::size_t)> p, std::function<bool()> c) {
    progress_ = std::move(p); cancelled_ = std::move(c);
}
bool HarmonyBackupExtractor::safeFile(const fs::path& p) const {
    try {
        auto rel = fs::absolute(p).lexically_normal().lexically_relative(root_);
        if (rel.empty() || rel.is_absolute()) return false;
        fs::path at = root_;
        for (const auto& part : rel) {
            if (part == ".." || part == ".") return false;
            at /= part;
            if (fs::is_symlink(fs::symlink_status(at))) return false;
        }
        return fs::is_regular_file(at);
    } catch (...) { return false; }
}
void HarmonyBackupExtractor::record(const std::string& path, const std::string& status, const std::string& detail) {
    coverage_.push_back({{"path", originalDisplay(path)}, {"status", status}, {"detail", detail}});
}
bool HarmonyBackupExtractor::addEntry(Entry e) {
    if (cancelled_ && cancelled_()) throw std::runtime_error("CANCELLED");
    if (entries_.size() >= maxEntries || e.size > maxMember) throw std::runtime_error("HARMONY_LIMIT_EXCEEDED");
    if (e.path.empty()) { record(e.originalPath, "UNSUPPORTED", "unsafe_or_unknown_source_path"); return false; }
    if (ambiguous_.count(e.path)) return false;
    if (entries_.count(e.path)) {
        entries_.erase(e.path); ambiguous_[e.path] = true;
        record(e.path, "AMBIGUOUS", "duplicate_path_within_application"); return false;
    }
    entries_.emplace(e.path, std::move(e));
    if (progress_ && entries_.size() % 256 == 0) progress_(entries_.size());
    return true;
}
bool HarmonyBackupExtractor::indexTar(const fs::path& path, const std::string& bundle, int index) {
    std::unique_ptr<archive, decltype(&archive_read_free)> a(archive_read_new(), archive_read_free);
    archive_read_support_format_tar(a.get()); archive_read_support_filter_none(a.get());
    if (archive_read_open_filename(a.get(), path.string().c_str(), 65536) != ARCHIVE_OK) return false;
    archive_entry* item = nullptr;
    int rc;
    const auto relative = path.lexically_relative(root_).generic_string();
    const auto bytes = fs::file_size(path); const auto time = stamp(path);
    while ((rc = archive_read_next_header(a.get(), &item)) == ARCHIVE_OK) {
        if (cancelled_ && cancelled_()) throw std::runtime_error("CANCELLED");
        if (archive_entry_filetype(item) != AE_IFREG || archive_entry_symlink(item) || archive_entry_hardlink(item)) {
            archive_read_data_skip(a.get()); continue;
        }
        const char* raw = archive_entry_pathname(item);
        if (!raw || !archive_entry_size_is_set(item) || archive_entry_size(item) < 0) return false;
        Entry e;
        e.bundle = bundle; e.appIndex = index; e.originalPath = originalDisplay(raw);
        e.path = scopedPath(bundle, index, raw); e.container = relative;
        // Uncompressed TAR only. libarchive counts consumed bytes, after GNU/PAX
        // headers; this supports bounded random reads without re-scanning archives.
        const auto offset = archive_filter_bytes(a.get(), 0);
        if (offset < 0) return false;
        e.offset = static_cast<std::uint64_t>(offset); e.size = archive_entry_size(item);
        e.modified = archive_entry_mtime(item); e.containerSize = bytes; e.containerTime = time;
        if (e.offset > bytes || e.size > bytes - e.offset) return false;
        addEntry(std::move(e));
        if (archive_read_data_skip(a.get()) != ARCHIVE_OK) return false;
    }
    return rc == ARCHIVE_EOF;
}
bool HarmonyBackupExtractor::initialize() {
    entries_.clear(); used_.clear(); hashes_.clear(); ambiguous_.clear(); coverage_ = json::array(); error_.clear();
    try {
        root_ = fs::absolute(root_).lexically_normal();
        if (fs::is_symlink(fs::symlink_status(root_)) || !safeFile(root_ / ".info.json") || !recognizes(root_.string()))
            throw std::runtime_error("INVALID_HARMONY_BACKUP");
        auto info = readJson(root_ / ".info.json");
        // Do not copy backupKey/password metadata into results or prompts.
        manifest_ = {{"platform", "HarmonyOS"}, {"adapter_version", "harmony-decrypted-v1"},
            {"device", info["BackupFileHeaderInfo"].value("deviceModel", "")},
            {"backup_time_ms", info["BackupFileHeaderInfo"].value("backupTime", 0LL)},
            {"backup_version", info.value("BackupFileVersionInfo", json::object()).value("versionName", "")},
            {"manifest_sha256", sha256(root_ / ".info.json")}, {"modules", json::array()},
            {"source_manifests", json::object()}, {"containers", json::object()}};
        if (info["BackupFileModuleInfo"].size() > 10000) throw std::runtime_error("HARMONY_MODULE_LIMIT");
        std::set<std::string> moduleOwners;
        for (const auto& module : info["BackupFileModuleInfo"]) {
            const auto bundle = module.value("moduleName", ""); const int index = module.value("appIndex", 0);
            if (!component(bundle) || index < 0) throw std::runtime_error("INVALID_HARMONY_MODULE");
            // This layout has one folder per bundle. Do not attribute the same
            // folder to multiple cloned app instances merely because appIndex differs.
            if (!moduleOwners.insert(bundle).second) throw std::runtime_error("AMBIGUOUS_HARMONY_MODULE");
            json app = {{"bundle", bundle}, {"app_index", index}, {"name", module.value("appName", "")},
                {"version", module.value("bundleVersionName", "")}, {"version_code", module.value("bundleVersionCode", 0LL)},
                {"type", module.value("module_type", "")}, {"declared_size", module.value("bundleDataSize", 0LL)}};
            manifest_["modules"].push_back(app);
            fs::path dir;
            for (const auto* category : {"BASIC", "SYSTEM", "APPLICATION"}) {
                auto candidate = root_ / "files" / category / bundle;
                if (fs::is_directory(candidate)) {
                    if (!dir.empty()) throw std::runtime_error("AMBIGUOUS_HARMONY_MODULE");
                    dir = candidate;
                }
            }
            const std::string appPath = "/harmony/" + encode(bundle) + "/" + std::to_string(index);
            fs::path mp = dir / "manage.jsonx";
            if (dir.empty() || !safeFile(mp)) mp = dir / "manage.json";
            if (dir.empty() || !safeFile(mp)) { record(appPath, "NOT_PRESENT", "module_metadata_only"); continue; }
            json list;
            try { list = readJson(mp); } catch (...) { record(appPath, "LOCKED", "no_readable_decrypted_manifest"); continue; }
            manifest_["source_manifests"][mp.lexically_relative(root_).generic_string()] = sha256(mp);
            if (list.is_null() || (list.is_array() && list.empty())) { record(appPath, "parsed", "empty_manifest"); continue; }
            if (!list.is_array() || list.size() > 100000) throw std::runtime_error("INVALID_HARMONY_MANIFEST");
            for (const auto& item : list) {
                const std::string name = item.value("fileName", "");
                if (!component(name)) throw std::runtime_error("UNSAFE_HARMONY_FILENAME");
                auto file = dir / (name + "x");
                if (!safeFile(file)) file = dir / name;
                if (!safeFile(file)) { record(appPath + "/" + encode(name), "NOT_FOUND", "manifest_member_missing"); continue; }
                const auto details = item.value("information", json::object());
                const auto original = details.value("path", "");
                auto st = details.value("stat", json::object());
                const auto expected = st.value("st_size", -1LL);
                if (expected < 0 || static_cast<std::uint64_t>(expected) != fs::file_size(file)) {
                    record(appPath + "/" + encode(name), "LOCKED", "plaintext_size_mismatch_or_encrypted_source"); continue;
                }
                if (!item.value("isBigFile", false) && name.ends_with(".tar")) {
                    if (!indexTar(file, bundle, index)) throw std::runtime_error("MALFORMED_HARMONY_TAR: " + name);
                } else {
                    Entry e;
                    e.bundle = bundle; e.appIndex = index; e.originalPath = originalDisplay(original);
                    e.path = scopedPath(bundle, index, original); e.container = file.lexically_relative(root_).generic_string();
                    e.size = fs::file_size(file); e.containerSize = e.size; e.containerTime = stamp(file);
                    e.modified = st.value("st_mtim", json::object()).value("tv_sec", 0LL);
                    addEntry(std::move(e));
                }
            }
            record(appPath, "parsed", "manifest_indexed; application_content_not_asserted_parsed");
        }
        // An orphan service payload is not silently interpreted as a database.
        auto service = root_ / "files/SYSTEM/1120/1120_sa.data";
        if (safeFile(service)) record("/harmony/1120/0/1120_sa.data", "UNSUPPORTED", "opaque_service_payload");
        if (entries_.empty()) throw std::runtime_error("HARMONY_NO_READABLE_FILES");
        for (const auto& [_, e] : entries_) {
            if (manifest_["containers"].contains(e.container)) continue;
            if (cancelled_ && cancelled_()) throw std::runtime_error("CANCELLED");
            const auto file = root_ / e.container;
            auto hash = sha256(file);
            if (hash.empty() || stamp(file) != e.containerTime || fs::file_size(file) != static_cast<std::uint64_t>(e.containerSize))
                throw std::runtime_error("EVIDENCE_CHANGED_DURING_INDEX");
            manifest_["containers"][e.container] = hash;
            if (progress_) progress_(entries_.size());
        }
        if (progress_) progress_(entries_.size());
        return true;
    } catch (const std::exception& e) { error_ = e.what(); return false; }
}
std::string HarmonyBackupExtractor::sha256(const fs::path& path) {
    std::ifstream f(path, std::ios::binary); if (!f) return {};
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> c(EVP_MD_CTX_new(), EVP_MD_CTX_free);
    if (!c || EVP_DigestInit_ex(c.get(), EVP_sha256(), nullptr) != 1) return {};
    std::array<char, 1 << 20> b{};
    while (f) { f.read(b.data(), b.size()); if (f.gcount() && EVP_DigestUpdate(c.get(), b.data(), f.gcount()) != 1) return {}; }
    if (f.bad()) return {};
    unsigned char digest[EVP_MAX_MD_SIZE]; unsigned size = 0;
    if (EVP_DigestFinal_ex(c.get(), digest, &size) != 1) return {};
    return hexDigest(digest, size);
}
bool HarmonyBackupExtractor::verifyIntegrity() {
    try {
        if (sha256(root_/".info.json") != manifest_.at("manifest_sha256").get<std::string>()) return false;
        for (const auto* group : {"source_manifests", "containers"}) {
            for (const auto& [path, hash] : manifest_.at(group).items()) {
                if (cancelled_ && cancelled_()) { error_="CANCELLED"; return false; }
                if (!safeFile(root_/path) || sha256(root_/path)!=hash.get<std::string>()) {
                    error_="EVIDENCE_CHANGED_AFTER_INDEX"; return false;
                }
                if (progress_) progress_(entries_.size());
            }
        }
        return true;
    } catch (...) { error_="EVIDENCE_CHANGED_AFTER_INDEX"; return false; }
}
bool HarmonyBackupExtractor::extractFileByPath(const std::string& path, const std::string& output) {
    try {
        const auto found = entries_.find(path.starts_with('/') ? path : "/" + path);
        if (found == entries_.end()) return false;
        const auto& e = found->second; auto source = root_ / e.container;
        if (!safeFile(source) || fs::file_size(source) != static_cast<std::uint64_t>(e.containerSize) || stamp(source) != e.containerTime)
            throw std::runtime_error("EVIDENCE_CHANGED_AFTER_INDEX");
        auto dest = fs::absolute(output).lexically_normal();
        auto rel = fs::weakly_canonical(dest).lexically_relative(fs::weakly_canonical(root_));
        if (!rel.empty() && *rel.begin() != "..") return false;
        if (fs::is_symlink(fs::symlink_status(dest))) return false;
        fs::create_directories(dest.parent_path());
        std::ifstream in(source, std::ios::binary); in.seekg(e.offset);
        std::ofstream out(dest, std::ios::binary | std::ios::trunc);
        if (!in || !out) return false;
        std::array<char, 1 << 16> data{}; std::uint64_t left = e.size;
        while (left) {
            if (cancelled_ && cancelled_()) throw std::runtime_error("CANCELLED");
            auto n = static_cast<std::streamsize>(std::min<std::uint64_t>(left, data.size()));
            in.read(data.data(), n); if (in.gcount() != n) throw std::runtime_error("SHORT_HARMONY_READ");
            out.write(data.data(), n); if (!out) throw std::runtime_error("HARMONY_OUTPUT_FAILED"); left -= n;
        }
        out.close(); if (!out) return false;
        auto& hash = hashes_[e.container]; if (hash.empty()) hash = sha256(source);
        if (hash.empty() || hash != manifest_.at("containers").value(e.container, "") ||
            stamp(source) != e.containerTime || fs::file_size(source) != static_cast<std::uint64_t>(e.containerSize))
            throw std::runtime_error("EVIDENCE_CHANGED_DURING_READ");
        used_[e.path] = {source.string(), hash, e.originalPath, e.path,
            static_cast<std::size_t>(e.size), sha256(dest), "harmony-backup", "harmony-decrypted-v1"};
        if (progress_) progress_(used_.size());
        return true;
    } catch (const std::exception& e) { error_ = e.what(); return false; }
}
bool HarmonyBackupExtractor::readRange(const std::string& path,std::uint64_t offset,std::size_t length,std::string& data,std::string& error) {
    data.clear();error.clear();
    try {
        const auto& e=entries_.at(path);const auto file=root_/e.container;
        if(length>65536 || offset>e.size)throw std::runtime_error("SOURCE_RANGE_INVALID");
        if(!safeFile(file) || fs::file_size(file)!=static_cast<std::uint64_t>(e.containerSize) || stamp(file)!=e.containerTime)
            throw std::runtime_error("EVIDENCE_CHANGED_AFTER_INDEX");
        length=std::min<std::uint64_t>(length,e.size-offset);
        if(e.offset>UINT64_MAX-offset)throw std::runtime_error("SOURCE_RANGE_INVALID");
        std::ifstream in(file,std::ios::binary);in.seekg(e.offset+offset);data.resize(length);
        if(length){in.read(data.data(),length);if(in.gcount()!=static_cast<std::streamsize>(length))throw std::runtime_error("SOURCE_RANGE_READ_FAILED");}
        return true;
    }catch(const std::exception& e){data.clear();error=e.what();return false;}
}
std::vector<std::string> HarmonyBackupExtractor::findPathsByFilename(const std::string& name, std::size_t limit) const {
    std::vector<std::string> out;
    for (const auto& [path, entry] : entries_) {
        if (out.size() >= limit) break;
        if (fs::path(path).filename() == encode(name)) out.push_back(path);
    }
    return out;
}
std::vector<AndroidSourceProvenance> HarmonyBackupExtractor::usedSourceProvenance() const {
    std::vector<AndroidSourceProvenance> result;
    for (const auto& [_, p] : used_) result.push_back(p);
    return result;
}
bool HarmonyBackupExtractor::saveIndex(sqlite3* db) const {
    const char* schema = "CREATE TABLE IF NOT EXISTS harmony_source_meta(key TEXT PRIMARY KEY,value TEXT);"
        "CREATE TABLE IF NOT EXISTS harmony_source_files(path TEXT PRIMARY KEY,bundle TEXT,app_index INTEGER,"
        "original_path TEXT,container TEXT,data_offset INTEGER,size INTEGER,mtime INTEGER,container_size INTEGER,container_time INTEGER);";
    if (sqlite3_exec(db, schema, nullptr, nullptr, nullptr) != SQLITE_OK) return false;
    sqlite3_stmt* s = nullptr;
    if (sqlite3_prepare_v2(db, "INSERT OR REPLACE INTO harmony_source_meta VALUES(?,?)", -1, &s, nullptr) != SQLITE_OK) return false;
    for (const auto& [k,v] : std::map<std::string,std::string>{{"root",root_.string()},{"manifest",manifest_.dump()},{"coverage",coverage_.dump()}}) {
        sqlite3_bind_text(s,1,k.c_str(),-1,SQLITE_TRANSIENT); sqlite3_bind_text(s,2,v.c_str(),-1,SQLITE_TRANSIENT);
        if (sqlite3_step(s)!=SQLITE_DONE) { sqlite3_finalize(s); return false; } sqlite3_reset(s);
    }
    sqlite3_finalize(s);
    if (sqlite3_prepare_v2(db, "INSERT OR REPLACE INTO harmony_source_files VALUES(?,?,?,?,?,?,?,?,?,?)", -1, &s, nullptr)!=SQLITE_OK) return false;
    for (const auto& [path,e] : entries_) {
        sqlite3_bind_text(s,1,path.c_str(),-1,SQLITE_TRANSIENT); sqlite3_bind_text(s,2,e.bundle.c_str(),-1,SQLITE_TRANSIENT);
        sqlite3_bind_int(s,3,e.appIndex); sqlite3_bind_text(s,4,e.originalPath.c_str(),-1,SQLITE_TRANSIENT);
        sqlite3_bind_text(s,5,e.container.c_str(),-1,SQLITE_TRANSIENT); sqlite3_bind_int64(s,6,e.offset);
        sqlite3_bind_int64(s,7,e.size); sqlite3_bind_int64(s,8,e.modified);
        sqlite3_bind_int64(s,9,e.containerSize); sqlite3_bind_int64(s,10,e.containerTime);
        if (sqlite3_step(s)!=SQLITE_DONE) { sqlite3_finalize(s); return false; } sqlite3_reset(s);
    }
    sqlite3_finalize(s); return true;
}
bool HarmonyBackupExtractor::loadIndex(sqlite3* db) {
    try {
        root_ = fs::absolute(root_).lexically_normal();
        sqlite3_stmt* s = nullptr;
        if (sqlite3_prepare_v2(db,"SELECT key,value FROM harmony_source_meta",-1,&s,nullptr)!=SQLITE_OK) return false;
        std::map<std::string,std::string> meta;
        while(sqlite3_step(s)==SQLITE_ROW) meta[col(s,0)]=col(s,1);
        sqlite3_finalize(s);
        if (meta["root"] != root_.string()) return false;
        manifest_=json::parse(meta.at("manifest")); coverage_=json::parse(meta.at("coverage"));
        if (!safeFile(root_/".info.json") || sha256(root_/".info.json")!=manifest_.value("manifest_sha256", "")) return false;
        for (const auto& [path, hash] : manifest_.at("source_manifests").items())
            if (!safeFile(root_/path) || sha256(root_/path) != hash.get<std::string>()) return false;
        if (sqlite3_prepare_v2(db,"SELECT * FROM harmony_source_files ORDER BY path",-1,&s,nullptr)!=SQLITE_OK) return false;
        entries_.clear();
        while(sqlite3_step(s)==SQLITE_ROW) {
            Entry e; e.path=col(s,0);e.bundle=col(s,1);e.appIndex=sqlite3_column_int(s,2);e.originalPath=col(s,3);e.container=col(s,4);
            e.offset=sqlite3_column_int64(s,5);e.size=sqlite3_column_int64(s,6);e.modified=sqlite3_column_int64(s,7);
            e.containerSize=sqlite3_column_int64(s,8);e.containerTime=sqlite3_column_int64(s,9);
            entries_.emplace(e.path,std::move(e));
        }
        sqlite3_finalize(s); return !entries_.empty();
    } catch (...) { return false; }
}
