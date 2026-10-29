// test_miui_proto_bak_gtest.cpp
// Unit tests for the MIUI offline-backup miui_bak/_tmp_bak protobuf parsers
// (contacts / call logs). Fixtures are real payloads captured from a MIUI 12
// (cepheus, V12.5.6.0.RFACNXM) offline backup.
#include <gtest/gtest.h>

#include <string>

#include "analyzers/AndroidAnalyzer/MiuiBakProtoParsers.h"

namespace {

// apps/com.android.contacts/miui_bak/_tmp_bak from 通话记录(com.android.contacts).bak:
// six outgoing call entries (12315, 12305, 1008611, 10086, 18879500794, 15809649804).
const char kCallLogBak[] =
    "\x12\xa4\x01\x0a\x17\x12\x01\x36\x1a\x05\x31\x32\x33\x31\x35\x20"
    "\x84\xe1\xa4\xa7\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x17\x12\x01"
    "\x35\x1a\x05\x31\x32\x33\x30\x35\x20\x87\xb5\xa4\xa7\xfe\x33\x28"
    "\x00\x30\x02\x38\x01\x0a\x19\x12\x01\x34\x1a\x07\x31\x30\x30\x38"
    "\x36\x31\x31\x20\xc6\xeb\xa3\xa7\xfe\x33\x28\x00\x30\x02\x38\x01"
    "\x0a\x17\x12\x01\x33\x1a\x05\x31\x30\x30\x38\x36\x20\xb7\xc4\xa3"
    "\xa7\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x1d\x12\x01\x32\x1a\x0b"
    "\x31\x38\x38\x37\x39\x35\x30\x30\x37\x39\x34\x20\x8c\xfc\xa2\xa7"
    "\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x1d\x12\x01\x31\x1a\x0b\x31"
    "\x35\x38\x30\x39\x36\x34\x39\x38\x30\x34\x20\xb1\x8f\xa2\xa7\xfe"
    "\x33\x28\x00\x30\x02\x38\x01";
const size_t kCallLogBakSize = sizeof(kCallLogBak) - 1;

// apps/com.android.contacts/miui_bak/_tmp_bak from 联系人(com.android.contacts).bak:
// two contacts (冶梦杰 158 0964 9804, 李尉聪 188 7950 0794), mobile numbers.
const char kContactsBak[] =
    "\x0a\x64\x12\x30\x12\x01\x31\x2a\x18\x0a\x09\xe5\x86\xb6\xe6\xa2"
    "\xa6\xe6\x9d\xb0\x12\x06\xe6\xa2\xa6\xe6\x9d\xb0\x22\x03\xe5\x86"
    "\xb6\x32\x11\x0a\x0d\x31\x35\x38\x20\x30\x39\x36\x34\x20\x39\x38"
    "\x30\x34\x10\x02\x12\x30\x12\x01\x32\x2a\x18\x0a\x09\xe6\x9d\x8e"
    "\xe5\xb0\x89\xe8\x81\xaa\x12\x06\xe5\xb0\x89\xe8\x81\xaa\x22\x03"
    "\xe6\x9d\x8e\x32\x11\x0a\x0d\x31\x38\x38\x20\x37\x39\x35\x30\x20"
    "\x30\x37\x39\x34\x10\x02";
const size_t kContactsBakSize = sizeof(kContactsBak) - 1;

// apps/com.android.mms/miui_bak/_tmp_bak from 短信(com.android.mms).bak:
// two real SMS (a 爱聊 verification code from 106953628954, and a 中国联通
// roaming notice from 10655526112).
const char kSmsBak[] =
    "\x22\xba\x02\x0a\x69\x12\x02\x35\x37\x18\x01\x22\x0c\x31\x30\x36"
    "\x39\x35\x33\x36\x32\x38\x39\x35\x34\x32\x34\xef\xbc\xbb\xe7\x88"
    "\xb1\xe8\x81\x8a\xef\xbc\xbd\xe6\x82\xa8\xe6\x89\x8b\xe6\x9c\xba"
    "\xe5\xb0\xbe\xe5\x8f\xb7\x31\x38\x36\x33\xe7\x9a\x84\xe9\xaa\x8c"
    "\xe8\xaf\x81\xe7\xa0\x81\xe6\x98\xaf\x35\x36\x38\x32\x35\x34\x38"
    "\xce\xf1\xad\xd1\x9b\x31\x40\x01\x48\x01\x50\xff\xff\xff\xff\xff"
    "\xff\xff\xff\xff\x01\x58\x00\x68\x00\x78\x00\x88\x01\x00\x0a\xcc"
    "\x01\x12\x01\x31\x18\x01\x22\x0a\x31\x30\x36\x35\x35\x35\x32\x36"
    "\x31\x31\x32\x9b\x01\xe4\xb8\xad\xe5\x9b\xbd\xe8\x81\x94\xe9\x80"
    "\x9a\xe6\xb8\xa9\xe9\xa6\xa8\xe6\x8f\x90\xe9\x86\x92\xef\xbc\x9a"
    "\xe6\x82\xa8\xe5\x88\x9a\xe6\x89\x8d\xe6\x8e\xa5\xe5\x90\xac\xe7"
    "\x9a\x84\xe7\x94\xb5\xe8\xaf\x9d\x30\x30\x31\x38\x33\x32\x35\x36"
    "\x34\x33\x31\x39\x39\xe4\xb8\xba\xe5\xa2\x83\xe5\xa4\x96\xe6\x9d"
    "\xa5\xe7\x94\xb5\xef\xbc\x8c\xe8\xaf\xb7\xe6\xb3\xa8\xe6\x84\x8f"
    "\xe8\xbe\xa8\xe5\x88\xab\xef\xbc\x8c\xe9\x98\xb2\xe8\x8c\x83\xe9"
    "\xa3\x8e\xe9\x99\xa9\xe3\x80\x82\xe5\x8f\x96\xe6\xb6\x88\xe8\xaf"
    "\xa5\xe7\x9f\xad\xe4\xbf\xa1\xe6\x8f\x90\xe9\x86\x92\xe8\xaf\xb7"
    "\xe5\x9b\x9e\xe5\xa4\x8d\xe2\x80\x9c\x39\xe2\x80\x9d\xe3\x80\x82"
    "\x38\x98\xf9\xfb\xc4\xb0\x31\x40\x01\x48\x01\x50\xff\xff\xff\xff"
    "\xff\xff\xff\xff\xff\x01\x58\x00\x78\x00\x88\x01\x00";
const size_t kSmsBakSize = sizeof(kSmsBak) - 1;

// apps/com.miui.notes/miui_bak/_tmp_bak from 笔记(com.miui.notes).bak:
// two notes - 购物清单 / "牛奶咖啡 水果 衣服" and 生日 / "明天阿亮生日".
const char kNotesBak[] =
    "\x32\xc8\x02\x12\xac\x01\x12\x01\x31\x18\x00\x20\x00\x28\xaf\xa2"
    "\xf0\x99\xb9\x31\x30\xc8\xa2\xbe\x9b\xb9\x31\x38\x00\x42\x1a\xe7"
    "\x89\x9b\xe5\xa5\xb6\xe5\x92\x96\xe5\x95\xa1\x20\xe6\xb0\xb4\xe6"
    "\x9e\x9c\x20\xe8\xa1\xa3\xe6\x9c\x8d\x4a\x57\x0a\x21\x76\x6e\x64"
    "\x2e\x61\x6e\x64\x72\x6f\x69\x64\x2e\x63\x75\x72\x73\x6f\x72\x2e"
    "\x69\x74\x65\x6d\x2f\x74\x65\x78\x74\x5f\x6e\x6f\x74\x65\x10\xc8"
    "\xa0\xf0\x99\xb9\x31\x18\xc8\xa0\xf0\x99\xb9\x31\x22\x1a\xe7\x89"
    "\x9b\xe5\xa5\xb6\xe5\x92\x96\xe5\x95\xa1\x20\xe6\xb0\xb4\xe6\x9e"
    "\x9c\x20\xe8\xa1\xa3\xe6\x9c\x8d\x28\x00\x30\x00\x3a\x00\x42\x00"
    "\x4a\x00\x60\x00\x68\x00\x72\x0c\xe8\xb4\xad\xe7\x89\xa9\xe6\xb8"
    "\x85\xe5\x8d\x95\x7a\x06\x63\x6f\x6d\x6d\x6f\x6e\x82\x01\x00\x8a"
    "\x01\x00\x12\x96\x01\x12\x01\x32\x18\x00\x20\x00\x28\x8f\xdc\xbe"
    "\x9b\xb9\x31\x30\xc6\xd2\xbf\x9b\xb9\x31\x38\x00\x42\x12\xe6\x98"
    "\x8e\xe5\xa4\xa9\xe9\x98\xbf\xe4\xba\xae\xe7\x94\x9f\xe6\x97\xa5"
    "\x4a\x4f\x0a\x21\x76\x6e\x64\x2e\x61\x6e\x64\x72\x6f\x69\x64\x2e"
    "\x63\x75\x72\x73\x6f\x72\x2e\x69\x74\x65\x6d\x2f\x74\x65\x78\x74"
    "\x5f\x6e\x6f\x74\x65\x10\xb8\xd6\xbe\x9b\xb9\x31\x18\xb8\xd6\xbe"
    "\x9b\xb9\x31\x22\x12\xe6\x98\x8e\xe5\xa4\xa9\xe9\x98\xbf\xe4\xba"
    "\xae\xe7\x94\x9f\xe6\x97\xa5\x28\x00\x30\x00\x3a\x00\x42\x00\x4a"
    "\x00\x60\x00\x68\x00\x72\x06\xe7\x94\x9f\xe6\x97\xa5\x7a\x06\x63"
    "\x6f\x6d\x6d\x6f\x6e\x82\x01\x00\x8a\x01\x00";
const size_t kNotesBakSize = sizeof(kNotesBak) - 1;

std::string fixture(const char* data, size_t size) {
    return std::string(data, size);
}

}  // namespace

