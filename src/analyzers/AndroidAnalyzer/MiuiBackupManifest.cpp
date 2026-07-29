#include "MiuiBackupManifest.h"
#include <fstream>
#include <sstream>
#include <regex>

static std::string readFile(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    std::stringstream ss; ss << f.rdbuf();
    return ss.str();
}
static std::string one(const std::string& xml, const std::string& tag) {
    std::regex re("<" + tag + ">([^<]*)</" + tag + ">");
    std::smatch m; return std::regex_search(xml, m, re) ? m[1].str() : std::string();
}
static uint64_t toU64(const std::string& s) {
    try { return s.empty() ? 0 : std::stoull(s); } catch (...) { return 0; }
}

bool parseMiuiManifest(const std::string& backupFolder, BackupMeta& out) {
    std::string path = backupFolder + "/descript.xml";
    std::string xml = readFile(path);
    if (xml.find("MIUI-backup") == std::string::npos) return false;
    out.device = one(xml, "device");
    out.miuiVersion = one(xml, "miuiVersion");
    out.date = toU64(one(xml, "date"));
    out.totalSize = toU64(one(xml, "size"));
    out.sourceFolder = backupFolder;
    out.packages.clear();
    std::regex pkg("<package>([\\s\\S]*?)</package>");
    for (std::sregex_iterator it(xml.begin(), xml.end(), pkg), end; it != end; ++it) {
        std::string body = (*it)[1].str();
        BackupPackage p;
        p.packageName = one(body, "packageName");
        p.bakFile     = one(body, "bakFile");
        p.bakType     = (int)toU64(one(body, "bakType"));
        p.error       = (int)toU64(one(body, "error"));
        p.state       = (int)toU64(one(body, "state"));
        p.pkgSize     = toU64(one(body, "pkgSize"));
        p.sdSize      = toU64(one(body, "sdSize"));
        if (!p.packageName.empty()) out.packages.push_back(std::move(p));
    }
    return true;
}
