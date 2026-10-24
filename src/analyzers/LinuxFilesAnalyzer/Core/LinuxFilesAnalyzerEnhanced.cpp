// LinuxFilesAnalyzerEnhanced.cpp
// Web-server analysis and enhanced-analysis methods of LinuxFilesAnalyzer
// (Apache/Nginx logs, event correlation, timeline reconstruction,
//  anomaly detection, rule engine / attack chain analysis)

#include "LinuxFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <set>
#include <limits>
#include <openssl/evp.h>
#include <iomanip>
#include <map>
#include <nlohmann/json.hpp>
#include <stdexcept>

// Web server parsers
#include "Parsers/WebServer/ApacheParser.h"
#include "Parsers/WebServer/NginxParser.h"

// Enhanced analysis
#include "Analysis/LogCorrelationEngine.h"
#include "Analysis/TimelineReconstructor.h"
#include "Analysis/AnomalyDetector.h"

// Phase 16: Rule engine
#include "Analysis/RuleEngine.h"

using forensics::linux::RuleEngine;

namespace fs = std::filesystem;

// ============================================================================
// Web Server Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::analyzeApacheServers() {
    std::cout << "Analyzing Apache web servers..." << std::endl;

    // Look for Apache logs in common locations
    std::vector<std::string> logPatterns = {
        "var/log/apache2/access.log%",
        "var/log/apache2/error.log%",
        "var/log/httpd/access.log%",
        "var/log/httpd/error.log%",
        "var/log/apache2/%.log",
        "var/log/httpd/%.log"
    };

    std::string extractPath = getExtractPath("apache");
    fs::create_directories(extractPath);

    int totalLogs = 0;
    for (const auto& pattern : logPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".log";
            if (extractFileToPath(file.inode, outputPath, file.partitionNum)) {
                auto parseResult = ApacheParser::parseAccessLog(outputPath);
                if (!parseResult.accessLogs.empty()) {
                    linuxDb_->insertApacheAccessLogs(parseResult.accessLogs);
                    totalLogs += parseResult.accessLogs.size();
                }
            }
        }
    }

    if (totalLogs > 0) {
        std::cout << "  Parsed " << totalLogs << " Apache log entries" << std::endl;
    } else {
        std::cout << "  No Apache logs found (skipping)" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzeNginxServers() {
    std::cout << "正在解析 Nginx 与宝塔 Web 日志…" << std::endl;
    const std::vector<std::string> patterns = {
        "var/log/nginx/access.log%", "var/log/nginx/%.log",
        "www/wwwlogs/%.log%", "www/server/nginx/logs/access.log%"
    };
    const auto extracted = getExtractPath("nginx");
    fs::create_directories(extracted);
    std::set<std::pair<int, int64_t>> seen;
    size_t total = 0;
    for (const auto& pattern : patterns) {
        for (const auto& file : queryFilesByPattern(pattern)) {
            if (file.type != "REG" || file.isDeleted || file.size <= 0 || !seen.emplace(file.partitionNum, file.inode).second) continue;
            const auto extension = fs::path(file.name).extension().string();
            if (extension == ".gz" || extension == ".xz" || extension == ".bz2") {
                std::cout << "压缩 Web 日志保留为文件证据，尚未结构化解析：" << file.path << std::endl;
                continue;
            }
            const auto local = extracted + "/" + std::to_string(file.partitionNum) + "_" + std::to_string(file.inode) + ".log";
            if (!extractFileToPath(file.inode, local, file.partitionNum))
                throw std::runtime_error("Nginx 日志提取失败：" + file.path);
            std::ifstream input(local, std::ios::binary);
            if (!input) throw std::runtime_error("无法读取提取的 Nginx 日志");
            std::vector<NginxAccessLogEntry> batch;
            std::string line;
            std::vector<char> lineBuffer(16 * 1024 + 1);
            int64_t lineNumber = 0, oversized = 0;
            while (input) {
                const auto offset = input.tellg();
                input.getline(lineBuffer.data(), static_cast<std::streamsize>(lineBuffer.size()));
                if (input.bad()) break;
                if (input.fail() && !input.eof()) {
                    ++lineNumber; ++oversized;
                    input.clear(); input.ignore(std::numeric_limits<std::streamsize>::max(), '\n');
                    continue;
                }
                if (input.gcount() == 0) break;
                ++lineNumber;
                line.assign(lineBuffer.data(), static_cast<size_t>(input.gcount()) - (input.eof() ? 0 : 1));
                if (line.find('\0') != std::string::npos) { ++oversized; continue; }
                if (line.empty()) continue;
                auto record = NginxParser::parseLogLine(line);
                if (record.statusCode <= 0) continue;
                record.sourcePartition = file.partitionNum;
                record.provenance.sourceFile = file.path;
                record.provenance.sourceLine = lineNumber;
                record.provenance.sourceOffset = static_cast<int64_t>(offset);
                record.provenance.sourceInode = file.inode;
                record.provenance.sourceHash = file.md5;
                record.provenance.rawRecord = line;
                record.provenance.parserVersion = "nginx-lines:v2";
                batch.push_back(std::move(record));
                if (batch.size() >= 1000) {
                    if (!linuxDb_->insertNginxAccessLogs(batch)) throw std::runtime_error("Nginx 记录写入失败");
                    total += batch.size(); batch.clear();
                }
            }
            if (input.bad()) throw std::runtime_error("Nginx 日志读取中断");
            if (oversized) std::cout << "Nginx 日志有 " << oversized << " 条超长或含 NUL 的行未解析，原始文件仍保留：" << file.path << std::endl;
            if (!batch.empty()) {
                if (!linuxDb_->insertNginxAccessLogs(batch)) throw std::runtime_error("Nginx 记录写入失败");
                total += batch.size();
            }
        }
    }
    std::cout << "已解析 Nginx 访问日志：" << total << " 条" << std::endl;
    std::set<std::pair<int, int64_t>> configs;
    for (const std::string pattern : {"etc/nginx/%.conf", "www/server/nginx/conf/%.conf", "www/server/panel/vhost/nginx/%.conf"}) {
        for (const auto& file : queryFilesByPattern(pattern)) {
            if (file.type != "REG" || file.isDeleted || file.size <= 0 || file.size > 16 * 1024 * 1024 ||
                !configs.emplace(file.partitionNum, file.inode).second) continue;
            const auto local = extracted + "/" + std::to_string(file.partitionNum) + "_" + std::to_string(file.inode) + ".conf";
            if (!extractFileToPath(file.inode, local, file.partitionNum)) continue;
            std::ifstream input(local, std::ios::binary);
            const std::string content((std::istreambuf_iterator<char>(input)), {});
            const auto parsed = NginxParser::parseServerBlocks(content, file.path);
            if (!parsed.serverBlocks.empty() && !linuxDb_->insertNginxServerBlocks(parsed.serverBlocks))
                throw std::runtime_error("Nginx 配置记录写入失败");
        }
    }
    // BaoTa writes JSON arrays, one request per line. These describe panel
    // administration, not website Nginx traffic. Preserve local time verbatim.
    sqlite3* db = linuxDb_->getDb();
    const char* schema = R"SQL(
      CREATE TABLE IF NOT EXISTS linux_panel_requests(
        id INTEGER PRIMARY KEY, timestamp_raw TEXT, client_address TEXT, method TEXT, url TEXT,
        user_agent TEXT, form_data TEXT, duration_ms INTEGER, status_code INTEGER, response_size INTEGER,
        source_file TEXT, source_line INTEGER, source_offset INTEGER, source_inode INTEGER,
        source_partition INTEGER, source_sha256 TEXT, raw_record TEXT, parser_version TEXT);
      CREATE TABLE IF NOT EXISTS linux_panel_request_sources(
        source_file TEXT, source_partition INTEGER, source_inode INTEGER, source_sha256 TEXT,
        canonical_source TEXT, parsed_records INTEGER, rejected_records INTEGER,
        PRIMARY KEY(source_file,source_partition));
    )SQL";
    if (sqlite3_exec(db, schema, nullptr, nullptr, nullptr) != SQLITE_OK)
        throw std::runtime_error("宝塔请求记录表初始化失败");
    std::map<std::string, std::pair<std::string, int64_t>> sameContent;
    std::set<std::pair<int, int64_t>> requestFiles;
    int64_t panelRecords = 0;
    for (const std::string pattern : {"www/wwwlogs/request/%.json", "www/server/panel/logs/request/%.json"}) {
        for (const auto& file : queryFilesByPattern(pattern)) {
            if (file.type != "REG" || file.isDeleted || file.size <= 0 ||
                !requestFiles.emplace(file.partitionNum, file.inode).second) continue;
            const auto local = extracted + "/" + std::to_string(file.partitionNum) + "_" + std::to_string(file.inode) + ".json";
            if (!extractFileToPath(file.inode, local, file.partitionNum))
                throw std::runtime_error("宝塔请求日志提取失败");
            std::ifstream input(local, std::ios::binary);
            std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> digest(EVP_MD_CTX_new(), EVP_MD_CTX_free);
            if (!input || !digest || EVP_DigestInit_ex(digest.get(), EVP_sha256(), nullptr) != 1)
                throw std::runtime_error("宝塔日志哈希初始化失败");
            std::vector<char> chunk(1024 * 1024);
            int64_t bytesRead = 0;
            while (input) {
                input.read(chunk.data(), chunk.size()); bytesRead += input.gcount();
                if (input.gcount() && EVP_DigestUpdate(digest.get(), chunk.data(), input.gcount()) != 1)
                    throw std::runtime_error("宝塔日志哈希计算失败");
            }
            if (input.bad() || bytesRead != file.size) throw std::runtime_error("宝塔日志哈希读取不完整");
            unsigned char bytes[EVP_MAX_MD_SIZE]; unsigned int length = 0;
            if (EVP_DigestFinal_ex(digest.get(), bytes, &length) != 1 || length != 32)
                throw std::runtime_error("宝塔日志哈希计算失败");
            std::ostringstream hash; hash << std::hex << std::setfill('0');
            for (unsigned int i=0; i<length; ++i) hash << std::setw(2) << static_cast<int>(bytes[i]);
            const std::string sha = hash.str();
            int64_t parsedCount = 0, rejected = 0;
            const auto duplicate = sameContent.find(sha);
            std::string canonical = duplicate == sameContent.end() ? file.path : duplicate->second.first;
            if (sqlite3_exec(db, "BEGIN TRANSACTION", nullptr, nullptr, nullptr) != SQLITE_OK)
                throw std::runtime_error("宝塔日志写入事务失败");
            try {
                if (duplicate == sameContent.end()) {
                    input.clear(); input.seekg(0);
                    sqlite3_stmt* raw = nullptr;
                    const char* sql = "INSERT INTO linux_panel_requests(timestamp_raw,client_address,method,url,user_agent,form_data,"
                        "duration_ms,status_code,response_size,source_file,source_line,source_offset,source_inode,source_partition,"
                        "source_sha256,raw_record,parser_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)";
                    if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) != SQLITE_OK) throw std::runtime_error("宝塔记录写入准备失败");
                    std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> statement(raw, sqlite3_finalize);
                    std::vector<char> buffer(1024 * 1024 + 1);
                    int64_t lineNumber = 0;
                    while (input) {
                        const auto offset = input.tellg();
                        input.getline(buffer.data(), buffer.size());
                        if (input.bad()) throw std::runtime_error("宝塔请求日志读取失败");
                        if (input.fail() && !input.eof()) {
                            ++lineNumber; ++rejected; input.clear();
                            input.ignore(std::numeric_limits<std::streamsize>::max(), '\n'); continue;
                        }
                        if (input.gcount() == 0) break;
                        ++lineNumber;
                        std::string line(buffer.data(), static_cast<size_t>(input.gcount()) - (input.eof() ? 0 : 1));
                        if (line.empty()) continue;
                        nlohmann::json record;
                        try {
                            record = nlohmann::json::parse(line, [](int depth, nlohmann::json::parse_event_t, nlohmann::json&) {
                                if (depth > 32) throw std::runtime_error("JSON 嵌套层级超限");
                                return true;
                            }, false);
                        } catch (...) { ++rejected; continue; }
                        if (!record.is_array() || record.size() < 9 || record.size() > 32 ||
                            !record[0].is_string() || !record[1].is_string() || !record[2].is_string() || !record[3].is_string()) {
                            ++rejected; continue;
                        }
                        auto text = [&](int index, const std::string& value) {
                            sqlite3_bind_text(raw, index, value.data(), static_cast<int>(value.size()), SQLITE_TRANSIENT);
                        };
                        for (int column=0; column<6; ++column) {
                            if (record[column].is_null()) sqlite3_bind_null(raw, column+1);
                            else text(column+1, record[column].is_string() ? record[column].get<std::string>() : record[column].dump());
                        }
                        for (int column=6; column<9; ++column) {
                            const bool inRange = !record[column].is_number_unsigned() ||
                                record[column].get<uint64_t>() <= static_cast<uint64_t>(std::numeric_limits<int64_t>::max());
                            if (record[column].is_number_integer() && inRange) sqlite3_bind_int64(raw, column+1, record[column].get<int64_t>());
                            else sqlite3_bind_null(raw, column+1);
                        }
                        text(10, file.path); sqlite3_bind_int64(raw,11,lineNumber);
                        sqlite3_bind_int64(raw,12,static_cast<int64_t>(offset)); sqlite3_bind_int64(raw,13,file.inode);
                        sqlite3_bind_int(raw,14,file.partitionNum); text(15,sha); text(16,line); text(17,"baota-request-array:v1");
                        if (sqlite3_step(raw) != SQLITE_DONE) throw std::runtime_error("宝塔请求记录写入失败");
                        sqlite3_reset(raw);sqlite3_clear_bindings(raw);++parsedCount;
                    }
                    sameContent[sha] = {file.path, parsedCount};
                    panelRecords += parsedCount;
                } else parsedCount = duplicate->second.second;
                sqlite3_stmt* raw = nullptr;
                if (sqlite3_prepare_v2(db, "INSERT OR REPLACE INTO linux_panel_request_sources VALUES(?,?,?,?,?,?,?)", -1, &raw, nullptr) != SQLITE_OK)
                    throw std::runtime_error("宝塔来源映射写入准备失败");
                std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)> statement(raw, sqlite3_finalize);
                sqlite3_bind_text(raw,1,file.path.c_str(),-1,SQLITE_TRANSIENT);sqlite3_bind_int(raw,2,file.partitionNum);
                sqlite3_bind_int64(raw,3,file.inode);sqlite3_bind_text(raw,4,sha.c_str(),-1,SQLITE_TRANSIENT);
                sqlite3_bind_text(raw,5,canonical.c_str(),-1,SQLITE_TRANSIENT);sqlite3_bind_int64(raw,6,parsedCount);sqlite3_bind_int64(raw,7,rejected);
                if (sqlite3_step(raw) != SQLITE_DONE) throw std::runtime_error("宝塔来源映射写入失败");
                if (sqlite3_exec(db,"COMMIT",nullptr,nullptr,nullptr) != SQLITE_OK) throw std::runtime_error("宝塔日志事务提交失败");
            } catch (...) { sqlite3_exec(db,"ROLLBACK",nullptr,nullptr,nullptr);throw; }
        }
    }
    std::cout << "已解析宝塔面板请求：" << panelRecords << " 条（原始本地时间，未推定时区）" << std::endl;
}

