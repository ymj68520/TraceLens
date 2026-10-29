// MeiyaBackupExtractor.cpp
// 美亚案件容器解码与索引。

#include "MeiyaBackupExtractor.h"

#include <sqlite3.h>

#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <system_error>

namespace fs = std::filesystem;

namespace meiya {
namespace {

// 在证据目录之外创建私有临时根，避免污染检材。
bool createTemporaryRoot(const fs::path& evidenceRoot, fs::path& out) {
    std::error_code error;
    const fs::path base = fs::temp_directory_path(error);
    if (error) return false;

    std::string pattern = (base / "tracelens-meiya-XXXXXX").string();
    std::vector<char> writable(pattern.begin(), pattern.end());
    writable.push_back('\0');
    char* created = mkdtemp(writable.data());
    if (!created) return false;
    out = fs::path(created);

    // 临时根绝不能落在证据目录内。
    std::error_code canonicalError;
    const auto evidence = fs::weakly_canonical(evidenceRoot, canonicalError);
    const auto temporary = fs::weakly_canonical(out, canonicalError);
    if (!canonicalError) {
        const auto relative = temporary.lexically_relative(evidence);
        if (!relative.empty() && *relative.begin() != "..") {
            fs::remove_all(out, canonicalError);
            return false;
        }
    }
    return true;
}

std::string sqlText(sqlite3_stmt* statement, int column) {
    const unsigned char* value = sqlite3_column_text(statement, column);
    return value ? reinterpret_cast<const char*>(value) : std::string{};
}

// 设备目录名即序列号（V1824BA / GM1910 / PBEM00）。
std::string deviceSerialFromPath(const fs::path& path) {
    return path.filename().string();
}

std::string stemSerial(const fs::path& file) {
    // GM1910.dmf → GM1910；V1824BA_RECORD_MFC.DB → V1824BA
    std::string name = file.stem().string();
    const std::string suffix = "_RECORD_MFC";
    if (name.size() > suffix.size() &&
        name.compare(name.size() - suffix.size(), suffix.size(), suffix) == 0) {
        name.erase(name.size() - suffix.size());
    }
    return name;
}

}  // namespace

MeiyaBackupExtractor::MeiyaBackupExtractor(std::string root) : root_(std::move(root)) {}

MeiyaBackupExtractor::~MeiyaBackupExtractor() {
    if (!temporaryRoot_.empty()) {
        std::error_code error;
        fs::remove_all(temporaryRoot_, error);
    }
}

bool MeiyaBackupExtractor::recognizes(const std::string& path) {
    std::error_code error;
    const fs::path root(path);
    if (fs::is_regular_file(root, error)) {
        const std::string name = root.filename().string();
        return name.size() > 3 &&
               name.compare(name.size() - 3, 3, ".mf") == 0 &&
               looksLikeEncryptedContainer(path);
    }
    if (!fs::is_directory(root, error)) return false;

    // 案件根：存在 <name>.mf
    for (const auto& entry : fs::directory_iterator(root, error)) {
        std::error_code entryError;
        if (!fs::is_regular_file(entry.path(), entryError)) continue;
        const std::string name = entry.path().filename().string();
        if (name.size() > 3 && name.compare(name.size() - 3, 3, ".mf") == 0) {
            return looksLikeEncryptedContainer(entry.path().string());
        }
    }
    // 设备目录：存在 <device>/<device>.dmf
    for (const auto& entry : fs::directory_iterator(root, error)) {
        std::error_code entryError;
        if (!fs::is_directory(entry.path(), entryError)) continue;
        const std::string device = entry.path().filename().string();
        const fs::path dmf = entry.path() / (device + ".dmf");
        if (fs::is_regular_file(dmf, entryError) &&
            looksLikeEncryptedContainer(dmf.string())) {
            return true;
        }
    }
    return false;
}

bool MeiyaBackupExtractor::initialize() {
    containers_.clear();
    devices_.clear();
    masks_.clear();
    error_.clear();

    std::error_code fsError;
    fs::path start(root_);
    if (fs::is_regular_file(start, fsError)) start = start.parent_path();
    if (!fs::is_directory(start, fsError)) {
        error_ = "not a directory: " + root_;
        return false;
    }
    caseRoot_ = start.string();

    std::vector<ContainerCandidate> candidates;
    if (!enumerateContainers(caseRoot_, candidates)) {
        error_ = "cannot enumerate containers under " + caseRoot_;
        return false;
    }
    if (candidates.empty()) {
        error_ = "no Meiya encrypted containers found";
        return false;
    }

    if (!createTemporaryRoot(start, temporaryRoot_)) {
        error_ = "cannot create an evidence-disjoint temporary root";
        return false;
    }

    // 同族共用掩码：先按 family 分组，再统一推导。
    std::map<std::string, std::vector<ContainerCandidate>> grouped;
    for (const auto& candidate : candidates) grouped[candidate.family].push_back(candidate);

    // 大容器（设备规范化库）优先推导：页数最多，统计最稳，也最能通过
    // SQLite 完整性校验。其余族先复用这个掩码，失败再各自推导。
    // 这样小容器（4 KB 的标记库、12 KB 的案件库）无需自带足够页。
    static const char* kPreferredOrder[] = {"device", "unknown", "appdb", "record",
                                            "mark", "case"};
    std::string sharedFamily;
    for (const char* family : kPreferredOrder) {
        const auto it = grouped.find(family);
        if (it == grouped.end()) continue;
        std::vector<fs::path> files;
        for (const auto& candidate : it->second) files.push_back(candidate.path);
        DerivedKey key;
        std::string derivationError;
        if (deriveMask(files, key, derivationError)) {
            masks_[family] = key;
            if (sharedFamily.empty()) sharedFamily = family;
        }
    }

    for (const auto& [family, members] : grouped) {
        if (masks_.count(family)) {
            decryptFamily(family, members);
            continue;
        }
        // 该族自身推导失败：尝试借用已解出的掩码（美亚同案件内掩码共享）。
        bool borrowed = false;
        for (const auto& [donorFamily, donorKey] : masks_) {
            if (canDecryptFamily(members, donorKey)) {
                masks_[family] = donorKey;
                masks_[family].label = donorKey.label + "+borrowed_from_" + donorFamily;
                borrowed = true;
                break;
            }
        }
        if (!borrowed) {
            masks_[family] = DerivedKey{};  // 空掩码 → decryptFamily 记录失败原因
        }
        decryptFamily(family, members);
    }

    // 读取设备摘要（尽力而为，失败不影响其他容器）。
    for (const auto& container : containers_) {
        if (container.family == "device" && container.status == "decrypted") {
            readDeviceSummary(container);
        }
    }

    const auto decrypted = std::count_if(containers_.begin(), containers_.end(),
        [](const DecryptedContainer& c) { return c.status == "decrypted"; });
    if (decrypted == 0) {
        error_ = "no container could be decoded";
        return false;
    }
    return true;
}

bool MeiyaBackupExtractor::canDecryptFamily(
    const std::vector<ContainerCandidate>& members, const DerivedKey& key) const {
    if (key.mask.size() != meiya::kMaskPeriod) return false;
    // 只要族内有一个成员能被该掩码解成合法 SQLite 即可认为共享。
    for (const auto& member : members) {
        std::ifstream input(member.path, std::ios::binary);
        if (!input) continue;
        std::vector<unsigned char> bytes(meiya::kMaskPeriod * 16);
        input.read(reinterpret_cast<char*>(bytes.data()),
                   static_cast<std::streamsize>(bytes.size()));
        bytes.resize(static_cast<std::size_t>(input.gcount()));
        if (bytes.empty()) continue;
        const auto decoded = meiya::decryptBytes(bytes, key.mask);
        std::size_t entries = 0;
        std::string error;
        // 只校验前 16 页：这是"这个掩码是否属于该族"的快速判据，最终仍以
        // 整容器 integrity_check 为准（decryptFamily 会逐容器复核）。
        if (meiya::validateSqlite(decoded, entries, error)) return true;
    }
    return false;
}

bool MeiyaBackupExtractor::decryptFamily(const std::string& family,
                                         const std::vector<ContainerCandidate>& candidates) {
    std::vector<fs::path> files;
    for (const auto& candidate : candidates) files.push_back(candidate.path);

    DerivedKey key;
    auto maskIt = masks_.find(family);
    const bool derived = maskIt != masks_.end() &&
                         maskIt->second.mask.size() == meiya::kMaskPeriod;
    if (derived) key = maskIt->second;

    for (std::size_t index = 0; index < candidates.size(); ++index) {
        const auto& candidate = candidates[index];
        DecryptedContainer container;
        container.sourcePath = candidate.path;
        container.family = family;
        container.containerSize = candidate.size;
        container.deviceSerial = deviceSerialFromPath(candidate.path.parent_path());

        if (!derived) {
            container.status = "failed";
            container.detail = "no usable mask for this container family";
            containers_.push_back(std::move(container));
            continue;
        }

        const std::string outputName =
            "container-" + std::to_string(containers_.size()) + ".db";
        const fs::path destination = temporaryRoot_ / outputName;
        if (!decryptFile(candidate.path.string(), destination.string(), key.mask)) {
            container.status = "failed";
            container.detail = "decrypt failed";
            containers_.push_back(std::move(container));
            continue;
        }

        // 逐容器复核必须覆盖整个文件：同族掩码在个别成员上仍可能不适用，
        // 而只看前几页会把"开头像"误判成"整库可读"。
        std::ifstream input(destination, std::ios::binary | std::ios::ate);
        const std::streamoff size = input.tellg();
        input.seekg(0, std::ios::beg);
        std::vector<unsigned char> image(static_cast<std::size_t>(size > 0 ? size : 0));
        if (!image.empty()) {
            input.read(reinterpret_cast<char*>(image.data()), size);
        }
        input.close();

        std::size_t entries = 0;
        std::string validationError;
        if (image.empty() || !validateSqlite(image, entries, validationError)) {
            std::error_code removeError;
            fs::remove(destination, removeError);
            container.status = "failed";
            container.detail = "container rejected by SQLite: " + validationError;
            containers_.push_back(std::move(container));
            continue;
        }

        container.decryptedPath = destination;
        container.encryptionLabel = key.label;
        container.schemaEntries = entries;
        container.status = "decrypted";
        container.detail = "mask=" + key.label + "; pages=" + std::to_string(key.pagesUsed);
        containers_.push_back(std::move(container));
    }
    return true;
}

void MeiyaBackupExtractor::readDeviceSummary(const DecryptedContainer& container) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(container.decryptedPath.string().c_str(), &db, SQLITE_OPEN_READONLY,
                        nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }

    DeviceSummary summary;
    summary.serial = stemSerial(container.sourcePath);
    summary.sourceContainer = container.sourcePath.filename().string();

    sqlite3_stmt* statement = nullptr;
    const char* sql =
        "SELECT MANUFACTURER, MODEL, IMEI_ESN_MEID, MAC, BLUETOOTH_MAC, CHARACTERISTIC_DESC "
        "FROM TBL_PR_DEVICE_INFO LIMIT 1";
    if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
        if (sqlite3_step(statement) == SQLITE_ROW) {
            summary.manufacturer = sqlText(statement, 0);
            summary.model = sqlText(statement, 1);
            summary.imei = sqlText(statement, 2);
            summary.mac = sqlText(statement, 3);
            summary.bluetoothMac = sqlText(statement, 4);
            summary.characteristic = sqlText(statement, 5);
        }
        sqlite3_finalize(statement);
    }
    sqlite3_close(db);
    devices_.push_back(std::move(summary));
}

const DecryptedContainer* MeiyaBackupExtractor::findContainer(const std::string& family) const {
    for (const auto& container : containers_) {
        if (container.family == family && container.status == "decrypted") return &container;
    }
    return nullptr;
}

std::vector<const DecryptedContainer*> MeiyaBackupExtractor::findContainers(
    const std::string& family) const {
    std::vector<const DecryptedContainer*> result;
    for (const auto& container : containers_) {
        if (container.family == family && container.status == "decrypted") result.push_back(&container);
    }
    return result;
}

}  // namespace meiya