TEST(MiuiBakClassifyTest, DetectsJsonSettings) {
    const std::string json =
        "{\"packageName\":\"com.android.mms\",\"version\":1,"
        "\"data\":[{\"key\":\"MessageSettings\",\"type\":\"json\",\"value\":{}}]}";
    EXPECT_EQ(classifyMiuiBakContent(json), MiuiBakKind::Json);
}

TEST(MiuiBakClassifyTest, DetectsCallLogAndContacts) {
    EXPECT_EQ(classifyMiuiBakContent(fixture(kCallLogBak, kCallLogBakSize)),
              MiuiBakKind::CallLog);
    EXPECT_EQ(classifyMiuiBakContent(fixture(kContactsBak, kContactsBakSize)),
              MiuiBakKind::Contacts);
}

TEST(MiuiBakClassifyTest, EmptyStateTemplateIsUnknown) {
    // apps/com.miui.gallery _tmp_bak: an all-zeros state template with no records.
    const std::string empty = std::string("\x20\x00\x2a\x00\x32\x00\x3a\x00", 8);
    EXPECT_EQ(classifyMiuiBakContent(empty), MiuiBakKind::Unknown);
    EXPECT_EQ(classifyMiuiBakContent(""), MiuiBakKind::Unknown);
}

TEST(MiuiBakClassifyTest, TruncatedPayloadIsUnknown) {
    std::string truncated(fixture(kCallLogBak, kCallLogBakSize));
    truncated.resize(40);  // cuts inside the second call entry
    EXPECT_EQ(classifyMiuiBakContent(truncated), MiuiBakKind::Unknown);
}

