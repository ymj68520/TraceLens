#pragma once
#ifndef MIUI_BAK_PROTO_PARSERS_H
#define MIUI_BAK_PROTO_PARSERS_H

#include <cstdint>
#include <string>
#include <vector>

// Parsers for the MIUI offline-backup app-state records stored as
// apps/<package>/miui_bak/_tmp_bak tar members. System apps such as
// com.android.contacts (联系人 / 通话记录 / 通讯录与拨号 .bak files) do not
// back up their provider databases in these exports; instead the records ride
// along as hand-rolled protobuf payloads, with plain JSON used for plain
// settings. Schema below was recovered from real MIUI 12 (cepheus,
// V12.5.6.0.RFACNXM) backups and follows the protobuf wire format, so unknown
// fields are skipped rather than rejected.
//
// Contacts message (repeated at top level):
//   f1 ContactRecord {
//     f2 DataRecord {
//       f2 id (string)
//       f5 NameDetail { f1 display_name, f2 nickname, f4 sort_key }
//       f6 PhoneRecord { f1 number, f2 type (varint, AOSP Phone.TYPE) }
//     }
//   }
//
// Call-log message:
//   f2 CallLogList { repeated f1 CallEntry {
//     f2 id (string), f3 number (string), f4 date (varint, ms),
//     f5 duration (varint, s), f6 type (varint, AOSP Calls.TYPE) } }
// Call entries may also appear directly at the top level without the f2
// wrapper on some MIUI builds.

enum class MiuiBakKind {
    Unknown,   // unrecognized binary payload (e.g. empty state templates)
    Json,      // app settings JSON ("{\"packageName\":...}")
    Contacts,
    CallLog
};

struct MiuiProtoContactRow {
    std::string displayName;
    std::string nickname;
    std::string number;   // raw as stored (MIUI groups digits with spaces)
    int numberType = 0;
};

struct MiuiProtoCallRow {
    std::string number;
    uint64_t dateMs = 0;
    uint64_t duration = 0;
    int type = 0;
};

// Classifies a _tmp_bak payload. Contacts/CallLog require at least one
// well-formed record; structurally valid but empty payloads classify Unknown.
MiuiBakKind classifyMiuiBakContent(const std::string& bytes);

// Both parsers accept payloads of their own shape only (they verify the wire
// structure) and return false on malformed input. Unknown fields are skipped.
bool parseMiuiContactsBak(const std::string& bytes, std::vector<MiuiProtoContactRow>& out);
bool parseMiuiCallLogBak(const std::string& bytes, std::vector<MiuiProtoCallRow>& out);

#endif  // MIUI_BAK_PROTO_PARSERS_H
