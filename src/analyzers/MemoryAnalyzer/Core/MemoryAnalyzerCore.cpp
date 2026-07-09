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
#include <cctype>
#include <fstream>
#include <filesystem>
#include <cstring>

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

// Scan the first chunk of a memory image for a Linux banner of the form
// "Linux version X.Y.Z-...". vol3 needs an ISF matching this exact version.
static std::string detectKernelVersion(const std::string& memPath) {
    std::ifstream f(memPath, std::ios::binary);
    if (!f) return "";
    // The banner lives in the first ~64MB on most kernels.
    std::string buf;
    buf.resize(64 * 1024 * 1024);
    f.read(&buf[0], buf.size());
    std::streamsize n = f.gcount();
    buf.resize(n);
    const std::string needle = "Linux version ";
    auto pos = buf.find(needle);
    if (pos == std::string::npos) return "";
    // Read until newline / end of printable.
    auto end = pos + needle.size();
    while (end < buf.size() && buf[end] != '\n' && buf[end] != '\0') ++end;
    return buf.substr(pos, end - pos);
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
            if (res.stderrText.find("banner") != std::string::npos ||
                res.stderrText.find("symbol table requirement") != std::string::npos ||
                res.stderrText.find("Unsatisfied requirement") != std::string::npos) {
                symbolsOk = false;
            }
        }
        done(ok);
    }

    if (!symbolsOk) {
        std::string banner = detectKernelVersion(memPath_);
        std::cerr << "\n[Memory] ERROR: Volatility3 could not match kernel symbols.\n";
        if (!banner.empty()) {
            std::cerr << "[Memory] Kernel banner: " << banner << "\n";
        }
        // Extract the version token (e.g. "6.8.0-110-generic") for a copy-paste
        // hint, falling back to a placeholder.
        std::string ver = "6.8.0-110-generic";
        {
            // "Linux version 6.8.0-110-generic (...)"
            auto p = banner.find("version ");
            if (p != std::string::npos) {
                p += 8;
                auto e = p;
                while (e < banner.size() && (isalnum(static_cast<unsigned char>(banner[e])) ||
                       banner[e] == '.' || banner[e] == '-' || banner[e] == '_')) ++e;
                if (e > p) ver = banner.substr(p, e - p);
            }
        }
        std::cerr << "[Memory] vol3 needs an ISF symbol file matching this kernel.\n"
                  << "[Memory] Fix — run from the project root:\n"
                  << "[Memory]   ./scripts/build-vol3-isf.sh " << ver << "\n"
                  << "[Memory]   (downloads the ISF; then re-run this analyzer)\n"
                  << "[Memory] Or pass an existing symbol dir: --vol-symbols-dir <dir>\n";
        std::cout << "[Memory] Done (no data — symbols missing) -> " << outputDbPath_ << std::endl;
        return;
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
