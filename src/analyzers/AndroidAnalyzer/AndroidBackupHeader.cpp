#include "AndroidBackupHeader.h"
#include <fstream>

static std::string readHead(const std::string& path, size_t cap) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return {};
    std::string s(cap, '\0');
    f.read(&s[0], static_cast<std::streamsize>(cap));
    s.resize(static_cast<size_t>(f.gcount()));
    return s;
}

bool parseAndroidBackupHeader(const std::string& bakPath, AndroidBackupHeader& out) {
    // Reset on entry so no stale fields persist on a false-return path.
    out = AndroidBackupHeader{};
    // The MIUI header is variable-length; only the first ~1 KiB is needed.
    // Read only the first `cap` bytes - never slurp a multi-hundred-MB .bak.
    std::string buf = readHead(bakPath, 4096);
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
    // Strict parse: a non-numeric version or compression field is malformed
    // input - fail loudly rather than silently defaulting (no silent failure).
    try { out.version = std::stoi(ver); } catch (...) { return false; }
    try { out.compression = std::stoi(comp); } catch (...) { return false; }
    out.encMarker = enc;
    if (enc == "none") out.encryption = BackupEncryption::None;
    else if (enc == "AES-256-encrypted") out.encryption = BackupEncryption::Aes256;
    else out.encryption = BackupEncryption::Unknown;
    out.payloadOffset = cur;
    return true;
}
