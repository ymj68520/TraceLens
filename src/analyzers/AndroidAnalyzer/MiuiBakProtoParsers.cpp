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
//
// The container also carries non-contact DataRecords - notably a trailing
// group record that has only an id and status fields. Those are skipped rather
// than treated as corruption: rejecting the payload over one of them discarded
// every real contact in the same backup (observed: 668 contacts lost to the
// final record of a real MIUI 12 export).
bool parseContactsShape(const std::string& bytes, std::vector<MiuiProtoContactRow>& out) {
    std::vector<ProtoField> top;
    if (!readFields(bytes, top)) return false;

    bool sawContact = false;
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
            if (!haveName && !havePhone) continue;  // grouping/metadata record
            out.push_back(row);
            sawContact = true;
        }
    }
    return sawContact;
}

// One SMS/MMS entry. f4 address is the only field MIUI always writes; the
// body and timestamp are optional so a delivery report still yields a row.
bool parseSmsEntry(const std::string& buf, MiuiProtoSmsRow& row) {
    std::vector<ProtoField> fields;
    if (!readFields(buf, fields)) return false;
    if (!findString(fields, 4, row.address)) return false;

    findString(fields, 6, row.body);
    findString(fields, 10, row.serviceCenter);
    uint64_t value = 0;
    if (findVarint(fields, 7, value)) row.dateMs = value;
    if (findVarint(fields, 11, value)) row.threadId = value;
    if (findVarint(fields, 3, value)) row.type = static_cast<int>(value);
    if (findVarint(fields, 8, value)) row.read = static_cast<int>(value);
    if (findVarint(fields, 9, value)) row.status = static_cast<int>(value);
    return true;
}

// MessageList: entries nested under a single top-level f4 wrapper. Entries
// that carry neither an address nor a body (thread/grouping records) are
// skipped, matching the contact-record policy.
bool parseSmsShape(const std::string& bytes, std::vector<MiuiProtoSmsRow>& out) {
    std::vector<ProtoField> top;
    if (!readFields(bytes, top)) return false;

    bool sawMessage = false;
    for (const auto& field : top) {
        if (field.number != 4 || field.wireType != 2) continue;
        std::vector<ProtoField> wrapper;
        if (!readFields(field.bytes, wrapper)) return false;
        for (const auto& inner : wrapper) {
            if (inner.number != 1 || inner.wireType != 2) continue;
            MiuiProtoSmsRow row;
            if (!parseSmsEntry(inner.bytes, row)) continue;
            if (row.address.empty() && row.body.empty()) continue;
            out.push_back(std::move(row));
            sawMessage = true;
        }
    }
    return sawMessage;
}

// Notes: f6 wrapper holding repeated f2 NoteRecord. A record is accepted when
// it has an id, a title or a snippet, so empty template rows are skipped.
bool parseNotesShape(const std::string& bytes, std::vector<MiuiProtoNoteRow>& out) {
    std::vector<ProtoField> top;
    if (!readFields(bytes, top)) return false;

    bool sawNote = false;
    for (const auto& field : top) {
        if (field.number != 6 || field.wireType != 2) continue;
        std::vector<ProtoField> wrapper;
        if (!readFields(field.bytes, wrapper)) return false;
        for (const auto& inner : wrapper) {
            if (inner.number != 2 || inner.wireType != 2) continue;
            std::vector<ProtoField> record;
            if (!readFields(inner.bytes, record)) return false;

            MiuiProtoNoteRow row;
            findString(record, 2, row.noteId);
            findString(record, 8, row.snippet);
            findString(record, 14, row.title);
            findString(record, 15, row.kind);
            uint64_t value = 0;
            if (findVarint(record, 5, value)) row.createdMs = value;
            if (findVarint(record, 6, value)) row.modifiedMs = value;
            if (row.noteId.empty() && row.title.empty() && row.snippet.empty()) continue;
            out.push_back(std::move(row));
            sawNote = true;
        }
    }
    return sawNote;
}

}  // namespace

MiuiBakKind classifyMiuiBakContent(const std::string& bytes) {
    if (bytes.empty()) return MiuiBakKind::Unknown;
    if (looksLikeJson(bytes)) return MiuiBakKind::Json;
    std::vector<MiuiProtoCallRow> calls;
    if (parseCallLogShape(bytes, calls)) return MiuiBakKind::CallLog;
    std::vector<MiuiProtoContactRow> contacts;
    if (parseContactsShape(bytes, contacts)) return MiuiBakKind::Contacts;
    std::vector<MiuiProtoSmsRow> messages;
    if (parseSmsShape(bytes, messages)) return MiuiBakKind::Sms;
    std::vector<MiuiProtoNoteRow> notes;
    if (parseNotesShape(bytes, notes)) return MiuiBakKind::Notes;
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

bool parseMiuiSmsBak(const std::string& bytes, std::vector<MiuiProtoSmsRow>& out) {
    out.clear();
    if (looksLikeJson(bytes)) return false;
    return parseSmsShape(bytes, out);
}

bool parseMiuiNotesBak(const std::string& bytes, std::vector<MiuiProtoNoteRow>& out) {
    out.clear();
    if (looksLikeJson(bytes)) return false;
    return parseNotesShape(bytes, out);
}
