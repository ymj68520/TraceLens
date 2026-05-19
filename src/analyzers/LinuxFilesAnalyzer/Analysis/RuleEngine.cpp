// RuleEngine.cpp
// Rule engine for attack chain analysis with MITRE ATT&CK mapping

#include "RuleEngine.h"
#include <sqlite3.h>
#include <sstream>
#include <regex>
#include <algorithm>
#include <set>

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// ============================================================================
// ATT&CK Stage Ordering
// ============================================================================

const std::vector<std::string> RuleEngine::ATTCK_STAGES = {
    "Initial Access",
    "Execution",
    "Persistence",
    "Privilege Escalation",
    "Defense Evasion",
    "Credential Access",
    "Discovery",
    "Lateral Movement",
    "Collection",
    "Exfiltration",
    "Command and Control"
};

const std::map<std::string, std::string> RuleEngine::TECHNIQUE_TO_TACTIC = {
    {"T1078", "Initial Access"},
    {"T1059", "Execution"},
    {"T1053", "Persistence"},
    {"T1543", "Persistence"},
    {"T1547", "Persistence"},
    {"T1055", "Privilege Escalation"},
    {"T1068", "Privilege Escalation"},
    {"T1070", "Defense Evasion"},
    {"T1036", "Defense Evasion"},
    {"T1562", "Defense Evasion"},
    {"T1003", "Credential Access"},
    {"T1110", "Credential Access"},
    {"T1087", "Discovery"},
    {"T1082", "Discovery"},
    {"T1046", "Discovery"},
    {"T1021", "Lateral Movement"},
    {"T1570", "Lateral Movement"},
    {"T1005", "Collection"},
    {"T1041", "Exfiltration"},
    {"T1071", "Command and Control"},
    {"T1572", "Command and Control"}
};

// ============================================================================
// Constructor
// ============================================================================

RuleEngine::RuleEngine(const std::string& dbPath) : dbPath_(dbPath) {}

// ============================================================================
// Main evaluation
// ============================================================================

std::vector<RuleMatch> RuleEngine::evaluateAllRules() {
    std::vector<RuleMatch> allMatches;

    auto sigmaMatches = evaluateSigmaRules();
    allMatches.insert(allMatches.end(), sigmaMatches.begin(), sigmaMatches.end());

    auto iocMatches = matchIOCs();
    allMatches.insert(allMatches.end(), iocMatches.begin(), iocMatches.end());

    auto attckMatches = mapAnomaliesToATTCK();
    allMatches.insert(allMatches.end(), attckMatches.begin(), attckMatches.end());

    return allMatches;
}

// ============================================================================
// Sigma-like rule evaluation
// ============================================================================

std::vector<RuleMatch> RuleEngine::evaluateSigmaRules() {
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath_.c_str(), &db) != SQLITE_OK) {
        return {};
    }

    auto matches = evaluateBuiltInSigmaRules(db);
    sqlite3_close(db);
    return matches;
}

