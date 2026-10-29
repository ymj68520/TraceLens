#include "ThunderForensicArtifactParsers.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileBackupSchema.h"
#include "MobileEvidenceAnalysis.h"
#include "MobileEvidencePackage.h"
#include "ThunderForensicBackupExtractor.h"
#include "ThunderForensicCaseDatabase.h"

#include <openssl/evp.h>
#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <vector>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

constexpr const char* kParserVersion = "thunderforensic-v2";
constexpr const char* kManifestMember = "ThunderForensic.json";
constexpr const char* kPhoneDataPrefix = "PhoneData/";
constexpr const char* kLogDataPrefix = "LogData/";
constexpr const char* kWifiXmlMember = "wifi.xml";
// Bounds artifact growth for a hostile or runaway container.
constexpr std::size_t kMaxArtifactRows = 1000000;
constexpr std::uint64_t kMaxMemberJsonBytes = 64ULL << 20;
constexpr std::size_t kMaxAppContainers = 2000;
constexpr std::size_t kMaxAppDatabaseRows = 20000;
constexpr std::size_t kMaxZipEntries = 10000;

std::string toLower(std::string value);

std::string scalar(const json& item, std::initializer_list<const char*> keys) {
    for (const char* key : keys) {
        if (!item.contains(key) || item[key].is_null()) continue;
        const json& value = item[key];
        if (value.is_string()) return value.get<std::string>();
        return value.dump();
    }
    return {};
}

std::string serialized(const json& value) {
    return value.dump(-1, ' ', false, json::error_handler_t::replace);
}

std::uint64_t numberValue(const json& item, std::initializer_list<const char*> keys) {
    for (const char* key : keys) {
        if (!item.contains(key) || item[key].is_null()) continue;
        const json& value = item[key];
        try {
            if (value.is_number_unsigned()) return value.get<std::uint64_t>();
            if (value.is_number_integer()) {
                const auto signedValue = value.get<std::int64_t>();
                return signedValue > 0 ? static_cast<std::uint64_t>(signedValue) : 0;
            }
            if (value.is_string()) return std::stoull(value.get<std::string>());
        } catch (const std::exception&) {
        }
    }
    return 0;
}

// Days-from-civil (Howard Hinnant) to avoid locale-dependent time parsing.
std::int64_t daysFromCivil(std::int64_t year, unsigned month, unsigned day) {
    year -= month <= 2;
    const std::int64_t era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yearOfEra = static_cast<unsigned>(year - era * 400);
    const unsigned dayOfYear = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
    const unsigned dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear;
    return era * 146097 + static_cast<std::int64_t>(dayOfEra) - 719468;
}

bool readUtcParts(const std::string& text, std::int64_t& epochSeconds) {
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
    char separator = 0;
    std::istringstream in(text);
    in >> year;
    if (in.peek() != '-') return false;
    in.ignore();
    in >> month;
    if (in.peek() != '-') return false;
    in.ignore();
    in >> day;
    in >> separator;
    if (separator != 'T' && separator != ' ') return false;
    in >> hour;
    if (in.peek() != ':') return false;
    in.ignore();
    in >> minute;
    if (in.peek() != ':') return false;
    in.ignore();
    in >> second;
    if (in.fail() || month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 ||
        second > 60)
        return false;
    std::int64_t days = daysFromCivil(year, static_cast<unsigned>(month),
                                      static_cast<unsigned>(day));
    epochSeconds = days * 86400 + hour * 3600 + minute * 60 + second;
    // Apply the trailing zone offset (Z or ±HH:MM); the default is UTC.
    const std::streamoff consumed = in.tellg();
    if (consumed < 0) return true;
    const std::size_t position = std::min<std::size_t>(static_cast<std::size_t>(consumed),
                                                       text.size());
    const std::string rest = text.substr(position);
    if (!rest.empty() && (rest[0] == '+' || rest[0] == '-')) {
        int zoneHour = 0, zoneMinute = 0;
        if (std::sscanf(rest.c_str(), "%3d:%2d", &zoneHour, &zoneMinute) == 2) {
            const std::int64_t offset =
                zoneHour * 3600 + (zoneHour < 0 ? -zoneMinute : zoneMinute) * 60;
            epochSeconds -= offset;
        }
    }
    return true;
}

std::optional<std::int64_t> parseIsoToSeconds(const std::string& text) {
    if (text.size() < 19) return std::nullopt;
    std::int64_t seconds = 0;
    if (!readUtcParts(text, seconds)) return std::nullopt;
    return seconds;
}

std::string memberKindFor(const std::string& memberName) {
    const std::string stem = fs::path(memberName).stem().string();
    if (stem == "deviceinfo") return "device_info";
    if (stem == "imei") return "device_identifier";
    if (stem == "application") return "application";
    if (stem == "uninstalllist") return "uninstall_list";
    if (stem == "app_traffic") return "app_traffic";
    if (stem == "appusagedetail") return "app_usage_session";
    if (stem == "wifi") return "wifi";
    if (stem == "image_extractor" || stem == "video_extractor" || stem == "audio_extractor")
        return "media";
    if (stem == "contacts") return "contact";
    if (stem == "calllogs") return "call_log";
    if (stem == "smss") return "sms";
    if (stem == "mmss") return "mms";
    if (stem == "calendar") return "calendar_event";
    if (stem == "siminfo") return "sim_info";
    if (stem == "simstate") return "sim_state";
    if (stem == "bluetooth") return "bluetooth";
    if (stem == "doc_extractor") return "document";
    return "phone_data:" + stem;
}

std::string bytesSha256(const std::string& bytes) {
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned size = 0;
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),
                                                                    EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(context.get(), bytes.data(), bytes.size()) != 1 ||
        EVP_DigestFinal_ex(context.get(), digest, &size) != 1)
        return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned i = 0; i < size; ++i) out << std::setw(2) << unsigned(digest[i]);
    return out.str();
}

std::string stripQuotes(std::string value) {
    if (value.size() >= 2 && value.front() == '"' && value.back() == '"')
        return value.substr(1, value.size() - 2);
    return value;
}