TEST(MiuiCallLogBakTest, ParsesRealBackupEntries) {
    std::vector<MiuiProtoCallRow> rows;
    ASSERT_TRUE(parseMiuiCallLogBak(fixture(kCallLogBak, kCallLogBakSize), rows));
    ASSERT_EQ(rows.size(), 6u);

    // Newest entry first in the payload.
    EXPECT_EQ(rows[0].number, "12315");
    EXPECT_EQ(rows[0].dateMs, 1786251915396ull);
    EXPECT_EQ(rows[0].type, 2);  // outgoing
    EXPECT_EQ(rows[5].number, "15809649804");
    EXPECT_EQ(rows[5].dateMs, 1786251872177ull);
}

TEST(MiuiCallLogBakTest, RejectsJsonAndGarbage) {
    std::vector<MiuiProtoCallRow> rows;
    EXPECT_FALSE(parseMiuiCallLogBak("{\"packageName\":\"x\"}", rows));
    EXPECT_FALSE(parseMiuiCallLogBak("not protobuf at all", rows));
}

TEST(MiuiContactsBakTest, ParsesRealBackupContacts) {
    std::vector<MiuiProtoContactRow> rows;
    ASSERT_TRUE(parseMiuiContactsBak(fixture(kContactsBak, kContactsBakSize), rows));
    ASSERT_EQ(rows.size(), 2u);

    EXPECT_EQ(rows[0].displayName, "冶梦杰");
    EXPECT_EQ(rows[0].nickname, "梦杰");
    // Raw number keeps MIUI's grouping spaces; the analyzer normalizes them.
    EXPECT_EQ(rows[0].number, "158 0964 9804");
    EXPECT_EQ(rows[0].numberType, 2);  // TYPE_MOBILE
    EXPECT_EQ(rows[1].displayName, "李尉聪");
    EXPECT_EQ(rows[1].number, "188 7950 0794");
}

