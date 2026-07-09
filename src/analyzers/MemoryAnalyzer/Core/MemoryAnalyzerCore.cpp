#include "MemoryAnalyzerDeclarations.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include "../Volatility/Volatility3Runner.h"
#include "../Volatility/VolatilityPlugins.h"
#include "../Parsers/ProcessParser.h"
#include "../Parsers/NetworkParser.h"
#include "../Parsers/BashHistoryParser.h"
#include "../Parsers/BootTimeParser.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include <fstream>
#include <filesystem>
#include <cstdlib>
#include <cstring>
#include <cctype>

using json = nlohmann::json;

MemoryAnalyzer::MemoryAnalyzer(std::string memPath) : memPath_(std::move(memPath)) {}
MemoryAnalyzer::~MemoryAnalyzer() = default;

bool MemoryAnalyzer::initialize() {
    if (outputDbPath_.empty()) {
        // default: <memBasename>_memory.db next to the image
        namespace fs = std::filesystem;
        fs::path p(memPath_);
        outputDbPath_ = (p.parent_path() / (p.stem().string() + "_memory.db")).string();
    }
    db_ = std::make_unique<MemoryAnalysisDatabase>(outputDbPath_);
    if (!db_->initialize()) {
        std::cerr << "[Memory] DB init failed: " << db_->lastError() << std::endl;
        return false;
    }
    runner_ = std::make_unique<Volatility3Runner>(memPath_);
    if (!symbolDir_.empty()) {
        runner_->setSymbolDir(symbolDir_);
    }
    if (Volatility3Runner::resolveVolBinary().empty()) {
        std::cerr << "[Memory] WARNING: volatility3 'vol' not found — analysis will be empty" << std::endl;
    }
    return true;
}

static bool runAndStore(Volatility3Runner& r, MemoryAnalysisDatabase& db, const char* plugin,
                        size_t (*fn)(const json&, MemoryAnalysisDatabase&)) {
    auto res = r.run(plugin);
    if (!res.ok) { db.setMeta(std::string("err:") + plugin, res.stderrText); return false; }
    try {
        json arr = json::parse(res.jsonText);
        fn(arr, db);
    } catch (const std::exception& e) {
        db.setMeta(std::string("parse_err:") + plugin, e.what());
        return false;
    }
    return true;
}

// Scan a memory image for a Linux banner of the form "Linux version X.Y.Z-...".
// vol3 needs an ISF matching this exact version. The banner can be far into a
// large dump (it appeared past 64MB in our 4GB test image), so we stream-scan
// up to SCAN_LIMIT bytes, keeping a tail-overlap window so a banner straddling
// a chunk boundary is still found.
// Returns the full banner line (for logging) via `bannerOut` and the version
// token (e.g. "6.8.0-110-generic") via return value.
static std::string detectKernelVersion(const std::string& memPath,
                                       std::string* bannerOut = nullptr) {
    constexpr std::streamsize CHUNK = 64 * 1024 * 1024;      // 64MB read window
    // The kernel banner can be very deep in a large dump (it appeared at 3.5GB
    // in our 4GB test image), so scan the whole file, not just the head.
    const std::string needle = "Linux version ";

    std::ifstream f(memPath, std::ios::binary);
    if (!f) return "";

    std::string tail;  // overlap from the previous chunk (needle.size()-1 bytes)
    while (true) {
        std::string buf;
        buf.resize(CHUNK);
        f.read(&buf[0], buf.size());
        std::streamsize n = f.gcount();
        if (n <= 0) break;
        buf.resize(n);

        // Search in tail+buf so a banner straddling the boundary is caught.
        // Loop: "Linux version" appears in unrelated strings (e.g. PasswordSafe's
        // "GNU/Linux version of ..."), so we must validate that the token after
        // it looks like a kernel version (starts with a digit) and skip false hits.
        std::string window = tail + buf;
        std::string::size_type searchFrom = 0;
        while (true) {
            auto pos = window.find(needle, searchFrom);
            if (pos == std::string::npos) break;
            // Read until newline / NUL / end of window.
            auto end = pos + needle.size();
            while (end < window.size() && window[end] != '\n' && window[end] != '\0') ++end;
            std::string banner = window.substr(pos, end - pos);
            // Extract version token: "Linux version 6.8.0-110-generic (...)" -> "6.8.0-110-generic"
            auto p = banner.find("version ");
            std::string ver;
            if (p != std::string::npos) {
                p += 8;
                auto e = p;
                while (e < banner.size() && (isalnum(static_cast<unsigned char>(banner[e])) ||
                       banner[e] == '.' || banner[e] == '-' || banner[e] == '_')) ++e;
                if (e > p) ver = banner.substr(p, e - p);
            }
            // A real kernel version starts with a digit (X.Y.Z). "of", "dependencies"
            // etc. are false positives — skip them and keep scanning.
            if (!ver.empty() && isdigit(static_cast<unsigned char>(ver[0]))) {
                if (bannerOut) *bannerOut = banner;
                return ver;
            }
            searchFrom = pos + needle.size();  // try the next occurrence
        }
        // Keep a tail overlap for the next iteration.
        tail = (window.size() >= needle.size()) ? window.substr(window.size() - needle.size()) : window;
    }
    return "";
}

