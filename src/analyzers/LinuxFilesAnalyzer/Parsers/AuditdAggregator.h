// AuditdAggregator.h
// Aggregates multi-line auditd events by serial number

#pragma once
#ifndef AUDITD_AGGREGATOR_H
#define AUDITD_AGGREGATOR_H

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include "LinuxDataTypes.h"

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Aggregated audit event combining multiple log lines with same serial
struct AggregatedAuditEvent {
    // Core identifiers
    int64_t timestamp = 0;               // Epoch seconds from msg=audit()
    int serialNumber = 0;                // Serial from msg=audit()
    std::string eventId;                 // Unique ID: "timestamp:serial"

    // SYSCALL fields
    int syscall = -1;                    // Syscall number
    std::string syscallName;             // Syscall name (if resolvable)
    int success = -1;                    // 1=success, 0=fail
    int exitCode = 0;                    // Exit code
    int pid = -1;                        // Process ID
    int ppid = -1;                       // Parent PID
    int uid = -1;                        // Effective UID
    int gid = -1;                        // Effective GID
    int euid = -1;                       // Effective UID
    int egid = -1;                       // Effective GID
    int auid = -1;                       // Audit UID (login UID)
    int ses = -1;                        // Session ID
    std::string exe;                     // Executable path
    std::string comm;                    // Command name
    std::string terminal;                // TTY
    std::string key;                     // Audit key filter

    // EXECVE fields
    std::vector<std::string> argv;       // Command arguments
    int argc = 0;                        // Argument count

    // CWD field
    std::string cwd;                     // Current working directory

    // PATH fields (list of paths accessed)
    struct PathEntry {
        std::string name;                // File path
        std::string inode;               // Inode number
        std::string mode;                // File mode
        std::string ouid;                // Owner UID
        std::string ogid;                // Owner GID
        int nametype = 0;               // 0=normal, 1=PARENT, 2=CREATE, etc.
    };
    std::vector<PathEntry> paths;

    // PROCTITLE field
    std::string proctitle;               // Process title (argv[0] reconstructed)

    // USER_AUTH / USER_ACCT / USER_CMD fields
    std::string authUser;                // User being authenticated
    std::string authOp;                  // Authentication operation
    std::string authAddr;                // Source address (for SSH)

    // Additional audit fields
    std::string subject;                 // Subject (user/process)
    std::string object;                  // Object affected
    std::string result;                  // Result string (success/fail)

    // AVC (SELinux) fields
    std::string avcAction;               // denied, granted
    std::string avcClass;                // file, process, etc.
    std::string avcPermission;           // read, write, execute, etc.

    // Raw records
    std::vector<std::string> rawLines;   // All raw log lines for this event

    // Classification
    std::string eventType;               // "process_execution", "file_access", "auth", "privilege_change"
    int severity = 0;                    // 0=info, 1=low, 2=medium, 3=high, 4=critical

    // Provenance
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// Main aggregator class
class AuditdAggregator {
public:
    // Parse and aggregate audit log content
    static std::vector<AggregatedAuditEvent> aggregate(const std::string& content);

    // Parse a single audit line into type + serial + fields
    struct ParsedLine {
        std::string type;
        int64_t timestamp = 0;
        int serialNumber = 0;
        std::string body;                // Everything after the type=... msg=audit(...): prefix
        std::string rawLine;
    };

    // Parse a single line
    static ParsedLine parseLine(const std::string& line);

    // Merge multiple ParsedLines with same serial into one AggregatedAuditEvent
    static AggregatedAuditEvent mergeEvent(const std::vector<ParsedLine>& lines);

    // Classify event type based on contained record types
    static std::string classifyEvent(const AggregatedAuditEvent& event);

    // Assess severity based on event content
    static int assessSeverity(const AggregatedAuditEvent& event);

private:
    // Extract key=value pairs from a string
    static std::map<std::string, std::string> extractKeyValues(const std::string& body);

    // Parse SYSCALL fields
    static void parseSyscall(AggregatedAuditEvent& event, const std::string& body);

    // Parse EXECVE fields
    static void parseExecve(AggregatedAuditEvent& event, const std::string& body);

    // Parse CWD field
    static void parseCwd(AggregatedAuditEvent& event, const std::string& body);

    // Parse PATH field
    static void parsePath(AggregatedAuditEvent& event, const std::string& body);

    // Parse PROCTITLE field
    static void parseProctitle(AggregatedAuditEvent& event, const std::string& body);

    // Parse USER_AUTH / USER_ACCT fields
    static void parseUserAuth(AggregatedAuditEvent& event, const std::string& body);

    // Parse AVC fields
    static void parseAvc(AggregatedAuditEvent& event, const std::string& body);

    // Hex decode a string (auditd encodes some fields in hex)
    static std::string hexDecode(const std::string& hex);
};

} // namespace linux
} // namespace forensics

#endif // AUDITD_AGGREGATOR_H