TEST(MiuiContactsBakTest, RejectsJsonAndCallLogShape) {
    std::vector<MiuiProtoContactRow> rows;
    EXPECT_FALSE(parseMiuiContactsBak("{\"packageName\":\"x\"}", rows));
    EXPECT_FALSE(parseMiuiContactsBak(fixture(kCallLogBak, kCallLogBakSize), rows));
}

TEST(MiuiContactsBakTest, OneRowPerPhoneWhenContactHasSeveral) {
    // contact { data { f2 id "1", f5 name 张三, f6 "111" type 2, f6 "122" type 7 } }
    std::string proto;
    proto += std::string("\x0a\x21", 2);  // f1 ContactRecord len 33
    proto += std::string("\x12\x1f", 2);  // f2 DataRecord len 31
    proto += std::string("\x12\x01\x31", 3);                // f2 id "1"
    proto += std::string("\x2a\x08\x0a\x06"
                         "\xe5\xbc\xa0\xe4\xb8\x89",       // f5 { f1 张三 }
                         10);
    proto += std::string("\x32\x07\x0a\x03\x31\x31\x31\x10\x02", 9);  // f6 "111" mobile
    proto += std::string("\x32\x07\x0a\x03\x31\x32\x32\x10\x07", 9);  // f6 "122" type 7

    std::vector<MiuiProtoContactRow> rows;
    ASSERT_TRUE(parseMiuiContactsBak(proto, rows));
    ASSERT_EQ(rows.size(), 2u);
    EXPECT_EQ(rows[0].displayName, "张三");
    EXPECT_EQ(rows[0].number, "111");
    EXPECT_EQ(rows[0].numberType, 2);
    EXPECT_EQ(rows[1].displayName, "张三");
    EXPECT_EQ(rows[1].number, "122");
    EXPECT_EQ(rows[1].numberType, 7);
}