// Locate the project root by searching upward for the symbol-fetch script.
static std::string findProjectRoot() {
    namespace fs = std::filesystem;
    for (fs::path d = fs::current_path(); !d.empty(); d = d.parent_path()) {
        if (fs::exists(d / "scripts" / "build-vol3-isf.sh")) return d.string();
    }
    return "";
}

// Default vol3 2.x symbol scan dir. The fetch script installs ISFs here.
static std::string defaultSymbolDir() {
    const char* home = std::getenv("HOME");
    return home ? std::string(home) + "/.cache/volatility3/symbols" : "";
}

// Try to auto-fetch the ISF for `version` by invoking the project's
// scripts/build-vol3-isf.sh (community repo via CDN, dwarf2json fallback).
// Returns true if the script exited 0 AND the expected ISF file now exists.
static bool autoFetchSymbols(const std::string& version) {
    if (version.empty()) return false;
    std::string root = findProjectRoot();
    if (root.empty()) {
        std::cerr << "[Memory] auto-fetch: cannot locate project root (scripts/build-vol3-isf.sh not found)\n";
        return false;
    }
    std::string script = root + "/scripts/build-vol3-isf.sh";
    std::string cmd = "bash \"" + script + "\" \"" + version + "\" 2>&1";
    std::cout << "[Memory] Auto-fetching ISF for kernel " << version << " ...\n";
    int rc = std::system(cmd.c_str());
    if (rc != 0) {
        std::cerr << "[Memory] auto-fetch: build-vol3-isf.sh failed (exit " << rc << ")\n";
        return false;
    }
    // Confirm the ISF landed where vol3 expects it.
    std::string isf = defaultSymbolDir() + "/linux-" + version + ".json";
    bool ok = std::filesystem::exists(isf);
    if (!ok) {
        std::cerr << "[Memory] auto-fetch: script reported success but " << isf << " not found\n";
    }
    return ok;
}