std::vector<RuleMatch> RuleEngine::evaluateBuiltInSigmaRules(sqlite3* db) {
    std::vector<RuleMatch> matches;

    // Rule: Multiple failed SSH logins followed by success (brute force then compromise)
    {
        const char* sql =
            "SELECT COUNT(*) FROM linux_login_records "
            "WHERE login_type='ssh' AND is_success=0 "
            "AND username IN ("
            "  SELECT username FROM linux_login_records "
            "  WHERE login_type='ssh' AND is_success=1"
            ")";

        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            if (sqlite3_step(stmt) == SQLITE_ROW) {
                int count = sqlite3_column_int(stmt, 0);
                if (count > 5) {
                    RuleMatch match;
                    match.ruleId = "SIGMA-SSH-BRUTEFORCE";
                    match.ruleType = "sigma";
                    match.ruleName = "SSH Brute Force Followed by Success";
                    match.description = "Detected " + std::to_string(count) +
                        " failed SSH attempts with subsequent successful login";
                    match.attckTechnique = "T1110";
                    match.attackStage = "Credential Access";
                    match.severity = 4;
                    match.confidence = 0.8f;
                    matches.push_back(std::move(match));
                }
            }
            sqlite3_finalize(stmt);
        }
    }

    // Rule: Suspicious cron jobs (reverse shells, downloads)
    {
        const char* sql =
            "SELECT id, command FROM linux_cron_jobs "
            "WHERE command LIKE '%/dev/tcp/%' "
            "OR command LIKE '%nc -e%' "
            "OR command LIKE '%bash -i%' "
            "OR command LIKE '%wget %|sh%' "
            "OR command LIKE '%curl %|sh%'";

        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                RuleMatch match;
                match.ruleId = "SIGMA-CRON-REVERSESHELL";
                match.ruleType = "sigma";
                match.ruleName = "Suspicious Cron Job - Reverse Shell";
                match.attckTechnique = "T1053";
                match.attackStage = "Persistence";
                match.severity = 5;
                match.confidence = 0.9f;
                match.matchedEventIds.push_back(sqlite3_column_int64(stmt, 0));
                match.description = "Suspicious cron job: " +
                    std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)));
                matches.push_back(std::move(match));
            }
            sqlite3_finalize(stmt);
        }
    }

    // Rule: UID 0 users other than root
    {
        const char* sql =
            "SELECT id, username FROM linux_users WHERE uid=0 AND username!='root'";

        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                RuleMatch match;
                match.ruleId = "SIGMA-UID0-NONROOT";
                match.ruleType = "sigma";
                match.ruleName = "Non-root User with UID 0";
                match.attckTechnique = "T1078";
                match.attackStage = "Privilege Escalation";
                match.severity = 5;
                match.confidence = 0.95f;
                match.matchedEventIds.push_back(sqlite3_column_int64(stmt, 0));
                match.description = "Non-root user '" +
                    std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1))) +
                    "' has UID 0";
                matches.push_back(std::move(match));
            }
            sqlite3_finalize(stmt);
        }
    }

    // Rule: Suspicious setuid files in /tmp or /var/tmp
    {
        const char* sql =
            "SELECT id, file_path FROM linux_setuid_files "
            "WHERE file_path LIKE '/tmp/%' OR file_path LIKE '/var/tmp/%'";

        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                RuleMatch match;
                match.ruleId = "SIGMA-SETUID-TMP";
                match.ruleType = "sigma";
                match.ruleName = "Setuid Binary in Temporary Directory";
                match.attckTechnique = "T1548";
                match.attackStage = "Privilege Escalation";
                match.severity = 5;
                match.confidence = 0.9f;
                match.matchedEventIds.push_back(sqlite3_column_int64(stmt, 0));
                match.description = "Setuid file in temp directory: " +
                    std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)));
                matches.push_back(std::move(match));
            }
            sqlite3_finalize(stmt);
        }
    }

    // Rule: Suspicious persistence entries
    {
        const char* sql =
            "SELECT id, persistence_type, file_path, command FROM linux_persistence_entries "
            "WHERE is_suspicious=1";

        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                RuleMatch match;
                match.ruleId = "SIGMA-PERSISTENCE-SUSPICIOUS";
                match.ruleType = "sigma";
                match.ruleName = "Suspicious Persistence Mechanism";
                match.attckTechnique = "T1547";
                match.attackStage = "Persistence";
                match.severity = sqlite3_column_int(stmt, 0) > 0 ? 4 : 3;
                match.confidence = 0.7f;
                match.matchedEventIds.push_back(sqlite3_column_int64(stmt, 0));
                match.description = "Suspicious persistence: " +
                    std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1))) +
                    " in " + std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2)));
                matches.push_back(std::move(match));
            }
            sqlite3_finalize(stmt);
        }
    }

    return matches;
}

// ============================================================================
// IOC Matching
// ============================================================================

std::vector<RuleMatch> RuleEngine::matchIOCs() {
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath_.c_str(), &db) != SQLITE_OK) {
        return {};
    }

    auto matches = evaluateIOCMatches(db);
    sqlite3_close(db);
    return matches;
}

std::vector<RuleMatch> RuleEngine::evaluateIOCMatches(sqlite3* db) {
    std::vector<RuleMatch> matches;

    // Known malicious IP patterns (simplified - real implementation would use threat intel feeds)
    // Check network connections for known bad patterns
    {
        const char* sql =
            "SELECT id, remote_address, remote_port, process FROM linux_network_connections "
            "WHERE remote_port IN (4444, 5555, 6666, 7777, 8888, 9999, 1234, 31337)";

        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                RuleMatch match;
                match.ruleId = "IOC-SUSPICIOUS-PORT";
                match.ruleType = "ioc";
                match.ruleName = "Connection to Suspicious Port";
                match.attckTechnique = "T1071";
                match.attackStage = "Command and Control";
                match.severity = 3;
                match.confidence = 0.5f;
                match.matchedEventIds.push_back(sqlite3_column_int64(stmt, 0));
                match.description = "Connection to suspicious port " +
                    std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2))) +
                    " from process " +
                    std::string(reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3)));
                matches.push_back(std::move(match));
            }
            sqlite3_finalize(stmt);
        }
    }

    return matches;
}

// ============================================================================
// ATT&CK Mapping
// ============================================================================

std::vector<RuleMatch> RuleEngine::mapAnomaliesToATTCK() {
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath_.c_str(), &db) != SQLITE_OK) {
        return {};
    }

    std::vector<RuleMatch> matches;

    // Map anomalies from the anomalies table
    const char* sql =
        "SELECT id, anomaly_type, description, severity FROM linux_anomalies "
        "WHERE llm_analyzed_at IS NOT NULL";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            std::string anomalyType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            std::string description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));

            std::string technique = mapToATTCKTechnique(anomalyType, description);
            if (!technique.empty()) {
                RuleMatch match;
                match.ruleId = "ATTCK-" + technique;
                match.ruleType = "custom";
                match.ruleName = "ATT&CK Technique: " + technique;
                match.attckTechnique = technique;
                match.attackStage = mapToATTCKTactic(technique);
                match.severity = sqlite3_column_int(stmt, 3);
                match.confidence = 0.6f;
                match.matchedEventIds.push_back(sqlite3_column_int64(stmt, 0));
                match.description = description;
                matches.push_back(std::move(match));
            }
        }
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
    return matches;
}

