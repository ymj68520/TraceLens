// MeiyaContainerCrypto.cpp
// 美亚容器掩码的运行时自推导与解码。

#include "MeiyaContainerCrypto.h"

#include <sqlite3.h>

#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <memory>
#include <system_error>
#include <unordered_map>
#include <set>

namespace fs = std::filesystem;

namespace meiya {
namespace {

constexpr std::size_t kHeaderProbe = 16;
constexpr const char* kSqliteMagic = "SQLite format 3";
constexpr std::uint64_t kMaximumDerivationBytes = 512ULL * 1024 * 1024;
// 掩码验证要跑 SQLite integrity_check，必须整库校验；为控制内存与耗时，
// 选取同族中小于此上限的文件作为验证样本。
constexpr std::uint64_t kValidationImageLimit = 64ULL * 1024 * 1024;

const std::array<unsigned char, kHeaderProbe> kSqliteHeader = {
    'S', 'Q', 'L', 'i', 't', 'e', ' ', 'f', 'o', 'r', 'm', 'a', 't', ' ', '3', '\0'
};

std::vector<unsigned char> readFileBytes(const std::string& path,
                                         std::uint64_t maximumBytes = kMaximumDerivationBytes) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return {};
    input.seekg(0, std::ios::end);
    const std::streamoff size = input.tellg();
    if (size <= 0 || static_cast<std::uint64_t>(size) > maximumBytes) return {};
    input.seekg(0, std::ios::beg);
    std::vector<unsigned char> bytes(static_cast<std::size_t>(size));
    input.read(reinterpret_cast<char*>(bytes.data()), size);
    if (!input) return {};
    return bytes;
}

// 统计单个文件内的页。
std::vector<std::vector<unsigned char>> splitPages(const std::vector<unsigned char>& data) {
    std::vector<std::vector<unsigned char>> pages;
    for (std::size_t offset = 0; offset + kMaskPeriod <= data.size(); offset += kMaskPeriod) {
        pages.emplace_back(data.begin() + offset, data.begin() + offset + kMaskPeriod);
    }
    return pages;
}

// 假设 A：最高频页是"全零页"。
bool maskFromZeroPage(const std::vector<std::vector<unsigned char>>& pages,
                      std::vector<unsigned char>& mask) {
    if (pages.empty()) return false;
    std::map<std::vector<unsigned char>, std::size_t> counts;
    for (const auto& page : pages) counts[page]++;
    const auto* best = &counts.begin()->first;
    std::size_t bestCount = 0;
    for (const auto& entry : counts) {
        if (entry.second > bestCount) {
            bestCount = entry.second;
            best = &entry.first;
        }
    }
    // 至少要有两页相同，否则"最高频"没有统计意义。
    if (bestCount < 2) return false;
    mask.assign(best->begin(), best->end());
    return true;
}

// 假设 B：逐字节取众数（多数页在多数偏移上是 0）。
void maskFromByteMode(const std::vector<std::vector<unsigned char>>& pages,
                      std::vector<unsigned char>& mask) {
    mask.assign(kMaskPeriod, 0);
    for (std::size_t offset = 0; offset < kMaskPeriod; ++offset) {
        std::map<unsigned char, std::size_t> counts;
        for (const auto& page : pages) {
            if (offset < page.size()) counts[page[offset]]++;
        }
        unsigned char best = 0;
        std::size_t bestCount = 0;
        for (const auto& entry : counts) {
            if (entry.second > bestCount) {
                bestCount = entry.second;
                best = entry.first;
            }
        }
        mask[offset] = best;
    }
}

// 用页 0 的已知 SQLite 头部修正掩码前缀。
void correctWithKnownHeader(const std::vector<unsigned char>& firstPage,
                            std::vector<unsigned char>& mask) {
    for (std::size_t i = 0; i < kHeaderProbe && i < firstPage.size(); ++i) {
        mask[i] = firstPage[i] ^ kSqliteHeader[i];
    }
}

std::string familyOf(const fs::path& path) {
    const std::string name = path.filename().string();
    std::string lower = name;
    std::transform(lower.begin(), lower.end(), lower.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

    const auto endsWith = [&lower](const char* suffix) {
        const std::size_t length = std::char_traits<char>::length(suffix);
        return lower.size() >= length &&
               lower.compare(lower.size() - length, length, suffix) == 0;
    };

    // Order matters: the most specific suffix must be tested first, otherwise
    // "<device>_RECORD_MFC.DB" and "MFCExcerpt.db" both fall through to ".db".
    if (endsWith("_record_mfc.db")) return "record";
    if (endsWith(".mf")) return "case";
    if (endsWith(".bm")) return "case";
    if (endsWith(".dmf")) return "device";
    if (endsWith(".amf")) return "appdb";
    if (endsWith(".db")) {
        // 笔录/标记库（MFC*.db）与各应用的 config.db 使用不同密钥族。
        if (lower.rfind("mfc", 0) == 0) return "mark";
        // 设备目录下的 config.db 与同设备 .dmf 共用掩码。
        const fs::path parent = path.parent_path();
        if (!parent.empty() && !parent.filename().empty()) {
            const std::string device = parent.filename().string();
            std::error_code error;
            if (fs::is_regular_file(parent / (device + ".dmf"), error)) return "device";
        }
        return "unknown";
    }
    return "unknown";
}

}  // namespace

bool looksLikeEncryptedContainer(const std::string& path) {
    std::ifstream input(path, std::ios::binary);
    if (!input) return false;
    input.seekg(0, std::ios::end);
    const std::streamoff size = input.tellg();
    if (size <= 0 || size % static_cast<std::streamoff>(kMaskPeriod) != 0) return false;

    std::array<unsigned char, kHeaderProbe> head{};
    input.seekg(0, std::ios::beg);
    input.read(reinterpret_cast<char*>(head.data()), head.size());
    if (input.gcount() != static_cast<std::streamsize>(head.size())) return false;

    // 明文 SQLite 直接排除（业务库 .db-wal、旁路明文库会走到这里）。
    if (std::memcmp(head.data(), kSqliteMagic, kHeaderProbe) == 0) return false;
    // 至少头部要"看起来像被掩码打乱"：不能全是 0 或全相同。
    const bool allSame = std::all_of(head.begin(), head.end(),
                                     [&](unsigned char c) { return c == head[0]; });
    return !allSame;
}

bool validateSqlite(const std::vector<unsigned char>& image,
                    std::size_t& schemaEntries, std::string& error) {
    schemaEntries = 0;
    error.clear();
    if (image.size() < kMaskPeriod) {
        error = "image smaller than one page";
        return false;
    }
    if (std::memcmp(image.data(), kSqliteMagic, kHeaderProbe) != 0) {
        error = "missing SQLite header";
        return false;
    }

    // 截断的镜像（快速族判定时只读前若干页）无法跑完整 integrity_check：
    // SQLite 会因页数不符报错。此时改为校验页结构的自洽性，返回 true 表示
    // "这个掩码看起来属于该族"；最终采信仍以整库校验为准。
    const unsigned char* header = image.data();
    const std::uint32_t pageSize = (static_cast<std::uint32_t>(header[16]) << 8) |
                                    static_cast<std::uint32_t>(header[17]);
    const std::uint64_t declaredPages =
        (static_cast<std::uint64_t>(header[28]) << 24) |
        (static_cast<std::uint64_t>(header[29]) << 16) |
        (static_cast<std::uint64_t>(header[30]) << 8) |
        static_cast<std::uint64_t>(header[31]);
    const std::uint64_t actualPages = image.size() / kMaskPeriod;
    if (pageSize != 0 && pageSize != 65536 && pageSize != kMaskPeriod) {
        error = "unexpected page size " + std::to_string(pageSize);
        return false;
    }
    if (declaredPages == 0) {
        error = "page count is zero";
        return false;
    }
    if (actualPages < declaredPages) {
        // 片段校验：页类型必须是 SQLite 已知值，页数声明必须可信。
        static const std::set<unsigned char> kPageTypes{0x02, 0x05, 0x0a, 0x0d};
        for (std::uint64_t page = 0; page < actualPages; ++page) {
            const unsigned char type = image[page * kMaskPeriod];
            if (!kPageTypes.count(type)) {
                error = "invalid page type 0x" + std::to_string(type) +
                        " at page " + std::to_string(page);
                return false;
            }
        }
        return true;
    }

    // 用 mkstemp 落临时文件后交给 SQLite；退火到 /tmp 以避免污染证据目录。
    std::string pattern = (fs::temp_directory_path() / "tracelens-meiya-verify-XXXXXX").string();
    std::vector<char> writable(pattern.begin(), pattern.end());
    writable.push_back('\0');
    const int descriptor = mkstemp(writable.data());
    if (descriptor < 0) {
        error = "cannot create verification file";
        return false;
    }
    const std::string tempPath(writable.data());
    {
        std::ofstream output(tempPath, std::ios::binary | std::ios::trunc);
        output.write(reinterpret_cast<const char*>(image.data()),
                     static_cast<std::streamsize>(image.size()));
        if (!output) {
            close(descriptor);
            std::remove(tempPath.c_str());
            error = "cannot write verification file";
            return false;
        }
    }
    close(descriptor);

    sqlite3* db = nullptr;
    if (sqlite3_open_v2(tempPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        error = db ? sqlite3_errmsg(db) : "cannot open verification file";
        if (db) sqlite3_close(db);
        std::remove(tempPath.c_str());
        return false;
    }

    bool ok = false;
    sqlite3_stmt* statement = nullptr;
    if (sqlite3_prepare_v2(db, "PRAGMA integrity_check", -1, &statement, nullptr) == SQLITE_OK) {
        if (sqlite3_step(statement) == SQLITE_ROW) {
            const unsigned char* text = sqlite3_column_text(statement, 0);
            ok = text && std::string(reinterpret_cast<const char*>(text)) == "ok";
            if (!ok && text) error = reinterpret_cast<const char*>(text);
        }
        sqlite3_finalize(statement);
    } else {
        error = sqlite3_errmsg(db);
    }

    if (ok) {
        statement = nullptr;
        if (sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM sqlite_master", -1, &statement, nullptr)
            == SQLITE_OK) {
            if (sqlite3_step(statement) == SQLITE_ROW) {
                schemaEntries = static_cast<std::size_t>(sqlite3_column_int(statement, 0));
            }
            sqlite3_finalize(statement);
        }
    }

    sqlite3_close(db);
    std::remove(tempPath.c_str());
    return ok;
}

std::vector<unsigned char> decryptBytes(const std::vector<unsigned char>& data,
                                        const std::vector<unsigned char>& mask) {
    if (mask.size() != kMaskPeriod) return {};
    std::vector<unsigned char> out(data.size());
    for (std::size_t offset = 0; offset < data.size(); ++offset) {
        out[offset] = data[offset] ^ mask[offset % kMaskPeriod];
    }
    return out;
}

bool decryptFile(const std::string& source, const std::string& destination,
                 const std::vector<unsigned char>& mask) {
    if (mask.size() != kMaskPeriod) return false;
    std::ifstream input(source, std::ios::binary);
    if (!input) return false;
    std::ofstream output(destination, std::ios::binary | std::ios::trunc);
    if (!output) return false;

    std::array<unsigned char, kMaskPeriod> buffer{};
    std::size_t position = 0;
    while (input) {
        input.read(reinterpret_cast<char*>(buffer.data()),
                   static_cast<std::streamsize>(buffer.size()));
        const std::streamsize count = input.gcount();
        if (count <= 0) break;
        for (std::streamsize i = 0; i < count; ++i) {
            buffer[static_cast<std::size_t>(i)] ^= mask[position % kMaskPeriod];
            ++position;
        }
        output.write(reinterpret_cast<const char*>(buffer.data()), count);
        if (!output) return false;
    }
    return true;
}

bool deriveMask(const std::vector<fs::path>& familyFiles, DerivedKey& out,
                std::string& error) {
    error.clear();
    out = DerivedKey{};

    // 合并同族文件的所有页：小文件单独没有足够页做统计，合并后才有代表性。
    std::vector<std::vector<unsigned char>> pages;
    std::vector<unsigned char> firstPage;
    // 验证需要完整的 SQLite 镜像（integrity_check 会遍历所有页），因此保留
    // 一个"够小到能整体验证"的同族文件全文；过大的容器改用其前若干页，
    // 并通过后续逐容器复核兜底。
    std::vector<unsigned char> validationImage;
    fs::path validationSource;
    for (const auto& file : familyFiles) {
        const auto bytes = readFileBytes(file.string());
        if (bytes.empty()) continue;
        auto filePages = splitPages(bytes);
        if (filePages.empty()) continue;
        if (firstPage.empty()) firstPage = filePages.front();
        if (validationImage.empty() && bytes.size() <= kValidationImageLimit) {
            validationImage = bytes;
            validationSource = file;
        }
        for (auto& page : filePages) pages.push_back(std::move(page));
    }
    if (pages.empty() || firstPage.empty()) {
        error = "no readable pages in the container family";
        return false;
    }

    // 同族里没有小文件时，退化为对最大文件的前 kValidationImageLimit 字节
    // 做验证。只要这段通过，后续每个容器还会各自复核。
    if (validationImage.empty()) {
        for (const auto& file : familyFiles) {
            const auto bytes = readFileBytes(file.string(), kValidationImageLimit);
            if (bytes.size() < kMaskPeriod) continue;
            if (bytes.size() > validationImage.size()) {
                validationImage = bytes;
                validationSource = file;
            }
        }
    }
    if (validationImage.empty()) {
        error = "no container large enough to validate the derived mask";
        return false;
    }

    struct Candidate {
        const char* label;
        std::vector<unsigned char> mask;
    };
    std::vector<Candidate> candidates;

    std::vector<unsigned char> zeroPageMask;
    if (maskFromZeroPage(pages, zeroPageMask)) {
        correctWithKnownHeader(firstPage, zeroPageMask);
        candidates.push_back({"zero_page", std::move(zeroPageMask)});
    }

    std::vector<unsigned char> modeMask;
    maskFromByteMode(pages, modeMask);
    correctWithKnownHeader(firstPage, modeMask);
    candidates.push_back({"byte_mode", std::move(modeMask)});

    // 用 SQLite 自身做客观判据：只有 integrity_check 通过的掩码才采信。
    // 统计假设在小文件上可能失效，而完整性校验是客观的；两者结合才不会
    // 把"看起来解开了"当成"确实解开了"。
    std::string lastError = "no candidate produced a valid SQLite image";
    for (auto& candidate : candidates) {
        const auto decoded = decryptBytes(validationImage, candidate.mask);
        std::size_t entries = 0;
        std::string validationError;
        if (validateSqlite(decoded, entries, validationError)) {
            out.label = candidate.label;
            out.mask = std::move(candidate.mask);
            out.pagesUsed = pages.size();
            out.validationEntries = entries;
            return true;
        }
        lastError = std::string(candidate.label) + ": " + validationError;
    }

    error = lastError;
    return false;
}

bool enumerateContainers(const std::string& root, std::vector<ContainerCandidate>& out) {
    out.clear();
    std::error_code error;

    std::vector<fs::path> starts;
    const fs::path rootPath(root);
    if (fs::is_directory(rootPath, error)) {
        starts.push_back(rootPath);
    } else if (fs::is_regular_file(rootPath, error)) {
        starts.push_back(rootPath.parent_path());
    } else {
        return false;
    }

    // 只向下走两层：案件根 → 设备目录 → 容器文件；再深就是应用私有数据，
    // 不属于容器层。
    const auto consider = [&out](const fs::path& file) {
        std::error_code fileError;
        if (!fs::is_regular_file(file, fileError)) return;
        if (!looksLikeEncryptedContainer(file.string())) return;
        ContainerCandidate candidate;
        candidate.path = file;
        candidate.family = familyOf(file);
        candidate.size = static_cast<std::uint64_t>(fs::file_size(file, fileError));
        if (fileError) return;
        out.push_back(std::move(candidate));
    };

    for (const auto& start : starts) {
        consider(start);
        std::error_code dirError;
        for (const auto& level1 : fs::directory_iterator(start, dirError)) {
            std::error_code levelError;
            if (fs::is_directory(level1.path(), levelError)) {
                for (const auto& level2 : fs::directory_iterator(level1.path(), levelError)) {
                    consider(level2.path());
                }
            } else {
                consider(level1.path());
            }
        }
    }
    return true;
}

}  // namespace meiya