void MemoryAnalyzer::analyzeMemoryData() {
    std::cout << "[Memory] Analyzing: " << memPath_ << std::endl;
    db_->setMeta("source_image", memPath_);

    auto mark = [&](const char* plugin) {
        std::cout << "  - " << plugin << " ..." << std::flush;
    };
    auto done = [&](bool ok) {
        std::cout << (ok ? " ok" : " FAIL") << std::endl;
    };

    // Run pslist first; if it fails with a symbol-table error, every other
    // plugin will too — so detect that case once and print actionable guidance
    // (the kernel version + how to supply symbols) rather than letting all 5
    // plugins fail silently.
    bool symbolsOk = true;
    mark(MemoryVolatility::PSLIST);
    {
        auto res = runner_->run(MemoryVolatility::PSLIST);
        bool ok = false;
        if (res.ok) {
            try { json arr = json::parse(res.jsonText); ok = parseProcesses(arr, *db_) > 0 || arr.empty(); }
            catch (const std::exception& e) { db_->setMeta("parse_err:linux.pslist", e.what()); }
        } else {
            db_->setMeta("err:linux.pslist", res.stderrText);
            // Detect vol3 symbol/requirement failures. vol3 emits several
            // phrasings depending on version; match them all. The most reliable
            // is "Unable to validate the plugin requirements" (always present).
            if (res.stderrText.find("banner") != std::string::npos ||
                res.stderrText.find("symbol table requirement") != std::string::npos ||
                res.stderrText.find("Unsatisfied requirement") != std::string::npos ||
                res.stderrText.find("Unable to validate the plugin requirements") != std::string::npos) {
                symbolsOk = false;
            }
        }
        done(ok);
    }

    if (!symbolsOk) {
        // vol3 couldn't match symbols. Auto-resolve: detect the kernel version
        // from the image, fetch the ISF via build-vol3-isf.sh, point the runner
        // at the symbol dir, and retry pslist once. Only retry once to avoid
        // loops.
        std::string banner;
        std::string ver = detectKernelVersion(memPath_, &banner);
        std::cerr << "\n[Memory] vol3 could not match kernel symbols.\n";
        if (!banner.empty()) std::cerr << "[Memory] Kernel banner: " << banner << "\n";

        bool recovered = false;
        if (!ver.empty()) {
            std::cerr << "[Memory] Detected kernel: " << ver << "\n";
            if (autoFetchSymbols(ver)) {
                // Point the runner at the freshly-installed symbol dir and retry.
                std::string symDir = defaultSymbolDir();
                if (!symDir.empty()) runner_->setSymbolDir(symDir);
                std::cout << "[Memory] Retrying linux.pslist with new symbols ...\n";
                mark(MemoryVolatility::PSLIST);
                {
                    auto res = runner_->run(MemoryVolatility::PSLIST);
                    bool ok = false;
                    if (res.ok) {
                        try { json arr = json::parse(res.jsonText);
                              ok = parseProcesses(arr, *db_) > 0 || arr.empty(); }
                        catch (const std::exception& e) { db_->setMeta("parse_err:linux.pslist", e.what()); }
                    } else {
                        db_->setMeta("err:linux.pslist", res.stderrText);
                    }
                    done(ok);
                    recovered = ok;
                }
            }
        }

        if (!recovered) {
            std::cerr << "[Memory] Automatic symbol fetch failed.\n"
                      << "[Memory] Try manually: ./scripts/build-vol3-isf.sh "
                      << (ver.empty() ? "<kernel-version>" : ver) << "\n"
                      << "[Memory] Or pass an existing symbol dir: --vol-symbols-dir <dir>\n";
            std::cout << "[Memory] Done (no data — symbols missing) -> " << outputDbPath_ << std::endl;
            return;
        }
        std::cout << "[Memory] Symbols recovered; continuing with remaining plugins.\n";
    }

    // linux.sockstat feeds the network_connections table (there is no
    // linux.netstat in vol3 2.x).
    mark(MemoryVolatility::SOCKSTAT);
    done(runAndStore(*runner_, *db_, MemoryVolatility::SOCKSTAT, parseSockstat));

    mark(MemoryVolatility::BASH);
    done(runAndStore(*runner_, *db_, MemoryVolatility::BASH, parseBashHistory));

    mark(MemoryVolatility::BOOTTIME);
    {   // boottime returns no rows-count; small inline handler
        auto res = runner_->run(MemoryVolatility::BOOTTIME);
        bool ok = res.ok;
        if (ok) {
            try { json a = json::parse(res.jsonText); parseBootTime(a, *db_); }
            catch (const std::exception& e) { db_->setMeta("parse_err:linux.boottime", e.what()); ok = false; }
        } else {
            db_->setMeta("err:linux.boottime", res.stderrText);
        }
        done(ok);
    }

    // Per-process command lines come from linux.psaux (there is no
    // linux.cmdline plugin in vol3).
    mark(MemoryVolatility::PSAUX);
    done(runAndStore(*runner_, *db_, MemoryVolatility::PSAUX, parseCmdline));

    std::cout << "[Memory] Done -> " << outputDbPath_ << std::endl;
}