std::string RuleEngine::mapToATTCKTechnique(const std::string& anomalyType,
                                              const std::string& description) {
    // Map anomaly types to ATT&CK techniques
    if (anomalyType.find("BRUTE_FORCE") != std::string::npos) return "T1110";
    if (anomalyType.find("PRIVILEGE") != std::string::npos) return "T1068";
    if (anomalyType.find("PERSISTENCE") != std::string::npos) return "T1547";
    if (anomalyType.find("LATERAL") != std::string::npos) return "T1021";
    if (anomalyType.find("EXFILTRATION") != std::string::npos) return "T1041";
    if (anomalyType.find("CREDENTIAL") != std::string::npos) return "T1003";
    if (anomalyType.find("DISCOVERY") != std::string::npos) return "T1082";
    if (anomalyType.find("DEFENSE_EVASION") != std::string::npos) return "T1070";

    // Check description for hints
    if (description.find("ssh") != std::string::npos) return "T1021";
    if (description.find("cron") != std::string::npos) return "T1053";
    if (description.find("sudo") != std::string::npos) return "T1548";

    return "";
}

std::string RuleEngine::mapToATTCKTactic(const std::string& techniqueId) {
    auto it = TECHNIQUE_TO_TACTIC.find(techniqueId);
    if (it != TECHNIQUE_TO_TACTIC.end()) {
        return it->second;
    }
    return "Unknown";
}

// ============================================================================
// Attack Chain Construction
// ============================================================================

std::vector<AttackChain> RuleEngine::buildAttackChains(
    const std::vector<RuleMatch>& matches) {

    std::vector<AttackChain> chains;
    if (matches.empty()) return chains;

    // Group matches by attack stage
    std::map<std::string, std::vector<const RuleMatch*>> stageGroups;
    for (const auto& match : matches) {
        stageGroups[match.attackStage].push_back(&match);
    }

    // Build chains from stage groups
    AttackChain chain;
    chain.chainId = "CHAIN-001";
    chain.overallSeverity = 0;

    for (const auto& stage : ATTCK_STAGES) {
        auto it = stageGroups.find(stage);
        if (it != stageGroups.end()) {
            chain.stages.push_back(stage);
            for (const auto* match : it->second) {
                chain.matches.push_back(*match);
                chain.overallSeverity = std::max(chain.overallSeverity, match->severity);
            }
        }
    }

    if (!chain.matches.empty()) {
        // Build summary
        std::ostringstream summary;
        summary << "Attack chain detected with " << chain.stages.size() << " stages: ";
        for (size_t i = 0; i < chain.stages.size(); ++i) {
            if (i > 0) summary << " -> ";
            summary << chain.stages[i];
        }
        chain.summary = summary.str();

        // Build description
        std::ostringstream desc;
        desc << "Detected " << chain.matches.size() << " rule matches across "
             << chain.stages.size() << " ATT&CK stages.\n";
        for (const auto& m : chain.matches) {
            desc << "- [" << m.ruleId << "] " << m.description << "\n";
        }
        chain.description = desc.str();

        chains.push_back(std::move(chain));
    }

    return chains;
}

// ============================================================================
// Database Storage
// ============================================================================

bool RuleEngine::storeRuleMatches(const std::vector<RuleMatch>& matches) {
    // Rule matches are stored via the existing anomaly/correlated events tables
    // The RuleMatch struct maps to the existing data model
    return true;
}

bool RuleEngine::storeAttackChains(const std::vector<AttackChain>& chains) {
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath_.c_str(), &db) != SQLITE_OK) {
        return false;
    }

    const char* sql =
        "INSERT INTO linux_attack_chains "
        "(chain_id, attack_type, events, timeline, summary, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?)";

    for (const auto& chain : chains) {
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            sqlite3_bind_text(stmt, 1, chain.chainId.c_str(), -1, SQLITE_TRANSIENT);

            // Combine stages into attack_type
            std::string stagesStr;
            for (size_t i = 0; i < chain.stages.size(); ++i) {
                if (i > 0) stagesStr += " -> ";
                stagesStr += chain.stages[i];
            }
            sqlite3_bind_text(stmt, 2, stagesStr.c_str(), -1, SQLITE_TRANSIENT);

            // Combine matched event IDs
            std::ostringstream eventsStr;
            for (size_t i = 0; i < chain.matches.size(); ++i) {
                if (i > 0) eventsStr << ",";
                for (auto id : chain.matches[i].matchedEventIds) {
                    eventsStr << id << ";";
                }
            }
            sqlite3_bind_text(stmt, 3, eventsStr.str().c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(stmt, 4, chain.summary.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(stmt, 5, chain.description.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(stmt, 6, chain.overallSeverity);

            sqlite3_step(stmt);
            sqlite3_finalize(stmt);
        }
    }

    sqlite3_close(db);
    return true;
}

} // namespace linux
} // namespace forensics
