// RuleEngine.h
// Rule engine for attack chain analysis with MITRE ATT&CK mapping

#pragma once
#ifndef RULE_ENGINE_H
#define RULE_ENGINE_H

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include "LinuxDataTypes.h"

// Forward declare sqlite3 to avoid header dependency
struct sqlite3;

namespace forensics {
namespace linux {

struct RuleMatch {
    std::string ruleId;
    std::string ruleType;       // sigma, yara, ioc, custom
    std::string ruleName;
    std::string description;
    std::vector<int64_t> matchedEventIds;
    std::string attckTechnique; // MITRE ATT&CK technique ID (e.g., T1059.004)
    std::string attackStage;    // MITRE ATT&CK tactic
    int severity = 0;           // 1-5
    float confidence = 0.0f;
    EvidenceProvenance provenance;
};

struct AttackChain {
    std::string chainId;
    std::vector<std::string> stages;    // ATT&CK tactics in order
    std::vector<RuleMatch> matches;
    int overallSeverity = 0;
    std::string summary;
    std::string description;
    EvidenceProvenance provenance;
};

class RuleEngine {
public:
    explicit RuleEngine(const std::string& dbPath);

    // Evaluate all rules against the database
    std::vector<RuleMatch> evaluateAllRules();

    // Evaluate Sigma-like rules (pattern matching on log events)
    std::vector<RuleMatch> evaluateSigmaRules();

    // Evaluate IOC (Indicator of Compromise) matches
    std::vector<RuleMatch> matchIOCs();

    // Map anomalies to ATT&CK techniques
    std::vector<RuleMatch> mapAnomaliesToATTCK();

    // Build attack chains from matches
    std::vector<AttackChain> buildAttackChains(const std::vector<RuleMatch>& matches);

    // Store results to database
    bool storeRuleMatches(const std::vector<RuleMatch>& matches);
    bool storeAttackChains(const std::vector<AttackChain>& chains);

private:
    std::string dbPath_;

    // Built-in rule definitions
    static std::vector<RuleMatch> evaluateBuiltInSigmaRules(
        sqlite3* db);

    // IOC database
    static std::vector<RuleMatch> evaluateIOCMatches(
        sqlite3* db);

    // ATT&CK technique mapping
    static std::string mapToATTCKTechnique(const std::string& anomalyType,
                                            const std::string& description);
    static std::string mapToATTCKTactic(const std::string& techniqueId);

    // Attack chain reconstruction
    static std::vector<std::string> reconstructChainStages(
        const std::vector<RuleMatch>& matches);

    // ATT&CK stage ordering
    static const std::vector<std::string> ATTCK_STAGES;
    static const std::map<std::string, std::string> TECHNIQUE_TO_TACTIC;
};

} // namespace linux
} // namespace forensics

#endif // RULE_ENGINE_H
