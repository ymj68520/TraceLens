#include "AndroidBackupHeader.h"
#include <fstream>
#include <vector>
#include <cstring>

static std::string readAll(const std::string& path, size_t cap) {
    std::ifstream f(path, std::ios::binary);
    std::string s((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    if (s.size() > cap) s.resize(cap);
    return s;
}

bool parseAndroidBackupHeader(const std::string& bakPath, AndroidBackupHeader& out) {
    // The MIUI header is variable-length; only the first ~1 KiB is needed.
    std::string buf = readAll(bakPath, 4096);
    const std::string magic = "ANDROID BACKUP\n";
    auto pos = buf.find(magic);
    if (pos == std::string::npos) return false;
    // After the magic: version\n compression\n encryption\n  then the payload.
    size_t cur = pos + magic.size();
    auto nextLine = [&](std::string& dst) -> bool {
        auto nl = buf.find('\n', cur);
        if (nl == std::string::npos) return false;
        dst.assign(buf, cur, nl - cur);
        cur = nl + 1;
        return true;
    };
    std::string ver, comp, enc;
    if (!nextLine(ver) || !nextLine(comp) || !nextLine(enc)) return false;
    try { out.version = std::stoi(ver); } catch (...) { return false; }
    try { out.compression = std::stoi(comp); } catch (...) { out.compression = 0; }
    out.encMarker = enc;
    if (enc == "none") out.encryption = BackupEncryption::None;
    else if (enc == "AES-256-encrypted") out.encryption = BackupEncryption::Aes256;
    else out.encryption = BackupEncryption::Unknown;
    out.payloadOffset = cur;
    return true;
}