// ============================================================================
// Enhanced Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::correlateEvents() {
    std::cout << "Correlating events across log sources..." << std::endl;

    LinuxAnalysis::LogCorrelationEngine correlator(outputDbPath_);
    auto correlatedEvents = correlator.correlateEvents();

    if (!correlatedEvents.empty()) {
        linuxDb_->insertCorrelatedEvents(correlatedEvents);
        std::cout << "  Generated " << correlatedEvents.size() << " correlated events" << std::endl;
        AuditLog::instance().log("SUCCESS", "EVENT_CORRELATION_COMPLETE",
            "Correlated " + std::to_string(correlatedEvents.size()) + " events");
    } else {
        std::cout << "  No correlated events found" << std::endl;
    }
}

void LinuxFilesAnalyzer::reconstructTimeline() {
    std::cout << "Reconstructing unified timeline..." << std::endl;

    LinuxAnalysis::TimelineReconstructor reconstructor(outputDbPath_);
    LinuxAnalysis::Timeline timeline = reconstructor.buildTimeline();

    if (!timeline.events.empty()) {
        linuxDb_->insertTimelineEvents(timeline.events);
        std::cout << "  Timeline has " << timeline.events.size() << " events" << std::endl;
    }

    if (!timeline.gaps.empty()) {
        linuxDb_->insertTimelineGaps(timeline.gaps);
        std::cout << "  Found " << timeline.gaps.size() << " timeline gaps" << std::endl;

        if (timeline.hasUnexplainedGaps()) {
            std::cout << "  WARNING: Timeline has suspicious gaps that may indicate log tampering" << std::endl;
            AuditLog::instance().log("WARNING", "TIMELINE_GAPS_DETECTED",
                "Found " + std::to_string(timeline.gaps.size()) + " unexplained timeline gaps");
        }
    } else {
        std::cout << "  No timeline gaps detected" << std::endl;
    }
}