std::string wifiSsidDisplay(std::string ssid) {
    // ThunderForensic keeps the raw quoted form ("Pixel_9577bn"); store the
    // human-readable network name like the standard WifiConfigStore parser.
    return stripQuotes(std::move(ssid));
}

// Android WifiConfiguration.KeyMgmt values, used when wifi.xml stores the
// allowedKeyManagement array instead of a printable KeyType label.
std::string keyManagementLabel(const json& item) {
    static const std::array<const char*, 11> kNames = {
        "NONE", "WPA_PSK", "WPA_EAP", "IEEE8021X", "WPA2_PSK", "OSEN",
        "SAE", "OWE", "WAPI_PSK", "WAPI_CERT", "SUITE_B_192"};
    if (!item.contains("allowedKeyManagement") ||
        !item["allowedKeyManagement"].is_array())
        return {};
    std::string label;
    for (const auto& value : item["allowedKeyManagement"]) {
        if (!value.is_number_integer()) continue;
        const auto index = value.get<long long>();
        if (index < 0 || static_cast<std::size_t>(index) >= kNames.size()) continue;
        if (!label.empty()) label += "|";
        label += kNames[static_cast<std::size_t>(index)];
    }
    return label;
}

std::string xmlUnescape(const std::string& value) {    std::string out;
    out.reserve(value.size());
    for (std::size_t i = 0; i < value.size();) {
        if (value.compare(i, 5, "&amp;") == 0) {
            out.push_back('&');
            i += 5;
        } else if (value.compare(i, 6, "&quot;") == 0) {
            out.push_back('"');
            i += 6;
        } else if (value.compare(i, 4, "&lt;") == 0) {
            out.push_back('<');
            i += 4;
        } else if (value.compare(i, 4, "&gt;") == 0) {
            out.push_back('>');
            i += 4;
        } else if (value.compare(i, 5, "&#39;") == 0) {
            out.push_back('\'');
            i += 5;
        } else {
            out.push_back(value[i++]);
        }
    }
    return out;
}

// Maps ThunderForensic list items onto the standard artifact tables when the
// field names are recognizable. Field spellings beyond these samples are
// unknown; unrecognized items stay in mobile_artifacts with their raw JSON.
bool fillContactRecord(const json& item, std::map<std::string, std::string>& record) {
    const std::string name = scalar(item, {"Name", "name", "DisplayName", "display_name",
                                           "NickName", "nick_name"});
    const std::string phone = scalar(item, {"Phone", "phone", "PhoneNumber", "phone_number",
                                            "Number", "number", "Mobile", "mobile"});
    if (name.empty() && phone.empty()) return false;
    record["display_name"] = name;
    record["phone"] = phone;
    return true;
}

bool fillCallRecord(const json& item, std::map<std::string, std::string>& record) {
    const std::string number = scalar(item, {"PhoneNumber", "phone_number", "Number", "number",
                                             "Phone", "phone"});
    if (number.empty()) return false;
    const std::string type = toLower(scalar(item, {"Type", "type", "CallType", "call_type"}));
    static const std::map<std::string, std::string> kCallTypes = {
        {"incoming", "1"}, {"outgoing", "2"}, {"missed", "3"}, {"voicemail", "4"},
        {"rejected", "5"}, {"blocked", "6"}};
    const auto mappedType = kCallTypes.find(type);
    record["number"] = number;
    record["date"] = scalar(item, {"Time", "time", "Date", "date", "DateMs", "date_ms"});
    record["duration"] = scalar(item, {"Duration", "duration"});
    record["type"] = mappedType != kCallTypes.end() ? mappedType->second : type;
    return true;
}

bool fillSmsRecord(const json& item, std::map<std::string, std::string>& record) {
    const std::string body = scalar(item, {"Body", "body", "Content", "content", "Text", "text",
                                           "SmsContent", "sms_content"});
    const std::string address = scalar(item, {"Address", "address", "PhoneNumber",
                                              "phone_number", "Number", "number",
                                              "Phone", "phone"});
    if (body.empty() && address.empty()) return false;
    const std::string type = toLower(scalar(item, {"Type", "type", "SmsType", "sms_type"}));
    static const std::map<std::string, std::string> kSmsTypes = {
        {"inbox", "1"}, {"received", "1"}, {"sent", "2"}, {"draft", "3"},
        {"outbox", "4"}, {"failed", "5"}, {"queued", "6"}};
    const auto mappedType = kSmsTypes.find(type);
    record["address"] = address;
    record["body"] = body;
    record["date"] = scalar(item, {"Time", "time", "Date", "date", "DateMs", "date_ms"});
    record["type"] = mappedType != kSmsTypes.end() ? mappedType->second : type;
    return true;
}

class IdentifierWriter {
public:
    IdentifierWriter(mobile_evidence::Package& package, std::set<std::string>& seen)
        : package_(package), seen_(seen) {}

    void add(const std::string& type, const std::string& value,
             const std::string& sourcePath = {}) {
        if (type.empty() || value.empty()) return;
        const std::string key = type + "\x1f" + value;
        if (!seen_.insert(key).second) return;
        mobile_evidence::Record record;
        record.kind = mobile_evidence::kind::kDeviceIdentity;
        record.sourcePath = sourcePath;
        record.sourceTable = "identifier";
        record.sourceKey = key;
        record.parserVersion = kParserVersion;
        record.payloadJson = json{{"identifier_type", type}, {"value", value}}.dump();
        record.rawJson = record.payloadJson;
        package_.records.push_back(std::move(record));
    }

private:
    mobile_evidence::Package& package_;
    std::set<std::string>& seen_;
};

void insertPhoneDataIdentifiers(mobile_evidence::Package& package,
                                const std::string& sourcePath,
                                const json& item, IdentifierWriter& identifiers) {
    static const std::array<const char*, 12> kIdentifierKeys = {
        "androidid", "imei1", "imei2", "meid", "serial", "macaddress", "android_id",
        "iccid", "imsi", "phonenumber", "wifimac", "bluetoothmac"};
    const std::string key = scalar(item, {"Key", "key"});
    const std::string value = scalar(item, {"Value", "value"});
    if (!key.empty() && !value.empty()) {
        for (const char* candidate : kIdentifierKeys) {
            if (key == candidate) {
                identifiers.add(key, value, sourcePath);
                return;
            }
        }
    }
    // SIM records (vivo) carry identifiers as named fields instead of Key/Value.
    identifiers.add("iccid", scalar(item, {"Iccid", "ICCID", "iccid"}), sourcePath);
    identifiers.add("imsi", scalar(item, {"Imsi", "IMSI", "imsi"}), sourcePath);
    identifiers.add("phonenumber", scalar(item, {"PhoneNumber", "phone_number"}), sourcePath);
}

