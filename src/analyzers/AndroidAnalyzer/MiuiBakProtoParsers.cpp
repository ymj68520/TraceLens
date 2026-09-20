#include "MiuiBakProtoParsers.h"

#include <cctype>

namespace {

struct ProtoField {
    uint32_t number = 0;
    uint32_t wireType = 0;
    uint64_t varint = 0;
    std::string bytes;
};

bool readVarint(const std::string& buf, size_t& pos, uint64_t& out) {
    uint64_t value = 0;
    int shift = 0;
    while (shift < 64) {
        if (pos >= buf.size()) return false;
        const uint8_t byte = static_cast<uint8_t>(buf[pos++]);
        value |= static_cast<uint64_t>(byte & 0x7f) << shift;
        if ((byte & 0x80) == 0) {
            out = value;
            return true;
        }
        shift += 7;
    }
    return false;
}

// Parses one full protobuf message into its fields. Returns false on any
// truncation or unsupported wire type so callers never inspect partial data.
bool readFields(const std::string& buf, std::vector<ProtoField>& out) {
    size_t pos = 0;
    while (pos < buf.size()) {
        uint64_t tag = 0;
        if (!readVarint(buf, pos, tag)) return false;
        ProtoField field;
        field.number = static_cast<uint32_t>(tag >> 3);
        field.wireType = static_cast<uint32_t>(tag & 7);
        if (field.number == 0) return false;
        switch (field.wireType) {
            case 0:  // varint
                if (!readVarint(buf, pos, field.varint)) return false;
                break;
            case 1:  // 64-bit
                if (pos + 8 > buf.size()) return false;
                pos += 8;
                break;
            case 2: {  // length-delimited
                uint64_t length = 0;
                if (!readVarint(buf, pos, length)) return false;
                if (length > buf.size() - pos) return false;
                field.bytes.assign(buf, pos, static_cast<size_t>(length));
                pos += static_cast<size_t>(length);
                break;
            }
            case 5:  // 32-bit
                if (pos + 4 > buf.size()) return false;
                pos += 4;
                break;
            default:
                return false;
        }
        out.push_back(std::move(field));
    }
    return true;
}

bool findString(const std::vector<ProtoField>& fields, uint32_t number, std::string& out) {
    for (const auto& field : fields) {
        if (field.number == number && field.wireType == 2) {
            out = field.bytes;
            return true;
        }
    }
    return false;
}

bool findVarint(const std::vector<ProtoField>& fields, uint32_t number, uint64_t& out) {
    for (const auto& field : fields) {
        if (field.number == number && field.wireType == 0) {
            out = field.varint;
            return true;
        }
    }
    return false;
}

bool looksLikeJson(const std::string& bytes) {
    size_t pos = 0;
    while (pos < bytes.size() && std::isspace(static_cast<unsigned char>(bytes[pos]))) ++pos;
    return pos < bytes.size() && bytes[pos] == '{';
}

// One CallEntry: f3 number (string) + f4 date (varint). Optional f2 id and
// f5/f6/f7 varints are read when present; unknown fields are skipped.
bool parseCallEntry(const std::string& buf, MiuiProtoCallRow& row) {
    std::vector<ProtoField> fields;
    if (!readFields(buf, fields)) return false;
    if (!findString(fields, 3, row.number) || row.number.empty()) return false;
    uint64_t date = 0;
    if (!findVarint(fields, 4, date)) return false;
    row.dateMs = date;
    uint64_t duration = 0;
    if (findVarint(fields, 5, duration)) row.duration = duration;
    uint64_t type = 0;
    if (findVarint(fields, 6, type)) row.type = static_cast<int>(type);
    return true;
}

// CallLogList: entries nested under a single top-level f2 wrapper, or repeated
// directly at the top level on some MIUI builds.
bool parseCallLogShape(const std::string& bytes, std::vector<MiuiProtoCallRow>& out) {
    std::vector<ProtoField> top;
    if (!readFields(bytes, top)) return false;

    std::vector<ProtoField> entries;
    bool haveEntries = false;
    for (const auto& field : top) {
        if (field.number == 2 && field.wireType == 2) {
            std::vector<ProtoField> wrapper;
            if (!readFields(field.bytes, wrapper)) return false;
            for (const auto& inner : wrapper) {
                if (inner.number == 1 && inner.wireType == 2) {
                    entries.push_back(inner);
                }
            }
            haveEntries = true;
        }
    }
    if (!haveEntries) {
        for (const auto& field : top) {
            if (field.number == 1 && field.wireType == 2) entries.push_back(field);
        }
    }
    for (const auto& entry : entries) {
        MiuiProtoCallRow row;
        if (!parseCallEntry(entry.bytes, row)) return false;
        out.push_back(std::move(row));
    }
    return !out.empty();
}

// ContactRecord: repeated top-level f1, each holding DataRecord f2 with
// NameDetail f5 and PhoneRecord f6. One output row per DataRecord.
bool parseContactsShape(const std::string& bytes, std::vector<MiuiProtoContactRow>& out) {
    std::vector<ProtoField> top;
    if (!readFields(bytes, top)) return false;

    bool sawRecord = false;
    for (const auto& field : top) {
        if (field.number != 1 || field.wireType != 2) continue;
        std::vector<ProtoField> contact;
        if (!readFields(field.bytes, contact)) return false;
        for (const auto& dataField : contact) {
            if (dataField.number != 2 || dataField.wireType != 2) continue;
            std::vector<ProtoField> data;
            if (!readFields(dataField.bytes, data)) return false;

            MiuiProtoContactRow row;
            std::vector<ProtoField> name;
            bool haveName = false;
            for (const auto& item : data) {
                if (item.number == 5 && item.wireType == 2 &&
                    readFields(item.bytes, name)) {
                    findString(name, 1, row.displayName);
                    findString(name, 2, row.nickname);
                    haveName = true;
                }
            }
            bool havePhone = false;
            for (const auto& item : data) {
                if (item.number != 6 || item.wireType != 2) continue;
                std::vector<ProtoField> phone;
                if (!readFields(item.bytes, phone)) return false;
                std::string number;
                uint64_t type = 0;
                findString(phone, 1, number);
                findVarint(phone, 2, type);
                if (!number.empty()) {
                    if (havePhone) out.push_back(row);  // flush previous phone row
                    row.number = number;
                    row.numberType = static_cast<int>(type);
                    havePhone = true;
                }
            }
            if (!haveName && !havePhone) return false;
            out.push_back(row);
            sawRecord = true;
        }
    }
    return sawRecord;
}

}  // namespace

MiuiBakKind classifyMiuiBakContent(const std::string& bytes) {
    if (bytes.empty()) return MiuiBakKind::Unknown;
    if (looksLikeJson(bytes)) return MiuiBakKind::Json;
    std::vector<MiuiProtoCallRow> calls;
    if (parseCallLogShape(bytes, calls)) return MiuiBakKind::CallLog;
    std::vector<MiuiProtoContactRow> contacts;
    if (parseContactsShape(bytes, contacts)) return MiuiBakKind::Contacts;
    return MiuiBakKind::Unknown;
}

bool parseMiuiCallLogBak(const std::string& bytes, std::vector<MiuiProtoCallRow>& out) {
    out.clear();
    if (looksLikeJson(bytes)) return false;
    return parseCallLogShape(bytes, out);
}

bool parseMiuiContactsBak(const std::string& bytes, std::vector<MiuiProtoContactRow>& out) {
    out.clear();
    if (looksLikeJson(bytes)) return false;
    return parseContactsShape(bytes, out);
}
