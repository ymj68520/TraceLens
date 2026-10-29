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
//
// SMS/MMS message (from 短信(com.android.mms).bak):
//   f4 MessageList { repeated f1 MessageEntry {
//     f2 id (string), f3 type (varint, AOSP Telephony.Sms.TYPE),
//     f4 address (string), f6 body (string), f7 date (varint, ms),
//     f8 read (varint), f9 status (varint), f10 service_center (string),
//     f11 thread_id (varint) } }
// f3 carries a sub-message flag; MIUI omits absent scalar fields entirely, so
// every field after the address is optional.
//
// Notes message (from 笔记(com.miui.notes).bak), MIUI Notes 3.x:
//   f6 NoteList { repeated f2 NoteRecord {
//     f2 id (string), f5 created (varint, ms), f6 modified (varint, ms),
//     f8 snippet (string), f14 title (string), f15 kind (string) } }
// f8 is the flat text rendered for the list view; rich bodies (checklists,
// images) live in separate note-detail stores not present in this export.

enum class MiuiBakKind {
    Unknown,   // unrecognized binary payload (e.g. empty state templates)
    Json,      // app settings JSON ("{\"packageName\":...}")
    Contacts,
    CallLog,
    Sms,
    Notes
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

struct MiuiProtoSmsRow {
    std::string address;
    std::string body;
    std::string serviceCenter;
    uint64_t dateMs = 0;
    uint64_t threadId = 0;
    int type = 0;
    int read = 0;
    int status = 0;
};

struct MiuiProtoNoteRow {
    std::string noteId;
    std::string title;
    std::string snippet;
    std::string kind;
    uint64_t createdMs = 0;
    uint64_t modifiedMs = 0;
};

// Classifies a _tmp_bak payload. Contacts/CallLog require at least one
// well-formed record; structurally valid but empty payloads classify Unknown.
// Records carrying neither a name nor a phone (contact grouping rows) are
// skipped rather than treated as corruption.
MiuiBakKind classifyMiuiBakContent(const std::string& bytes);

// Both parsers accept payloads of their own shape only (they verify the wire
// structure) and return false on malformed input. Unknown fields are skipped.
bool parseMiuiContactsBak(const std::string& bytes, std::vector<MiuiProtoContactRow>& out);
bool parseMiuiCallLogBak(const std::string& bytes, std::vector<MiuiProtoCallRow>& out);
bool parseMiuiSmsBak(const std::string& bytes, std::vector<MiuiProtoSmsRow>& out);
bool parseMiuiNotesBak(const std::string& bytes, std::vector<MiuiProtoNoteRow>& out);

#endif  // MIUI_BAK_PROTO_PARSERS_H
