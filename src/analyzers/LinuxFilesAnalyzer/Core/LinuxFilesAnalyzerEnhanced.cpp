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
    std::cout << "Analyzing Nginx web servers..." << std::endl;

    // Look for Nginx logs in common locations
    std::vector<std::string> logPatterns = {
        "var/log/nginx/access.log%",
        "var/log/nginx/error.log%",
        "var/log/nginx/%.log"
    };

    std::string extractPath = getExtractPath("nginx");
    fs::create_directories(extractPath);

    int totalLogs = 0;
    for (const auto& pattern : logPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".log";
            if (extractFileToPath(file.inode, outputPath, file.partitionNum)) {
                auto parseResult = NginxParser::parseAccessLog(outputPath);
                if (!parseResult.accessLogs.empty()) {
                    linuxDb_->insertNginxAccessLogs(parseResult.accessLogs);
                    totalLogs += parseResult.accessLogs.size();
                }
            }
        }
    }

    if (totalLogs > 0) {
        std::cout << "  Parsed " << totalLogs << " Nginx log entries" << std::endl;
    } else {
        std::cout << "  No Nginx logs found (skipping)" << std::endl;
    }
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