// Maps /storage/emulated/0/<rest> to the sdcard/<rest> container member when
// the payload rides along in the tar.
std::string mediaRelatedPath(const ThunderForensicBackupExtractor& source, const json& item) {
    const std::string mobilePath = scalar(item, {"MobilePath", "mobile_path", "Path", "path"});
    if (mobilePath.empty()) return {};
    static const std::array<const char*, 2> kStoragePrefixes = {"/storage/emulated/0/",
                                                                "/sdcard/"};
    for (const char* prefix : kStoragePrefixes) {
        const std::size_t position = mobilePath.find(prefix);
        if (position == std::string::npos) continue;
        const std::string candidate = "sdcard/" + mobilePath.substr(position + strlen(prefix));
        if (source.entries().count(candidate)) return candidate;
    }
    return {};
}

std::string toLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return value;
}

bool hasSuffix(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size() &&
           value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

// A per-app tree is encoded as <package>.tar/... or <package>.ab/... (the
// writer expands the inner archive in place). Returns the container prefix.
std::string appContainerPrefix(const std::string& path, std::string& package) {
    std::string normalized = path;
    std::replace(normalized.begin(), normalized.end(), '\\', '/');
    const std::size_t slash = normalized.find('/');
    if (slash == std::string::npos || slash == 0) return {};
    const std::string component = normalized.substr(0, slash);
    const std::string lower = toLower(component);
    static const std::array<const char*, 3> kSuffixes = {".tar", ".ab", ".zip"};
    for (const char* suffix : kSuffixes) {
        if (!hasSuffix(lower, suffix)) continue;
        const std::string stem = component.substr(0, component.size() - strlen(suffix));
        if (stem.empty() || stem.find('/') != std::string::npos) return {};
        package = stem;
        return component;
    }
    return {};
}

bool looksLikeDatabase(const std::string& path) {
    std::string name = fs::path(path).filename().string();
    std::transform(name.begin(), name.end(), name.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return hasSuffix(name, ".db") || hasSuffix(name, ".sqlite") || hasSuffix(name, ".sqlite3");
}

struct ZipInventoryEntry {
    std::string name;
    std::uint16_t flags = 0;
};

struct ZipInventory {
    bool ok = false;
    bool encrypted = false;
    std::vector<ZipInventoryEntry> entries;
    std::size_t totalEntries = 0;
};

std::uint16_t readLe16(const std::string& data, std::size_t offset) {
    return static_cast<std::uint16_t>(static_cast<unsigned char>(data[offset]) |
                                      (static_cast<unsigned char>(data[offset + 1]) << 8));
}

std::uint32_t readLe32(const std::string& data, std::size_t offset) {
    return static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset])) |
           (static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + 1])) << 8) |
           (static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + 2])) << 16) |
           (static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + 3])) << 24);
}

std::uint32_t readBe32(const std::string& data, std::size_t offset) {
    return (static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset])) << 24) |
           (static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + 1])) << 16) |
           (static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + 2])) << 8) |
           static_cast<std::uint32_t>(static_cast<unsigned char>(data[offset + 3]));
}

// ThunderForensic wraps large root-level envelopes (wifi.xml, note.zip,
// encryptNote.zip) in [uint32_be length][payload] chunks terminated by a zero
// length. Small files such as .backup are written plainly. Unframing is
// conservative: anything that does not parse as a complete chunk stream is
// returned unchanged.
std::string unframeThunderForensicBlob(const std::string& data, bool& framed) {
    framed = false;
    if (data.size() < 8) return data;
    const std::uint32_t first = readBe32(data, 0);
    if (first == 0 || first > data.size() - 4) return data;
    std::string out;
    out.reserve(data.size());
    std::size_t position = 0;
    std::size_t chunks = 0;
    while (position + 4 <= data.size()) {
        const std::uint32_t length = readBe32(data, position);
        position += 4;
        if (length == 0) break;
        if (length > data.size() - position) return data;
        out.append(data, position, length);
        position += length;
        ++chunks;
    }
    if (chunks == 0 || out.empty()) return data;
    // Any trailing bytes must be the zero terminator/padding.
    for (std::size_t i = position; i < data.size(); ++i)
        if (data[i] != '\0') return data;
    framed = true;
    return out;
}

// Reads the ZIP central directory without trusting the local-header offsets:
// ThunderForensic prefixes note archives with a 4-byte length, which shifts
// every offset and makes ordinary zip readers reject them.
ZipInventory readZipInventory(const std::string& data) {
    ZipInventory inventory;
    const std::size_t eocd = data.rfind(std::string("PK\x05\x06", 4));
    if (eocd == std::string::npos || eocd + 22 > data.size()) return inventory;
    const std::size_t total = readLe16(data, eocd + 10);
    const std::size_t centralOffset = readLe32(data, eocd + 16);
    if (total == 0xFFFF || centralOffset == 0xFFFFFFFF) return inventory;  // ZIP64
    std::size_t base = data.find(std::string("PK\x03\x04", 4));
    if (base == std::string::npos) base = 0;
    std::size_t position = base + centralOffset;
    if (position > data.size()) return inventory;
    inventory.totalEntries = total;
    for (std::size_t index = 0; index < total && index < kMaxZipEntries; ++index) {
        if (position + 46 > data.size()) return inventory;
        if (data.compare(position, 4, "PK\x01\x02") != 0) return inventory;
        const std::uint16_t flags = readLe16(data, position + 8);
        const std::size_t nameLength = readLe16(data, position + 28);
        const std::size_t extraLength = readLe16(data, position + 30);
        const std::size_t commentLength = readLe16(data, position + 32);
        if (position + 46 + nameLength + extraLength + commentLength > data.size())
            return inventory;
        ZipInventoryEntry entry;
        entry.name = data.substr(position + 46, nameLength);
        entry.flags = flags;
        if (flags & 0x0001 || flags & 0x0040 || flags & 0x0800) inventory.encrypted = true;
        inventory.entries.push_back(std::move(entry));
        position += 46 + nameLength + extraLength + commentLength;
    }
    inventory.ok = true;
    return inventory;
}

}  // namespace

