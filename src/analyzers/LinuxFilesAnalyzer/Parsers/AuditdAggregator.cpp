// AuditdAggregator.cpp
// Implementation of auditd multi-line event aggregation

#ifdef linux
#undef linux
#endif

#include "AuditdAggregator.h"
#include "TimestampNormalizer.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <iomanip>

namespace forensics {
namespace linux {

// ============================================================================
// Single line parsing
// ============================================================================

AuditdAggregator::ParsedLine AuditdAggregator::parseLine(const std::string& line) {
    ParsedLine result;
    if (line.empty()) return result;

    result.rawLine = line;

    // Format: type=TYPE msg=audit(EPOCH.MSEC:SERIAL): key=value ...
    std::regex auditPattern(R"(type=(\w+)\s+msg=audit\((\d+)\.(\d+):(\d+)\):(.*)");
    std::smatch match;

    if (!std::regex_search(line, match, auditPattern)) {
        return result;
    }

    result.type = match[1].str();
    try {
        result.timestamp = std::stoll(match[2].str());
    } catch (...) {
        result.timestamp = 0;
    }
    try {
        result.serialNumber = std::stoi(match[4].str());
    } catch (...) {
        result.serialNumber = 0;
    }
    result.body = match[5].str();

    return result;
}

// ============================================================================
// Key=value extraction
// ============================================================================

std::map<std::string, std::string> AuditdAggregator::extractKeyValues(const std::string& body) {
    std::map<std::string, std::string> kvs;

    // Match key=value patterns
    // Values can be: quoted strings or bare words
    std::regex kvPattern("(\\w+)=(?:\"([^\"]*)\"|(\\S+))");
    auto begin = std::sregex_iterator(body.begin(), body.end(), kvPattern);
    auto end = std::sregex_iterator();

    for (auto it = begin; it != end; ++it) {
        std::string key = (*it)[1].str();
        std::string value = (*it)[2].matched ? (*it)[2].str() : (*it)[3].str();
        kvs[key] = value;
    }

    return kvs;
}

// ============================================================================
// Hex decode
// ============================================================================

std::string AuditdAggregator::hexDecode(const std::string& hex) {
    std::string result;
    for (size_t i = 0; i + 1 < hex.length(); i += 2) {
        int byte;
        std::istringstream(hex.substr(i, 2)) >> std::hex >> byte;
        result += static_cast<char>(byte);
    }
    return result;
}

// ============================================================================
// Type-specific parsers
// ============================================================================

void AuditdAggregator::parseSyscall(AggregatedAuditEvent& event, const std::string& body) {
    auto kvs = extractKeyValues(body);

    auto getInt = [&](const std::string& key, int def = -1) -> int {
        auto it = kvs.find(key);
        if (it != kvs.end()) {
            try { return std::stoi(it->second); } catch (...) {}
        }
        return def;
    };

    event.syscall = getInt("syscall");
    event.pid = getInt("pid");
    event.ppid = getInt("ppid");
    event.uid = getInt("uid");
    event.gid = getInt("gid");
    event.euid = getInt("euid");
    event.egid = getInt("egid");
    event.auid = getInt("auid", -1);
    event.ses = getInt("ses");
    event.exitCode = getInt("exit");

    auto it = kvs.find("success");
    if (it != kvs.end()) {
        event.success = (it->second == "yes") ? 1 : 0;
    }

    it = kvs.find("exe");
    if (it != kvs.end()) event.exe = it->second;

    it = kvs.find("comm");
    if (it != kvs.end()) event.comm = it->second;

    it = kvs.find("tty");
    if (it != kvs.end()) event.terminal = it->second;

    it = kvs.find("key");
    if (it != kvs.end()) event.key = it->second;
}

void AuditdAggregator::parseExecve(AggregatedAuditEvent& event, const std::string& body) {
    // EXECVE format: argc=3 a0="ls" a1="-la" a2="/tmp"
    // Also handles hex-encoded: a0=hex-encoded-value
    auto kvs = extractKeyValues(body);

    auto it = kvs.find("argc");
    if (it != kvs.end()) {
        try { event.argc = std::stoi(it->second); } catch (...) {}
    }

    // Collect argv in order
    for (int i = 0; i < event.argc || i < 32; i++) {
        std::string key = "a" + std::to_string(i);
        auto argIt = kvs.find(key);
        if (argIt != kvs.end()) {
            event.argv.push_back(argIt->second);
        } else {
            break;
        }
    }
}

void AuditdAggregator::parseCwd(AggregatedAuditEvent& event, const std::string& body) {
    auto kvs = extractKeyValues(body);
    auto it = kvs.find("cwd");
    if (it != kvs.end()) {
        event.cwd = it->second;
    }
}

void AuditdAggregator::parsePath(AggregatedAuditEvent& event, const std::string& body) {
    auto kvs = extractKeyValues(body);

    AggregatedAuditEvent::PathEntry path;
    auto it = kvs.find("name");
    if (it != kvs.end()) path.name = it->second;

    it = kvs.find("inode");
    if (it != kvs.end()) path.inode = it->second;

    it = kvs.find("mode");
    if (it != kvs.end()) path.mode = it->second;

    it = kvs.find("ouid");
    if (it != kvs.end()) path.ouid = it->second;

    it = kvs.find("ogid");
    if (it != kvs.end()) path.ogid = it->second;

    it = kvs.find("nametype");
    if (it != kvs.end()) {
        if (it->second == "PARENT") path.nametype = 1;
        else if (it->second == "CREATE") path.nametype = 2;
        else if (it->second == "DELETE") path.nametype = 3;
        else if (it->second == "NORMAL") path.nametype = 0;
    }

    if (!path.name.empty()) {
        event.paths.push_back(path);
    }
}

void AuditdAggregator::parseProctitle(AggregatedAuditEvent& event, const std::string& body) {
    // PROCTITLE: proctitle=hex-encoded-value
    std::regex proctitleRe(R"(proctitle=([0-9A-Fa-f]+))");
    std::smatch match;
    if (std::regex_search(body, match, proctitleRe)) {
        event.proctitle = hexDecode(match[1].str());
        // Replace null bytes with spaces for readability
        std::replace(event.proctitle.begin(), event.proctitle.end(), '\0', ' ');
    }
}

void AuditdAggregator::parseUserAuth(AggregatedAuditEvent& event, const std::string& body) {
    auto kvs = extractKeyValues(body);

    auto it = kvs.find("op");
    if (it != kvs.end()) event.authOp = it->second;

    it = kvs.find("acct");
    if (it != kvs.end()) event.authUser = it->second;

    it = kvs.find("addr");
    if (it != kvs.end()) event.authAddr = it->second;

    it = kvs.find("res");
    if (it != kvs.end()) event.result = it->second;
}

void AuditdAggregator::parseAvc(AggregatedAuditEvent& event, const std::string& body) {
    // AVC format: avc: denied { read } for pid=1234 comm="cat" name="file" ...
    std::regex avcRe(R"(avc:\s+(\w+)\s+\{ (\w+) \})");
    std::smatch match;
    if (std::regex_search(body, match, avcRe)) {
        event.avcAction = match[1].str();   // denied, granted
        event.avcPermission = match[2].str(); // read, write, execute, etc.
    }

    auto kvs = extractKeyValues(body);
    auto it = kvs.find("scontext");
    if (it != kvs.end()) event.subject = it->second;

    it = kvs.find("tcontext");
    if (it != kvs.end()) event.object = it->second;

    it = kvs.find("tclass");
    if (it != kvs.end()) event.avcClass = it->second;
}

// ============================================================================
// Event merging
// ============================================================================

AggregatedAuditEvent AuditdAggregator::mergeEvent(const std::vector<ParsedLine>& lines) {
    AggregatedAuditEvent event;

    if (lines.empty()) return event;

    // Use timestamp and serial from first line
    event.timestamp = lines[0].timestamp;
    event.serialNumber = lines[0].serialNumber;
    event.eventId = std::to_string(event.timestamp) + ":" + std::to_string(event.serialNumber);

    // Set provenance
    event.provenance.parserName = "AuditdAggregator";
    event.provenance.parserVersion = "1.0.0";

    // Normalize timestamp
    event.normalizedTime = TimestampNormalizer::normalizeAuditd(
        std::to_string(event.timestamp) + ".000:" + std::to_string(event.serialNumber));

    for (const auto& line : lines) {
        event.rawLines.push_back(line.rawLine);

        if (line.type == "SYSCALL") {
            parseSyscall(event, line.body);
        } else if (line.type == "EXECVE") {
            parseExecve(event, line.body);
        } else if (line.type == "CWD") {
            parseCwd(event, line.body);
        } else if (line.type == "PATH") {
            parsePath(event, line.body);
        } else if (line.type == "PROCTITLE") {
            parseProctitle(event, line.body);
        } else if (line.type == "USER_AUTH" || line.type == "USER_ACCT" ||
                   line.type == "USER_CMD" || line.type == "USER_MGMT") {
            parseUserAuth(event, line.body);
        } else if (line.type == "AVC") {
            parseAvc(event, line.body);
        } else if (line.type == "EOE") {
            // End of event marker - nothing to parse
        }
    }

    // Classify and assess severity
    event.eventType = classifyEvent(event);
    event.severity = assessSeverity(event);

    return event;
}

// ============================================================================
// Event classification
// ============================================================================

std::string AuditdAggregator::classifyEvent(const AggregatedAuditEvent& event) {
    // Check for authentication events
    if (!event.authOp.empty()) {
        return "authentication";
    }

    // Check for AVC (SELinux) events
    if (!event.avcAction.empty()) {
        return "selinux";
    }

    // Check for process execution
    if (!event.argv.empty() || !event.proctitle.empty()) {
        return "process_execution";
    }

    // Check for file access (has PATH entries)
    if (!event.paths.empty()) {
        return "file_access";
    }

    // Check for privilege escalation patterns
    if (event.auid >= 0 && event.auid != event.uid) {
        return "privilege_change";
    }

    // Default based on type
    return "audit_event";
}

// ============================================================================
// Severity assessment
// ============================================================================

int AuditdAggregator::assessSeverity(const AggregatedAuditEvent& event) {
    int severity = 0;

    // Failed authentication
    if (!event.authOp.empty() && event.result == "fail") {
        severity = std::max(severity, 2);
    }

    // SELinux denials
    if (event.avcAction == "denied") {
        severity = std::max(severity, 2);
    }

    // Privilege escalation (UID change)
    if (event.auid >= 0 && event.auid != event.uid && event.uid == 0) {
        severity = std::max(severity, 3);
    }

    // Root shell execution
    if (event.uid == 0 && !event.exe.empty()) {
        if (event.exe.find("bash") != std::string::npos ||
            event.exe.find("sh") != std::string::npos ||
            event.exe.find("zsh") != std::string::npos) {
            severity = std::max(severity, 2);
        }
    }

    // Suspicious commands
    if (!event.argv.empty()) {
        std::string cmd = event.argv[0];
        // Common attack tools
        if (cmd.find("nc") != std::string::npos ||
            cmd.find("ncat") != std::string::npos ||
            cmd.find("socat") != std::string::npos ||
            cmd.find("wget") != std::string::npos ||
            cmd.find("curl") != std::string::npos ||
            cmd.find("chmod") != std::string::npos ||
            cmd.find("chown") != std::string::npos) {
            severity = std::max(severity, 1);
        }
    }

    // Failed syscall
    if (event.success == 0) {
        severity = std::max(severity, 1);
    }

    return severity;
}

// ============================================================================
// Main aggregation
// ============================================================================

std::vector<AggregatedAuditEvent> AuditdAggregator::aggregate(const std::string& content) {
    std::vector<AggregatedAuditEvent> results;

    // Step 1: Parse all lines
    std::vector<ParsedLine> allLines;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;
        auto parsed = parseLine(line);
        if (!parsed.type.empty()) {
            allLines.push_back(parsed);
        }
    }

    // Step 2: Group by (timestamp, serial)
    std::map<std::string, std::vector<ParsedLine>> groups;
    for (const auto& parsed : allLines) {
        std::string key = std::to_string(parsed.timestamp) + ":" + std::to_string(parsed.serialNumber);
        groups[key].push_back(parsed);
    }

    // Step 3: Merge each group into an aggregated event
    for (const auto& [key, lines] : groups) {
        auto event = mergeEvent(lines);
        if (!event.rawLines.empty()) {
            results.push_back(event);
        }
    }

    // Step 4: Sort by timestamp
    std::sort(results.begin(), results.end(),
        [](const AggregatedAuditEvent& a, const AggregatedAuditEvent& b) {
            return a.timestamp < b.timestamp;
        });

    return results;
}

} // namespace linux
} // namespace forensics
