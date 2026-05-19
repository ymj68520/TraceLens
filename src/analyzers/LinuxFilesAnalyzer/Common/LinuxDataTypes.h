// LinuxDataTypes.h
// Data structures for Linux file analysis

#pragma once
#ifndef LINUX_DATA_TYPES_H
#define LINUX_DATA_TYPES_H

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include <sys/types.h>

// ============================================================================
// Evidence Provenance - All parsed results must include this
// ============================================================================

// Evidence provenance for forensic traceability
struct EvidenceProvenance {
    std::string parserName;        // Parser name (e.g., "JournalParser", "SyslogParser")
    std::string parserVersion;     // Parser version (e.g., "1.0.0")
    std::string sourceFile;        // Source file path
    int64_t sourceOffset = -1;     // Byte offset in source file
    int64_t sourceLine = -1;       // Line number in source file
    int64_t sourceInode = -1;      // inode number of source file
    std::string sourceHash;        // Source file hash (MD5/SHA256)
    std::string parseError;        // Parse error message (empty if success)
    std::string rawRecord;         // Original raw record preserved
    int confidence = 100;          // Confidence score 0-100
};

// Normalized timestamp for unified timeline
struct NormalizedTimestamp {
    std::string originalTimestamp;      // Original timestamp string
    int64_t normalizedUtcTimestamp = 0; // Normalized UTC Unix timestamp
    std::string timezoneSource;         // "file", "system", "inferred", "utc"
    int timestampConfidence = 100;      // Confidence 0-100
    std::string bootId;                 // Boot ID (for monotonic timestamps)
    int64_t monotonicTimestamp = 0;     // Raw monotonic timestamp value
    int inferredYear = 0;               // Inferred year (syslog has no year)
    bool clockSkewFlag = false;         // Detected clock skew
};