bool buildPackageFromThunderForensic(ThunderForensicBackupExtractor& source,
                                     mobile_evidence::Package& out,
                                     std::vector<AndroidSourceProvenance>&
                                         caseProvenanceOut) {
    using mobile_evidence::Coverage;
    using mobile_evidence::Record;

    out = mobile_evidence::Package{};
    out.acquisition.adapterName = "thunder-backup";
    out.acquisition.adapterVersion = kParserVersion;
    out.acquisition.sourceType = "tar";
    out.acquisition.sourcePath = source.containerPath().string();
    out.acquisition.sourceSha256 = source.containerSha256();

    // ThunderForensic's published coverage vocabulary (parsed/empty/indexed/
    // LOCKED/PARTIAL/EXTRACT_FAILED/UNSUPPORTED) is what downstream consumers
    // read. Distinct from the normalized status field, it is carried verbatim
    // in nativeStatus so migration does not change visible values.
    const auto addCoverage = [&out](const std::string& artifactKind,
                                    const std::string& sourcePath,
                                    const std::string& state,
                                    const std::string& detail,
                                    std::uint64_t count = 0) {
        Coverage entry;
        entry.artifactKind = artifactKind;
        entry.sourcePath = sourcePath;
        entry.status = state;
        entry.nativeStatus = state;
        entry.detail = detail;
        entry.recordCount = count;
        out.coverage.push_back(std::move(entry));
    };

    std::size_t artifactRows = 0;
    const auto insertArtifact = [&](const std::string& kind, const std::string& packageName,
                                    const std::string& sourcePath, const std::string& sourceTable,
                                    const std::string& sourceKey, const std::string& recordJson,
                                    const std::string& timestampRaw,
                                    std::optional<std::int64_t> timestampSeconds,
                                    const std::string& relatedPath = {},
                                    const std::string& relatedStatus = {}) {
        if (artifactRows >= kMaxArtifactRows) return;
        Record record;
        record.kind = mobile_evidence::kind::kGeneric;
        record.nativeKind = kind;
        record.mobileArtifact = true;
        record.packageName = packageName;
        record.sourcePath = sourcePath;
        record.sourceTable = sourceTable;
        record.sourceKey = sourceKey;
        record.rawJson = recordJson;
        record.timestampRaw = timestampRaw;
        if (timestampSeconds) {
            record.timestampUnit = mobile_evidence::time_unit::kSeconds;
            record.timestampSeconds = *timestampSeconds;
        }
        record.parserVersion = kParserVersion;
        record.relatedPath = relatedPath;
        record.relatedStatus = relatedStatus;
        out.records.push_back(std::move(record));
        ++artifactRows;
    };

    std::set<std::string> identifierSeen;
    IdentifierWriter identifiers(out, identifierSeen);
    std::set<std::string> wifiSeen;
    // Kinds the container layer actually produced rows for. The project's
    // case databases are only read for families the tar did not cover (a
    // brand may omit PhoneData/smss.json while the case database has SMS).
    std::map<std::string, std::set<std::string>> parsedMembers;

    // ---- Backup manifest (ThunderForensic.json) ----
    std::string manifestBytes;
    if (!source.readMemberBytes(kManifestMember, manifestBytes, 8ULL << 20))
        throw std::runtime_error("THUNDERFORENSIC_MANIFEST_UNREADABLE");
    const json manifest = json::parse(manifestBytes);
    const json& device = manifest.contains("Device") && manifest["Device"].is_object()
                             ? manifest["Device"]
                             : json::object();
    const json& software = manifest.contains("Software") && manifest["Software"].is_object()
                               ? manifest["Software"]
                               : json::object();
    std::string deviceDisplay = scalar(device, {"Brand"});
    const std::string model = scalar(device, {"Model"});
    if (!model.empty() && deviceDisplay.find(model) == std::string::npos)
        deviceDisplay = deviceDisplay.empty() ? model : deviceDisplay + " " + model;
    if (deviceDisplay.empty()) deviceDisplay = scalar(device, {"Name"});
    if (deviceDisplay.empty()) deviceDisplay = scalar(device, {"Manufactor"});

    std::int64_t backupTimeMs = 0;
    if (manifest.contains("TaskInfo") && manifest["TaskInfo"].is_object()) {
        const std::string createdAt =
            scalar(manifest["TaskInfo"], {"CreateAt", "CompleteAt"});
        if (const auto seconds = parseIsoToSeconds(createdAt)) backupTimeMs = *seconds * 1000;
    }
    std::size_t moduleCount = 0;
    std::size_t logMembers = 0, sdcardMembers = 0, sdcardBytes = 0;
    for (const auto& [path, entry] : source.entries()) {
        if (path.starts_with(kPhoneDataPrefix) && path.ends_with(".json")) ++moduleCount;
        if (path.starts_with(kLogDataPrefix)) ++logMembers;
        if (path.starts_with("sdcard/")) {
            ++sdcardMembers;
            sdcardBytes += entry.size;
        }
    }

    out.manifest.present = true;
    out.manifest.targetTable = "mobile_backup_manifest";
    out.manifest.platform = "Android";
    out.manifest.device = deviceDisplay;
    out.manifest.backupVersion = scalar(software, {"Version"});
    out.manifest.backupTimeMs = backupTimeMs;
    out.manifest.moduleCount = static_cast<std::int64_t>(moduleCount);
    out.manifest.manifestSha256 = bytesSha256(manifestBytes);
    out.manifest.adapterVersion = kParserVersion;

    out.device.platform = "android";
    out.device.brand = scalar(device, {"Brand"});
    out.device.model = model;
    out.device.deviceName = deviceDisplay;
    out.device.serialNumber = scalar(device, {"SerialNumber", "SN"});
    out.device.imei = scalar(device, {"Imei"});
    out.device.meid = scalar(device, {"Meid"});
    out.device.extraJson = json{
        {"imei2", scalar(device, {"Imei2"})},
        {"mac_address", scalar(device, {"MacAddress", "WiFiAddress"})},
        {"tool_version", scalar(software, {"Version"})},
    }.dump();

    // Device identifiers that only the manifest carries.
    identifiers.add("imei1", scalar(device, {"Imei"}), kManifestMember);
    identifiers.add("imei2", scalar(device, {"Imei2"}), kManifestMember);
    identifiers.add("meid", scalar(device, {"Meid"}), kManifestMember);
    identifiers.add("serial", scalar(device, {"SerialNumber", "SN"}), kManifestMember);
    identifiers.add("macaddress", scalar(device, {"MacAddress", "WiFiAddress"}),
                    kManifestMember);

    // ---- PhoneData JSON artifacts ----
    for (const auto& [path, entry] : source.entries()) {
        if (!path.starts_with(kPhoneDataPrefix) || !path.ends_with(".json")) continue;
        const std::string kind = memberKindFor(path);
        const std::string sourceTable = fs::path(path).stem().string();
        if (path == kManifestMember || entry.size > kMaxMemberJsonBytes) {
            addCoverage("phone_data", path, "UNSUPPORTED", "member_size_limit");
            continue;
        }
        std::string bytes;
        if (!source.readMemberBytes(path, bytes)) {
            addCoverage("phone_data", path, "EXTRACT_FAILED", source.error());
            continue;
        }
        json document;
        try {
            document = json::parse(bytes);
        } catch (const std::exception&) {
            // ThunderForensic writes extractor error strings (e.g.
            // "java.lang.SecurityException: ...") into the .json member
            // when an artifact could not be acquired — surface that reason
            // instead of a bare parse failure.
            std::string detail = "invalid JSON document";
            if (!bytes.empty() && bytes.find_first_of("[{") != 0) {
                std::string reason = bytes.substr(0, bytes.find('\n'));
                if (reason.size() > 300) reason = reason.substr(0, 300);
                detail = "extractor_error: " + reason;
            }
            addCoverage("phone_data", path, "parse_failed", detail);
            continue;
        }
        // Normalize: arrays iterate directly; objects contribute their
        // array-valued fields (appusagedetail carries eventResultList).
        std::vector<std::pair<std::string, const json*>> sections;
        if (document.is_array()) {
            sections.emplace_back("", &document);
        } else if (document.is_object()) {
            for (const auto& [key, value] : document.items())
                if (value.is_array()) sections.emplace_back(key, &value);
            if (sections.empty()) sections.emplace_back("", &document);
        } else {
            addCoverage("phone_data", path, "empty", "non-object JSON document");
            continue;
        }

        std::size_t rows = 0, standardRows = 0;
        std::size_t rowIndex = 0;
        for (const auto& [section, list] : sections) {
            if (!list->is_array()) continue;
            for (const auto& item : *list) {
                const std::size_t index = rowIndex++;
                if (!item.is_object()) continue;
                const std::string packageName = scalar(item, {"PackageName", "package_name"});
                const std::string timestampRaw =
                    scalar(item, {"InstallTime", "LastUpdateTime", "LastUseTime",
                                  "CreateTime", "ModifyTime", "StartTime", "startTime",
                                  "endTime", "Date", "date", "Time", "time",
                                  "LastConnected"});
                const auto timestampSeconds = parseIsoToSeconds(timestampRaw);
                // The mobile_artifacts reader contract (android_artifact_
                // reader.py) parses source_key as JSON — the row's primary
                // key. Keep Harmony's shape: a JSON object, not a bare string.
                const json keyObject = section.empty()
                    ? json{{"row", index}}
                    : json{{"section", section}, {"row", index}};
                const std::string sourceKey = serialized(keyObject);
                insertArtifact(kind, packageName, path, sourceTable, sourceKey,
                               serialized(item), timestampRaw, timestampSeconds);
                parsedMembers[kind].insert(path);
                ++rows;

                // Standard-table projections keep ThunderForensic records
                // visible to the existing Android query surface.
                if (kind == "application" && !packageName.empty()) {
                    Record app;
                    app.kind = mobile_evidence::kind::kInstalledApp;
                    app.packageName = packageName;
                    app.sourcePath = path;
                    app.sourceTable = sourceTable;
                    app.sourceKey = sourceKey;
                    app.rawJson = serialized(item);
                    app.payloadJson = serialized(json{
                        {"package_name", packageName},
                        {"display_name", scalar(item, {"AppName", "app_name"})},
                        {"version_code", scalar(item, {"VersionCode"})},
                        {"version_name", scalar(item, {"VersionName"})},
                        {"data_size", std::to_string(numberValue(item, {"ApkSize"}))},
                        {"sd_size", "0"},
                        {"bak_type", "0"},
                    });
                    app.parserVersion = kParserVersion;
                    out.records.push_back(std::move(app));
                    ++standardRows;
                } else if (kind == "wifi") {
                    const std::string ssid = wifiSsidDisplay(scalar(item, {"Ssid", "ssid"}));
                    const std::string keyMgmt = scalar(item, {"KeyType", "key_type"});
                    if (!ssid.empty() && wifiSeen.insert(toLower(ssid)).second) {
                        Record wifi;
                        wifi.kind = mobile_evidence::kind::kWifiNetwork;
                        wifi.sourcePath = path;
                        wifi.sourceTable = sourceTable;
                        wifi.sourceKey = sourceKey;
                        wifi.rawJson = serialized(item);
                        wifi.payloadJson = serialized(json{
                            {"ssid", ssid},
                            {"pre_shared_key", ""},
                            {"key_mgmt", keyMgmt},
                        });
                        wifi.parserVersion = kParserVersion;
                        out.records.push_back(std::move(wifi));
                        ++standardRows;
                    }
                } else if (kind == "contact") {
                    std::map<std::string, std::string> record;
                    if (fillContactRecord(item, record)) {
                        Record contact;
                        contact.kind = mobile_evidence::kind::kContact;
                        contact.sourcePath = path;
                        contact.sourceTable = sourceTable;
                        contact.sourceKey = sourceKey;
                        contact.rawJson = serialized(item);
                        contact.payloadJson = serialized(json{
                            {"display_name", record["display_name"]},
                            {"phone_number", record["phone"]},
                        });
                        contact.parserVersion = kParserVersion;
                        out.records.push_back(std::move(contact));
                        ++standardRows;
                    }
                } else if (kind == "call_log") {
                    std::map<std::string, std::string> record;
                    if (fillCallRecord(item, record)) {
                        Record call;
                        call.kind = mobile_evidence::kind::kCallLog;
                        call.sourcePath = path;
                        call.sourceTable = sourceTable;
                        call.sourceKey = sourceKey;
                        call.rawJson = serialized(item);
                        call.payloadJson = serialized(json{
                            {"number", record["number"]},
                            // ThunderForensic keeps call dates in seconds;
                            // state it explicitly so the analysis stage does
                            // not re-scale a value the vendor already fixed.
                            {"date", timestampSeconds
                                ? std::to_string(*timestampSeconds)
                                : record["date"]},
                            {"duration_seconds", record["duration"]},
                            {"type", record["type"]},
                        });
                        if (timestampSeconds) {
                            call.timestampUnit = mobile_evidence::time_unit::kSeconds;
                            call.timestampSeconds = *timestampSeconds;
                        }
                        call.parserVersion = kParserVersion;
                        out.records.push_back(std::move(call));
                        ++standardRows;
                    }
                } else if (kind == "sms") {
                    std::map<std::string, std::string> record;
                    if (fillSmsRecord(item, record)) {
                        Record sms;
                        sms.kind = mobile_evidence::kind::kSms;
                        sms.sourcePath = path;
                        sms.sourceTable = sourceTable;
                        sms.sourceKey = sourceKey;
                        sms.rawJson = serialized(item);
                        sms.payloadJson = serialized(json{
                            {"address", record["address"]},
                            {"body", record["body"]},
                            {"date", timestampSeconds
                                ? std::to_string(*timestampSeconds)
                                : record["date"]},
                            {"type", record["type"]},
                        });
                        if (timestampSeconds) {
                            sms.timestampUnit = mobile_evidence::time_unit::kSeconds;
                            sms.timestampSeconds = *timestampSeconds;
                        }
                        sms.parserVersion = kParserVersion;
                        out.records.push_back(std::move(sms));
                        ++standardRows;
                    }
                } else if (kind == "media") {
                    const std::string related = mediaRelatedPath(source, item);
                    if (!related.empty()) {
                        // The artifact row was just appended; attach the
                        // container member it resolves to.
                        for (auto it = out.records.rbegin(); it != out.records.rend(); ++it) {
                            if (it->sourcePath == path && it->sourceKey == sourceKey) {
                                it->relatedPath = related;
                                it->relatedStatus = "present_in_container";
                                break;
                            }
                        }
                    }
                }
                if (kind == "device_info" || kind == "device_identifier" ||
                    kind == "sim_info")
                    insertPhoneDataIdentifiers(out, path, item, identifiers);
                if (kind == "bluetooth") {
                    identifiers.add("paired_bluetooth_mac",
                                    scalar(item, {"Mac", "MAC", "mac"}), path);
                }
            }
        }
        addCoverage("phone_data", path, rows > 0 ? "parsed" : "empty",
                    "rows=" + std::to_string(rows) +
                        "; standard_table_rows=" + std::to_string(standardRows), rows);
    }

    // ---- wifi.xml fallback (vivo shared_prefs) ----
    if (source.entries().count(kWifiXmlMember)) {
        std::string xml;
        if (!source.readMemberBytes(kWifiXmlMember, xml, kMaxMemberJsonBytes)) {
            addCoverage("wifi_xml", kWifiXmlMember, "EXTRACT_FAILED", source.error());
        } else {
            bool framed = false;
            xml = unframeThunderForensicBlob(xml, framed);
            const std::string marker = "<string name=\"wifi_saved_network\">";
            const std::size_t start = xml.find(marker);
            const std::size_t end = start == std::string::npos
                ? std::string::npos : xml.find("</string>", start + marker.size());
            if (start == std::string::npos || end == std::string::npos) {
                addCoverage("wifi_xml", kWifiXmlMember, "empty",
                            "wifi_saved_network entry absent");
            } else {
                const std::string payload = xmlUnescape(
                    xml.substr(start + marker.size(), end - start - marker.size()));
                json networks;
                std::size_t rows = 0, standardRows = 0;
                bool parseFailed = false;
                try {
                    networks = json::parse(payload);
                } catch (const std::exception&) {
                    parseFailed = true;
                    networks = json::array();
                }
                if (networks.is_array()) {
                    std::size_t index = 0;
                    for (const auto& item : networks) {
                        const std::size_t row = index++;
                        if (!item.is_object()) continue;
                        const std::string ssid =
                            wifiSsidDisplay(scalar(item, {"SSID", "ssid", "Ssid"}));
                        std::string keyMgmt = scalar(item, {"KeyType", "key_mgmt", "keyMgmt"});
                        if (keyMgmt.empty()) keyMgmt = keyManagementLabel(item);
                        const std::string preSharedKey = stripQuotes(
                            scalar(item, {"preSharedKey", "PreSharedKey", "psk"}));
                        const std::string connected =
                            scalar(item, {"lastConnected", "LastConnected"});
                        std::optional<std::int64_t> connectedSeconds;
                        try {
                            if (!connected.empty()) {
                                std::int64_t value = std::stoll(connected);
                                if (value > 1000000000000LL) value /= 1000;
                                if (value > 0) connectedSeconds = value;
                            }
                        } catch (const std::exception&) {
                        }
                        insertArtifact("wifi", "", kWifiXmlMember, "wifi_xml",
                                       serialized(json{{"row", row}}), serialized(item),
                                       connected, connectedSeconds);
                        parsedMembers["wifi"].insert(kWifiXmlMember);
                        ++rows;
                        if (!ssid.empty() && wifiSeen.insert(toLower(ssid)).second) {
                            Record wifi;
                            wifi.kind = mobile_evidence::kind::kWifiNetwork;
                            wifi.sourcePath = kWifiXmlMember;
                            wifi.sourceTable = "wifi_xml";
                            wifi.sourceKey = serialized(json{{"row", row}});
                            wifi.rawJson = serialized(item);
                            wifi.payloadJson = serialized(json{
                                {"ssid", ssid},
                                {"pre_shared_key", preSharedKey},
                                {"key_mgmt", keyMgmt},
                            });
                            wifi.parserVersion = kParserVersion;
                            out.records.push_back(std::move(wifi));
                            ++standardRows;
                        }
                    }
                }
                addCoverage("wifi_xml", kWifiXmlMember,
                            parseFailed ? "parse_failed"
                                        : (rows > 0 ? "parsed" : "empty"),
                            parseFailed
                                ? "wifi_saved_network is not valid JSON"
                                : "rows=" + std::to_string(rows) +
                                      "; standard_table_rows=" + std::to_string(standardRows),
                            rows);
            }
        }
    } else {
        addCoverage("wifi_xml", kWifiXmlMember, "not_found",
                    "member absent; PhoneData/wifi.json used when present");
    }

    // ---- LogData / sdcard inventory (payloads are not parsed line-wise) ----
    for (const auto& [path, entry] : source.entries()) {
        if (!path.starts_with(kLogDataPrefix)) continue;
        json record = {{"name", fs::path(path).filename().string()},
                       {"size", entry.size},
                       {"modified", entry.modified}};
        insertArtifact("device_log", "", path, "logdata",
                       serialized(json{{"member", path}}), serialized(record), {},
                       std::nullopt);
    }
    addCoverage("device_log", "<LogData>",
                logMembers > 0 ? "indexed" : "empty",
                "log_files=" + std::to_string(logMembers) +
                    "; line-level parsing is not performed");
    addCoverage("sdcard_files", "<sdcard>",
                sdcardMembers > 0 ? "indexed" : "empty",
                "members=" + std::to_string(sdcardMembers) +
                    "; bytes=" + std::to_string(sdcardBytes) +
                    "; payloads remain in the container");

    // ---- per-package data trees (<package>.tar/, <package>.ab/, ...) ----
    struct AppContainer {
        std::string package;
        std::string prefix;
        std::size_t files = 0;
        std::uint64_t bytes = 0;
        std::size_t databases = 0;
        std::size_t databaseRows = 0;
        std::vector<std::string> sampleDatabases;
    };
    std::map<std::string, AppContainer> containers;
    bool containersTruncated = false;
    std::size_t databaseRows = 0;
    for (const auto& [path, entry] : source.entries()) {
        std::string package;
        const std::string prefix = appContainerPrefix(path, package);
        if (prefix.empty()) continue;
        auto& container = containers[prefix];
        if (container.prefix.empty()) {
            if (containers.size() > kMaxAppContainers) {
                containers.erase(prefix);
                containersTruncated = true;
                continue;
            }
            container.package = package;
            container.prefix = prefix;
        }
        ++container.files;
        container.bytes += entry.size;
        if (!looksLikeDatabase(path)) continue;
        ++container.databases;
        if (container.sampleDatabases.size() < 50)
            container.sampleDatabases.push_back(path);
        if (databaseRows >= kMaxAppDatabaseRows) continue;
        json record = {{"name", fs::path(path).filename().string()},
                       {"size", entry.size},
                       {"modified", entry.modified},
                       {"container", prefix}};
        insertArtifact("app_database", package, path, "app_data",
                       serialized(json{{"member", path}}), serialized(record), {},
                       std::nullopt, path, "present_in_container");
        ++container.databaseRows;
        ++databaseRows;
    }
    std::size_t indexedContainers = 0;
    for (const auto& [prefix, container] : containers) {
        json record = {{"package", container.package},
                       {"prefix", container.prefix},
                       {"files", container.files},
                       {"bytes", container.bytes},
                       {"databases", container.databases},
                       {"sample_databases", container.sampleDatabases}};
        insertArtifact("app_data_container", container.package, prefix, "app_data",
                       serialized(json{{"container", prefix}}), serialized(record), {},
                       std::nullopt, prefix, "indexed_in_container");
        addCoverage("app_data", prefix, "indexed",
                    "files=" + std::to_string(container.files) +
                        "; bytes=" + std::to_string(container.bytes) +
                        "; databases=" + std::to_string(container.databases),
                    container.files);
        ++indexedContainers;
    }
    addCoverage("app_data", "<containers>",
                containers.empty() ? "empty" : "indexed",
                "containers=" + std::to_string(indexedContainers) +
                    "; database_rows=" + std::to_string(databaseRows) +
                    (containersTruncated
                         ? "; truncated_at=" + std::to_string(kMaxAppContainers)
                         : ""));

    // ---- root-level vendor envelopes ----
    std::size_t noteArchives = 0, encryptedEnvelopes = 0;
    for (const auto& [path, entry] : source.entries()) {
        const std::string name = fs::path(path).filename().string();
        if (name != "note.zip" && name != "encryptNote.zip" && name != ".backup" &&
            name != "encryptContact.vcf" && name != "encryptSms.xml")
            continue;
        std::string bytes;
        const bool readable = source.readMemberBytes(path, bytes, kMaxMemberJsonBytes);
        bool framed = false;
        const std::string payload = readable
            ? unframeThunderForensicBlob(bytes, framed) : std::string{};
        if (name == "note.zip" || name == "encryptNote.zip") {
            ++noteArchives;
            const ZipInventory inventory =
                readable ? readZipInventory(payload) : ZipInventory{};
            json record = {{"name", name},
                           {"size", entry.size},
                           {"readable", readable},
                           {"framed", framed},
                           {"entries", inventory.totalEntries},
                           {"encrypted", inventory.encrypted},
                           {"names", json::array()}};
            for (const auto& item : inventory.entries) {
                if (record["names"].size() >= 100) break;
                record["names"].push_back(item.name);
            }
            insertArtifact("note_archive", "", path, "vendor_archive",
                           serialized(json{{"archive", path}}), serialized(record), {},
                           std::nullopt, path,
                           inventory.encrypted ? "encrypted_entries" : "indexed");
            addCoverage("note_archive", path,
                        inventory.ok
                            ? (inventory.encrypted ? "LOCKED" : "indexed")
                            : "parse_failed",
                        inventory.ok
                            ? "entries=" + std::to_string(inventory.totalEntries) +
                                  "; encrypted=" +
                                  (inventory.encrypted ? std::string("true")
                                                       : std::string("false")) +
                                  "; content_not_decrypted"
                            : "ZIP central directory unreadable");
        } else if (name == ".backup") {
            json record = {{"name", name}, {"size", entry.size}, {"readable", readable},
                           {"framed", framed}};
            if (readable) {
                try {
                    record["document"] = json::parse(payload);
                } catch (const std::exception&) {
                    record["document"] =
                        payload.substr(0, std::min<std::size_t>(payload.size(), 512));
                }
            }
            insertArtifact("device_marker", "", path, "vendor_envelope",
                           serialized(json{{"member", path}}), serialized(record), {},
                           std::nullopt, path);
            addCoverage("device_marker", path,
                        readable ? "parsed" : "EXTRACT_FAILED",
                        "thunderforensic marker");
        } else {
            ++encryptedEnvelopes;
            json record = {{"name", name}, {"size", entry.size}};
            insertArtifact("encrypted_artifact", "", path, "vendor_envelope",
                           serialized(json{{"member", path}}), serialized(record), {},
                           std::nullopt, path,
                           entry.size == 0 ? "empty" : "encrypted_no_key");
            addCoverage("encrypted_artifact", path,
                        entry.size == 0 ? "empty" : "LOCKED",
                        entry.size == 0
                            ? "vendor encrypted envelope is empty in this extraction"
                            : "encrypted vendor envelope; no extraction key was supplied");
        }
    }
    addCoverage("vendor_archive", "<root>",
                (noteArchives + encryptedEnvelopes) > 0 ? "indexed" : "empty",
                "note_archives=" + std::to_string(noteArchives) +
                    "; encrypted_envelopes=" + std::to_string(encryptedEnvelopes));

    // ---- ThunderForensic case databases (project-folder delivery) ----
    // The tool's own parsed case database often carries rows the tar's
    // PhoneData members do not (vivo has no PhoneData/smss.json but 2079
    // SMS rows in data/evidence_1_sms). Read both layers; the case rows are
    // labeled with the database name so they never masquerade as tar rows.
    std::vector<AndroidSourceProvenance> caseProvenance;
    const auto caseStats = buildPackageFromCaseDatabases(
        source.projectRoot(), out, parsedMembers, &caseProvenance);
    if (caseStats.found) {
        std::cout << "[Android] ThunderForensic case databases: "
                  << caseStats.databases << " parsed, " << caseStats.rows
                  << " rows" << std::endl;
    }
    caseProvenanceOut = std::move(caseProvenance);

    // Container integrity and provenance are part of the result, not just
    // a log line: consumers can tell whether the SHA-256 policy skipped a
    // multi-gigabyte container.
    addCoverage("container_root:thunder-backup", source.containerPath().string(), "FOUND",
                "container=" + source.containerPath().filename().string() +
                    "; container_sha256_status=" + source.containerHashStatus());
    addCoverage("container", source.containerPath().string(), "FOUND",
                "container=" + source.containerPath().filename().string() +
                    "; container_sha256_status=" + source.containerHashStatus() +
                    "; duplicate_members=" + std::to_string(source.duplicateMemberCount()));
    return true;
}