void LinuxFilesAnalyzer::detectAnomalies() {
    std::cout << "Detecting security anomalies..." << std::endl;

    LinuxAnalysis::AnomalyDetector detector(outputDbPath_);
    auto anomalies = detector.detectAnomalies();

    if (!anomalies.empty()) {
        linuxDb_->insertAnomalies(anomalies);

        // Count by severity
        int critical = 0, high = 0, medium = 0, low = 0;
        for (const auto& anomaly : anomalies) {
            if (anomaly.severity >= 4) critical++;
            else if (anomaly.severity == 3) high++;
            else if (anomaly.severity == 2) medium++;
            else low++;
        }

        std::cout << "  Detected " << anomalies.size() << " anomalies: "
                  << critical << " critical, " << high << " high, "
                  << medium << " medium, " << low << " low" << std::endl;

        AuditLog::instance().log("SUCCESS", "ANOMALY_DETECTION_COMPLETE",
            "Detected " + std::to_string(anomalies.size()) + " anomalies (" +
            std::to_string(critical) + " critical, " + std::to_string(high) + " high)");
    } else {
        std::cout << "  No anomalies detected" << std::endl;
    }
}

// ============================================================================
// Phase 16: Rule engine and attack chain analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeWithRuleEngine() {
    std::cout << "Running rule engine and attack chain analysis..." << std::endl;

    try {
        RuleEngine engine(outputDbPath_);

        // Evaluate all rules
        auto matches = engine.evaluateAllRules();
        std::cout << "  Rule engine found " << matches.size() << " matches" << std::endl;

        // Build attack chains
        auto chains = engine.buildAttackChains(matches);
        std::cout << "  Built " << chains.size() << " attack chains" << std::endl;

        // Store results
        if (!matches.empty()) {
            engine.storeRuleMatches(matches);
        }
        if (!chains.empty()) {
            engine.storeAttackChains(chains);
            for (const auto& chain : chains) {
                std::cout << "  ATTACK CHAIN: " << chain.summary << std::endl;
                std::cout << "    Severity: " << chain.overallSeverity << std::endl;
            }
        }

        AuditLog::instance().log("SUCCESS", "RULE_ENGINE_COMPLETE",
            "Rule engine found " + std::to_string(matches.size()) + " matches, " +
            std::to_string(chains.size()) + " attack chains");
    } catch (const std::exception& e) {
        std::cerr << "  Rule engine error: " << e.what() << std::endl;
        AuditLog::instance().log("ERROR", "RULE_ENGINE_FAILED", e.what());
    }
}
