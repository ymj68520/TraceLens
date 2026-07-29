#include <gtest/gtest.h>
#include <cstdint>
#include <limits>
#include <string>
#include <vector>
#include "CommandLineParser.h"

namespace {

forensics::CommandLineArgs parse(std::vector<std::string> values) {
    std::vector<char*> argv;
    argv.reserve(values.size());
    for (auto& value : values) argv.push_back(value.data());
    return forensics::CommandLineParser::parse(
        static_cast<int>(argv.size()), argv.data());
}

TEST(CommandLineParserSizeLimit, ConvertsBinaryUnitsAndIgnoresCase) {
    const auto oneK = parse({"analyzer", "disk.E01", "--dump-text-max-size", "1K"});
    const auto fiveHundredM = parse({"analyzer", "disk.E01", "--dump-text-max-size", "500M"});
    const auto twoG = parse({"analyzer", "disk.E01", "--dump-text-max-size", "2g"});
    const auto oneT = parse({"analyzer", "disk.E01", "--dump-text-max-size", "1T"});

    ASSERT_TRUE(oneK.dump_text_max_bytes.has_value());
    EXPECT_EQ(*oneK.dump_text_max_bytes, 1024ULL);
    EXPECT_EQ(*fiveHundredM.dump_text_max_bytes, 500ULL * 1024ULL * 1024ULL);
    EXPECT_EQ(*twoG.dump_text_max_bytes, 2ULL * 1024ULL * 1024ULL * 1024ULL);
    EXPECT_EQ(*oneT.dump_text_max_bytes, 1024ULL * 1024ULL * 1024ULL * 1024ULL);
    EXPECT_TRUE(oneK.dump_text);
    EXPECT_TRUE(oneK.parse_error.empty());
}

TEST(CommandLineParserSizeLimit, LeavesLegacyDumpUnlimited) {
    const auto args = parse({"analyzer", "disk.E01", "--dump-text"});
    EXPECT_TRUE(args.dump_text);
    EXPECT_FALSE(args.dump_text_max_bytes.has_value());
    EXPECT_TRUE(args.parse_error.empty());
}

class InvalidSize : public ::testing::TestWithParam<const char*> {};
TEST_P(InvalidSize, RejectsInvalidValue) {
    const auto args = parse({"analyzer", "disk.E01", "--dump-text-max-size", GetParam()});
    EXPECT_FALSE(args.parse_error.empty());
    EXPECT_FALSE(args.dump_text_max_bytes.has_value());
}
INSTANTIATE_TEST_SUITE_P(
    Grammar, InvalidSize,
    ::testing::Values("0M", "-1G", "1.5G", "500", "10MB", "2GiB", "4P", ""));

TEST(CommandLineParserSizeLimit, RejectsOverflow) {
    const auto args = parse({
        "analyzer", "disk.E01", "--dump-text-max-size", "18446744073709551615T"});
    EXPECT_FALSE(args.parse_error.empty());
}

TEST(CommandLineParserSizeLimit, RejectsMissingValue) {
    const auto args = parse({"analyzer", "disk.E01", "--dump-text-max-size"});
    EXPECT_FALSE(args.parse_error.empty());
}

TEST(CommandLineParserAndroidSource, ParsesMiuiBackupModeAndPassword) {
    const auto args = parse({"analyzer", "/evidence/miui", "--android-analyze",
                             "--android-source", "miui-backup",
                             "--backup-password", "do-not-log-this"});

    EXPECT_TRUE(args.android_analyze);
    EXPECT_EQ(args.android_source, "miui-backup");
    EXPECT_EQ(args.backup_password, "do-not-log-this");
}

TEST(CommandLineParserAndroidSource, PreservesLegacySourceValues) {
    for (const char* mode : {"tsk", "dir", "zip"}) {
        const auto args = parse({"analyzer", "source", "--android-analyze",
                                 "--android-source", mode});
        EXPECT_EQ(args.android_source, mode);
        EXPECT_TRUE(args.backup_password.empty());
        EXPECT_TRUE(args.parse_error.empty());
    }
}

TEST(CommandLineParserAndroidSource, RejectsFlagAsSourceValueBeforeConsumingSecret) {
    const auto args = parse({"analyzer", "/evidence/miui", "--android-analyze",
                             "--android-source", "--backup-password", "topsecret"});

    EXPECT_FALSE(args.parse_error.empty());
    EXPECT_TRUE(args.android_source.empty());
    EXPECT_TRUE(args.backup_password.empty());
    EXPECT_EQ(args.image_path, "/evidence/miui");
}

TEST(CommandLineParserAndroidSource, RejectsUnknownSource) {
    const auto args = parse({"analyzer", "/evidence/miui", "--android-analyze",
                             "--android-source", "vendor-backup"});

    EXPECT_FALSE(args.parse_error.empty());
    EXPECT_TRUE(args.android_source.empty());
}

TEST(CommandLineParserAndroidSource, RejectsFlagAsBackupPasswordValue) {
    const auto args = parse({"analyzer", "/evidence/miui", "--android-analyze",
                             "--android-source", "miui-backup",
                             "--backup-password", "--no-ai"});

    EXPECT_FALSE(args.parse_error.empty());
    EXPECT_TRUE(args.backup_password.empty());
}

} // namespace