bool analyzeThunderForensicBackup(ThunderForensicBackupExtractor& source,
                                  AndroidAnalysisDatabase& output) {
    sqlite3* dest = output.handle();
    if (!dest) return false;
    if (sqlite3_exec(dest, mobile_backup_schema::DDL, nullptr, nullptr, nullptr) != SQLITE_OK)
        return false;
    if (!output.beginTransaction()) return false;

    bool committed = false;
    try {
        // Re-running the same source replaces derived records; never accumulate
        // duplicates.
        if (sqlite3_exec(dest,
                         "DELETE FROM mobile_artifacts; DELETE FROM installed_apps; "
                         "DELETE FROM app_db_inventory; DELETE FROM android_source_coverage; "
                         "DELETE FROM android_source_provenance;",
                         nullptr, nullptr, nullptr) != SQLITE_OK)
            throw std::runtime_error("THUNDERFORENSIC_RESULT_RESET_FAILED");

        mobile_evidence::Package package;
        std::vector<AndroidSourceProvenance> caseProvenance;
        if (!buildPackageFromThunderForensic(source, package, caseProvenance))
            throw std::runtime_error("THUNDERFORENSIC_EXTRACTION_FAILED");

        mobile_evidence::AnalysisOptions options;
        options.mirrorFiles = false;  // sdcard 只做清单，不逐条落表
        mobile_evidence::AnalysisResult result;
        if (!mobile_evidence::analyzePackage(package, output, options, result))
            throw std::runtime_error("THUNDERFORENSIC_RESULT_WRITE_FAILED");

        for (const auto& item : caseProvenance) output.insertSourceProvenance(item);
        for (const auto& provenance : source.usedSourceProvenance())
            output.insertSourceProvenance(provenance);

        // Container-level coverage lives in its own table
        // (android_container_coverage) and carries the hash policy and
        // duplicate-member count; it is not a per-record fact, so it is
        // written here rather than through the package.
        output.recordContainerCoverage(
            source.containerPath().string(), "<root>", kThunderForensicSource, "FOUND",
            "container=" + source.containerPath().filename().string() +
                "; container_sha256_status=" + source.containerHashStatus() +
                "; duplicate_members=" + std::to_string(source.duplicateMemberCount()));
        output.recordSourceCoverage(
            "container_root:thunder-backup", source.containerPath().string(), "FOUND",
            "container=" + source.containerPath().filename().string() +
                "; container_sha256_status=" + source.containerHashStatus());

        if (!output.commitTransaction()) throw std::runtime_error("THUNDERFORENSIC_COMMIT_FAILED");
        committed = true;
        return true;
    } catch (const std::exception&) {
        if (!committed) output.rollbackTransaction();
        return false;
    }
}
