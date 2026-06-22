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
#include <filesystem>

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

void MemoryAnalyzer::analyzeMemoryData() {
    std::cout << "[Memory] Analyzing: " << memPath_ << std::endl;
    db_->setMeta("source_image", memPath_);

    auto mark = [&](const char* plugin) {
        std::cout << "  - " << plugin << " ..." << std::flush;
    };
    auto done = [&](bool ok) {
        std::cout << (ok ? " ok" : " FAIL") << std::endl;
    };

    mark(MemoryVolatility::PSLIST);
    done(runAndStore(*runner_, *db_, MemoryVolatility::PSLIST, parseProcesses));

    mark(MemoryVolatility::NETSTAT);
    done(runAndStore(*runner_, *db_, MemoryVolatility::NETSTAT, parseNetstat));

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

    // cmdline: store raw args (no dedicated parser needed beyond insertCmdline)
    mark(MemoryVolatility::CMDLINE);
    {
        auto res = runner_->run(MemoryVolatility::CMDLINE);
        bool ok = false;
        if (res.ok) {
            try {
                json a = json::parse(res.jsonText);
                if (a.is_array()) {
                    ok = true;
                    for (const auto& c : a) {
                        db_->insertCmdline(c.value("PID", 0),
                                           c.value("Process", std::string("")),
                                           c.value("Args", c.value("Command", std::string(""))));
                    }
                }
            } catch (const std::exception& e) {
                db_->setMeta("parse_err:linux.cmdline", e.what());
            }
        } else {
            db_->setMeta("err:linux.cmdline", res.stderrText);
        }
        done(ok);
    }

    std::cout << "[Memory] Done -> " << outputDbPath_ << std::endl;
}
