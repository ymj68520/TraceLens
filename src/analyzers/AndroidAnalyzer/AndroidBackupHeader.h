#pragma once
#include <string>
#include <cstdint>

enum class BackupEncryption { None, Aes256, Unknown };
struct AndroidBackupHeader {
    int version = 0;
    int compression = 0;
    BackupEncryption encryption = BackupEncryption::None;
    uint64_t payloadOffset = 0;
    std::string encMarker;
};
bool parseAndroidBackupHeader(const std::string& bakPath, AndroidBackupHeader& out);