// System log entry (auth.log, syslog, messages, kern.log)
struct LinuxLogEntry {
    std::string logFile;             // Log file source (auth.log, syslog, etc.)
    std::string timestamp;           // Original timestamp string
    int64_t unixTimestamp = 0;       // Unix timestamp
    std::string hostname;            // Hostname
    std::string process;             // Process name
    int pid = -1;                    // Process ID (-1 if not available)
    std::string message;             // Log message content
    std::string level;               // Log level (INFO, WARNING, ERROR, etc.)
    std::string facility;            // Syslog facility (auth, daemon, kern, etc.)
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

// Linux user account information (/etc/passwd + /etc/shadow)
struct LinuxUserInfo {
    std::string username;            // Username
    int uid = -1;                    // User ID
    int gid = -1;                    // Primary Group ID
    std::string fullName;            // GECOS field (full name/comment)
    std::string homeDirectory;       // Home directory path
    std::string shell;               // Login shell
    std::string passwordHash;        // Password hash from shadow (if accessible)
    int64_t lastPasswordChange = 0;  // Last password change (days since epoch)
    int passwordMaxAge = 0;          // Max password age in days
    int passwordMinAge = 0;          // Min password age in days
    int passwordWarnDays = 0;        // Password warning days
    int inactiveDays = 0;            // Days after password expires until account is disabled
    int64_t accountExpires = 0;      // Account expiration date
    bool isLocked = false;           // Is account locked
    bool isSystemAccount = false;    // Is system account (uid < 1000 typically)
    EvidenceProvenance provenance;   // Evidence provenance
};

// Linux group information (/etc/group)
struct LinuxGroupInfo {
    std::string groupName;           // Group name
    int gid = -1;                    // Group ID
    std::vector<std::string> members; // Group members
    EvidenceProvenance provenance;   // Evidence provenance
};

// Login record (wtmp/btmp/lastlog)
struct LinuxLoginRecord {
    std::string username;            // Username
    std::string terminal;            // Terminal device (tty, pts)
    std::string remoteHost;          // Remote host/IP address
    int64_t loginTime = 0;           // Login timestamp
    int64_t logoutTime = 0;          // Logout timestamp (0 if still logged in)
    std::string loginType;           // Login type: login, ssh, console, reboot, shutdown
    bool isSuccess = true;           // Success (wtmp) or failure (btmp)
    int pid = 0;                     // Process ID
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

// Shell history entry (bash_history, zsh_history)
struct ShellHistoryEntry {
    std::string username;            // Username who executed command
    std::string shellType;           // Shell type: bash, zsh, fish, sh
    std::string command;             // Command content
    int64_t timestamp = 0;           // Timestamp (if available, e.g., HISTTIMEFORMAT)
    int lineNumber = 0;              // Line number in history file
    std::string historyFile;         // Source history file path
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

// Cron job entry
struct CronJobEntry {
    std::string username;            // User who owns the cron job
    std::string minute;              // Minute field
    std::string hour;                // Hour field
    std::string dayOfMonth;          // Day of month field
    std::string month;               // Month field
    std::string dayOfWeek;           // Day of week field
    std::string command;             // Command to execute
    std::string cronFile;            // Source cron file path
    std::string cronType;            // Type: user, system, cron.d, cron.daily, etc.
    EvidenceProvenance provenance;   // Evidence provenance
};

// SSH authorized key entry
struct SSHKeyInfo {
    std::string username;            // Username
    std::string keyType;             // Key type: ssh-rsa, ssh-ed25519, ecdsa-sha2-*
    std::string publicKey;           // Public key content (base64)
    std::string keyPath;             // Path to authorized_keys file
    std::string comment;             // Key comment (usually email or host)
    std::string options;             // Key options (if any)
    EvidenceProvenance provenance;   // Evidence provenance
};

// SSH known host entry
struct SSHKnownHost {
    std::string username;            // Username (owner of known_hosts)
    std::string hostname;            // Hostname or IP
    std::string keyType;             // Key type
    std::string publicKey;           // Host public key
    bool isHashed = false;           // Is hostname hashed
    EvidenceProvenance provenance;   // Evidence provenance
};

// Installed package information
struct PackageInfo {
    std::string name;                // Package name
    std::string version;             // Package version
    std::string architecture;        // Architecture (amd64, i386, etc.)
    int64_t installTime = 0;         // Installation timestamp
    std::string packageManager;      // Package manager: apt, dpkg, yum, dnf, rpm
    std::string status;              // Status: installed, config-files, etc.
    std::string description;         // Package description
    std::string maintainer;          // Package maintainer
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

// Network connection information
struct NetworkConnection {
    std::string protocol;            // Protocol: tcp, tcp6, udp, udp6
    std::string localAddress;        // Local IP address
    int localPort = 0;               // Local port
    std::string remoteAddress;       // Remote IP address
    int remotePort = 0;              // Remote port
    std::string state;               // Connection state: LISTEN, ESTABLISHED, etc.
    int uid = -1;                    // User ID of connection owner
    int inode = 0;                   // Socket inode
    std::string process;             // Process name (if available)
    int pid = -1;                    // Process ID (if available)
    EvidenceProvenance provenance;   // Evidence provenance
};

// Systemd service information
struct SystemdServiceInfo {
    std::string serviceName;         // Service unit name
    std::string description;         // Service description
    std::string loadState;           // Load state: loaded, not-found, etc.
    std::string activeState;         // Active state: active, inactive, failed
    std::string subState;            // Sub state: running, exited, dead
    std::string unitFile;            // Path to unit file
    std::string execStart;           // ExecStart command
    std::string user;                // User the service runs as
    bool isEnabled = false;          // Is enabled at boot
    EvidenceProvenance provenance;   // Evidence provenance
};

// Kernel module information
struct KernelModuleInfo {
    std::string moduleName;          // Module name
    int64_t size = 0;                // Size in bytes
    int usedCount = 0;               // Use count
    std::vector<std::string> usedBy; // Modules that depend on this
    std::string state;               // Live, Loading, Unloading
    std::string filename;            // Module file path
    EvidenceProvenance provenance;   // Evidence provenance
};

// Firewall rule (iptables/nftables)
struct FirewallRule {
    std::string chain;               // Chain: INPUT, OUTPUT, FORWARD
    std::string table;               // Table: filter, nat, mangle
    std::string protocol;            // Protocol: tcp, udp, icmp, all
    std::string source;              // Source address/network
    std::string destination;         // Destination address/network
    int sourcePort = -1;             // Source port (-1 for any)
    int destinationPort = -1;        // Destination port (-1 for any)
    std::string action;              // Action: ACCEPT, DROP, REJECT
    std::string ruleSpec;            // Full rule specification
    EvidenceProvenance provenance;   // Evidence provenance
};

// Audit log entry (auditd) - Named LinuxAuditLogEntry to avoid collision with project's AuditLog
struct LinuxAuditLogEntry {
    int64_t timestamp = 0;           // Event timestamp
    int serialNumber = 0;            // Audit serial number
    std::string type;                // Event type: SYSCALL, USER_AUTH, etc.
    std::string message;             // Full message content
    std::string subject;             // Subject (user/process)
    std::string object;              // Object affected
    std::string action;              // Action performed
    std::string result;              // Result: success, fail
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

// Browser data structures - reuse from Windows (same SQLite format)
// Chrome, Firefox, etc. use the same database format on Linux

enum class LinuxBrowserType {
    CHROME,
    CHROMIUM,
    FIREFOX,
    OPERA,
    BRAVE,
    UNKNOWN
};

struct LinuxBrowserProfile {
    LinuxBrowserType browserType = LinuxBrowserType::UNKNOWN;
    std::string browserName;         // Human-readable name
    std::string profileName;         // Profile folder/identifier
    std::string profilePath;         // Full path to profile
    std::string username;            // Linux user who owns the profile
    EvidenceProvenance provenance;   // Evidence provenance
};

// ============================================================================
// Container Data Structures
// ============================================================================

struct DockerContainerInfo {
    std::string containerId;
    std::string imageName;
    std::string imageTag;
    std::string command;
    int64_t createdAt = 0;
    std::string state;
    std::vector<std::string> mounts;
    std::vector<std::string> ports;
    std::string networkMode;
    std::string hostConfig;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct DockerImageInfo {
    std::string imageId;
    std::vector<std::string> tags;
    int64_t size = 0;
    int64_t createdAt = 0;
    std::vector<std::string> layerIds;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct DockerVolumeInfo {
    std::string volumeName;
    std::string mountpoint;
    std::string driver;
    int64_t createdAt = 0;
    std::vector<std::string> containerIds;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct PodmanContainerInfo {
    std::string containerId;
    std::string imageName;
    std::string podName;
    bool isRootless = false;
    std::string state;
    int64_t createdAt = 0;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct PodmanPodInfo {
    std::string podName;
    std::string podId;
    std::vector<std::string> containerIds;
    std::string state;
    int64_t createdAt = 0;
    EvidenceProvenance provenance;   // Evidence provenance
};

// ============================================================================
// Web Server Data Structures
// ============================================================================

struct ApacheAccessLogEntry {
    int64_t timestamp = 0;
    std::string remoteIp;
    std::string method;
    std::string url;
    std::string httpVersion;
    int statusCode = 0;
    int responseSize = 0;
    std::string referer;
    std::string userAgent;
    std::string vhost;
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

struct ApacheVHostConfig {
    std::string serverName;
    std::string documentRoot;
    std::vector<std::string> serverAliases;
    std::vector<std::string> sslCertificates;
    std::string configFilePath;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct NginxAccessLogEntry {
    int64_t timestamp = 0;
    std::string remoteIp;
    std::string method;
    std::string url;
    int statusCode = 0;
    int responseSize = 0;
    std::string referer;
    std::string userAgent;
    float requestTime = 0.0f;
    std::string upstreamAddr;
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

struct NginxServerBlock {
    std::string serverName;
    std::string root;
    std::vector<std::string> locations;
    std::string sslCertificate;
    std::string sslCertificateKey;
    std::vector<std::string> upstreams;
    std::string configFilePath;
    EvidenceProvenance provenance;   // Evidence provenance
};

// ============================================================================
// Security Data Structures
// ============================================================================

struct SetuidFileInfo {
    std::string filePath;
    std::string owner;
    std::string groupName;
    mode_t permissions = 0;
    bool isSetuid = false;
    bool isSetgid = false;
    int64_t size = 0;
    std::string md5Hash;
    std::string sha256Hash;
    bool isSuspicious = false;
    std::string suspiciousReason;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct FileCapability {
    std::string filePath;
    std::vector<std::string> capabilities;
    std::string capabilitySet;
    bool isInherited = false;
    bool isSuspicious = false;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct SELinuxStatus {
    bool isEnabled = false;
    std::string mode;
    std::string policyName;
    std::string currentMode;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct SELinuxAVCDenial {
    int64_t timestamp = 0;
    std::string sourceContext;
    std::string targetContext;
    std::string objectClass;
    std::string permission;
    std::string executablePath;
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

struct AppArmorProfile {
    std::string profileName;
    std::string mode;
    std::string filePath;
    std::vector<std::string> allowedPaths;
    std::vector<std::string> deniedPaths;
    bool isEnabled = false;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct AppArmorViolation {
    int64_t timestamp = 0;
    std::string profile;
    std::string operation;
    std::string targetPath;
    std::string executable;
    std::string status;
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

// ============================================================================
// Enhanced Analysis Data Structures
// ============================================================================

struct CorrelatedEvent {
    int64_t startTimestamp = 0;
    int64_t endTimestamp = 0;
    std::string eventType;
    std::string initiatingUser;
    std::string initiatingProcess;
    std::vector<std::string> relatedEventIds;
    std::string description;
    int severity = 0;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct AttackChain {
    std::string chainId;
    std::string attackType;
    std::vector<CorrelatedEvent> events;
    std::string timeline;
    std::string summary;
    float confidence = 0.0f;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct LinuxTimelineEvent {
    int64_t timestamp = 0;
    std::string sourceType;
    std::string eventType;
    std::string description;
    std::string username;
    std::string ipAddress;
    std::string details;
    int confidence = 0;
    NormalizedTimestamp normalizedTime;  // Normalized timestamp
    EvidenceProvenance provenance;       // Evidence provenance
};

struct TimelineGap {
    int64_t startTime = 0;
    int64_t endTime = 0;
    int64_t duration = 0;
    std::string description;
    bool isSuspicious = false;
    EvidenceProvenance provenance;   // Evidence provenance
};

struct Anomaly {
    std::string anomalyType;
    std::string description;
    int severity = 0;
    float confidence = 0.0f;
    std::vector<std::string> evidenceIds;
    std::string mitigation;
    int64_t detectedAt = 0;
    std::string anomalySubtype;
    std::string additionalData;
    EvidenceProvenance provenance;   // Evidence provenance
};

// ============================================================================
// Persistence Mechanism Data Structures (Phase 6)
// ============================================================================

enum class PersistenceType {
    RC_LOCAL,           // /etc/rc.local
    INIT_D_SCRIPT,      // /etc/init.d/*
    SHELL_PROFILE,      // /etc/profile, ~/.bashrc, ~/.profile, /etc/bash.bashrc
    AUTHORIZED_KEYS,    // ~/.ssh/authorized_keys
    LD_SO_PRELOAD,      // /etc/ld.so.preload
    SUDOERS,            // /etc/sudoers, /etc/sudoers.d/*
    UDEV_RULE,          // /etc/udev/rules.d/*.rules
    POLKIT_RULE,        // /etc/polkit-1/rules.d/*.rules
    XINETD_SERVICE,     // /etc/xinetd.d/*
    SYSTEMD_TIMER,      // *.timer units
    AT_JOB,             // /var/spool/at/*
    CRON_JOB,           // Already parsed, but included for completeness
    SYSTEMD_SERVICE,    // Already parsed, but included for completeness
    UNKNOWN_PERSISTENCE
};

enum class PersistenceRisk {
    LOW,        // Standard system persistence
    MEDIUM,    // Unusual but possibly legitimate
    HIGH,       // Suspicious pattern
    CRITICAL    // Known malicious pattern
};

struct PersistenceEntry {
    PersistenceType type = PersistenceType::UNKNOWN_PERSISTENCE;
    PersistenceRisk risk = PersistenceRisk::LOW;
    std::string filePath;              // Source file path
    std::string entryName;             // Entry name (service name, timer name, etc.)
    std::string command;               // Command or executable being persisted
    std::string arguments;             // Command arguments
    std::string username;              // Owner user
    std::string schedule;              // Schedule expression (cron, OnCalendar, etc.)
    bool isEnabled = true;             // Is the persistence active
    bool isSuspicious = false;         // Flagged as suspicious
    std::string suspiciousReason;      // Why it's suspicious
    std::string rawContent;            // Original raw content
    EvidenceProvenance provenance;     // Evidence provenance
};

#endif // LINUX_DATA_TYPES_H
