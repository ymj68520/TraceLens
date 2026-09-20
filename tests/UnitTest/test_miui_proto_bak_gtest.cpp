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

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