TEST(MiuiContactsBakTest, SkipsGroupingRecordWithoutLosingRealContacts) {
    // A real MIUI 12 export appends a contact-grouping DataRecord (id + status
    // only, no f5/f6). It used to fail the whole payload, discarding the 668
    // real contacts that preceded it.
    std::string proto;
    proto += std::string("\x0a\x18", 2);  // f1 ContactRecord len 24
    proto += std::string("\x12\x16", 2);  // f2 DataRecord len 22
    proto += std::string("\x12\x01\x31", 3);                // f2 id "1"
    proto += std::string("\x2a\x08\x0a\x06"
                         "\xe5\xbc\xa0\xe4\xb8\x89",       // f5 { f1 张三 }
                         10);
    proto += std::string("\x32\x07\x0a\x03\x31\x31\x31\x10\x02", 9);  // f6 "111"
    // Trailing grouping record: only id + status, no name and no phone.
    proto += std::string("\x0a\x0b\x12\x09\x12\x03\x36\x36\x39\x18\x01\x20\x00",
                         13);

    std::vector<MiuiProtoContactRow> rows;
    ASSERT_TRUE(parseMiuiContactsBak(proto, rows));
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0].displayName, "张三");
    EXPECT_EQ(rows[0].number, "111");
    EXPECT_EQ(classifyMiuiBakContent(proto), MiuiBakKind::Contacts);
}

TEST(MiuiSmsBakTest, ParsesRealBackupMessages) {
    std::vector<MiuiProtoSmsRow> rows;
    ASSERT_TRUE(parseMiuiSmsBak(fixture(kSmsBak, kSmsBakSize), rows));
    ASSERT_EQ(rows.size(), 2u);
    EXPECT_EQ(rows[0].address, "106953628954");
    EXPECT_NE(rows[0].body.find("568254"), std::string::npos);
    EXPECT_EQ(rows[0].dateMs, 1691045558478ull);
    EXPECT_EQ(rows[0].type, 1);  // MESSAGE_TYPE_INBOX
    EXPECT_EQ(rows[1].address, "1065552611");
    EXPECT_NE(rows[1].body.find("中国联通"), std::string::npos);
}

TEST(MiuiSmsBakTest, ClassifiedAsSmsAndRejectsOtherShapes) {
    EXPECT_EQ(classifyMiuiBakContent(fixture(kSmsBak, kSmsBakSize)), MiuiBakKind::Sms);
    std::vector<MiuiProtoSmsRow> rows;
    EXPECT_FALSE(parseMiuiSmsBak("{\"packageName\":\"x\"}", rows));
    EXPECT_FALSE(parseMiuiSmsBak(fixture(kContactsBak, kContactsBakSize), rows));
    EXPECT_FALSE(parseMiuiSmsBak(fixture(kCallLogBak, kCallLogBakSize), rows));
}

TEST(MiuiNotesBakTest, ParsesRealBackupNotes) {
    std::vector<MiuiProtoNoteRow> rows;
    ASSERT_TRUE(parseMiuiNotesBak(fixture(kNotesBak, kNotesBakSize), rows));
    ASSERT_EQ(rows.size(), 2u);
    EXPECT_EQ(rows[0].noteId, "1");
    EXPECT_EQ(rows[0].title, "购物清单");
    EXPECT_EQ(rows[0].snippet, "牛奶咖啡 水果 衣服");
    EXPECT_EQ(rows[0].kind, "common");
    EXPECT_GT(rows[0].createdMs, 0ull);
    EXPECT_GT(rows[0].modifiedMs, rows[0].createdMs);
    EXPECT_EQ(rows[1].title, "生日");
    EXPECT_EQ(rows[1].snippet, "明天阿亮生日");
}

TEST(MiuiNotesBakTest, ClassifiedAsNotesAndNotConfusedWithOtherShapes) {
    EXPECT_EQ(classifyMiuiBakContent(fixture(kNotesBak, kNotesBakSize)), MiuiBakKind::Notes);
    std::vector<MiuiProtoNoteRow> rows;
    EXPECT_FALSE(parseMiuiNotesBak(fixture(kSmsBak, kSmsBakSize), rows));
    EXPECT_FALSE(parseMiuiNotesBak(fixture(kContactsBak, kContactsBakSize), rows));
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
