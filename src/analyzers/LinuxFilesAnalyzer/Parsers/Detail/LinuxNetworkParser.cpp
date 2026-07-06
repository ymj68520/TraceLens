// LinuxNetworkParser.cpp
// Network and security analysis implementation

#include "../LinuxFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Parsers/AuditdAggregator.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <regex>

namespace fs = std::filesystem;

// ============================================================================
// Network Configuration Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeNetworkConfiguration() {
    std::cout << "Analyzing network configuration..." << std::endl;

    // Parse /etc/network/interfaces (Debian-based systems)
    auto interfacesFiles = queryFilesByPattern("%/etc/network/interfaces");
    for (const auto& file : interfacesFiles) {
        std::string extractPath = getExtractPath("network/interfaces");
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                NetworkConnection conn;
                std::string currentInterface;

                while (std::getline(f, line)) {
                    // Trim
                    size_t start = line.find_first_not_of(" \t");
                    if (start == std::string::npos) continue;
                    line = line.substr(start);

                    if (line.empty() || line[0] == '#') continue;

                    std::istringstream ss(line);
                    std::string keyword;
                    ss >> keyword;

                    if (keyword == "iface") {
                        // iface eth0 inet static
                        std::string iface, family, method;
                        ss >> iface >> family >> method;
                        currentInterface = iface;
                    } else if (keyword == "address" && !currentInterface.empty()) {
                        std::string addr;
                        ss >> addr;
                        conn.localAddress = addr;
                        conn.protocol = "interface:" + currentInterface;
                        conn.state = "configured";
                        linuxDb_->insertNetworkConnection(conn);
                    }
                }
            }
        }
    }

    // Parse /etc/resolv.conf for DNS configuration
    auto resolvFiles = queryFilesByPattern("%/etc/resolv.conf");
    for (const auto& file : resolvFiles) {
        std::string extractPath = getExtractPath("network/resolv.conf");
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                while (std::getline(f, line)) {
                    size_t start = line.find_first_not_of(" \t");
                    if (start == std::string::npos) continue;
                    line = line.substr(start);

                    if (line.empty() || line[0] == '#') continue;

                    std::istringstream ss(line);
                    std::string keyword;
                    ss >> keyword;

                    if (keyword == "nameserver") {
                        std::string dns;
                        ss >> dns;
                        NetworkConnection conn;
                        conn.protocol = "dns";
                        conn.remoteAddress = dns;
                        conn.remotePort = 53;
                        conn.state = "configured";
                        linuxDb_->insertNetworkConnection(conn);
                    }
                }
            }
        }
    }

    // Parse /etc/hosts for static host mappings
    auto hostsFiles = queryFilesByPattern("%/etc/hosts");
    for (const auto& file : hostsFiles) {
        std::string extractPath = getExtractPath("network/hosts");
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            // Just log that we found hosts file; detailed parsing could be added
            AuditLog::instance().log("SYSTEM", "LINUX_HOSTS_FOUND",
                                      "Found /etc/hosts file at " + file.path);
        }
    }

    AuditLog::instance().log("SYSTEM", "LINUX_NETWORK_CONFIG_PARSED",
                              "Analyzed network configuration files");
}

// ============================================================================
// Security Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeFirewallRules() {
    std::cout << "Analyzing firewall rules..." << std::endl;

    // Common locations for iptables rules
    std::vector<std::string> iptablesPaths = {
        "%/etc/iptables/rules.v4",
        "%/etc/iptables/rules.v6",
        "%/etc/iptables.rules",
        "%/etc/sysconfig/iptables",
        "%/etc/ufw/user.rules",
        "%/etc/ufw/user6.rules"
    };

    std::vector<FirewallRule> allRules;

    for (const auto& pattern : iptablesPaths) {
        auto ruleFiles = queryFilesByPattern(pattern);
        for (const auto& file : ruleFiles) {
            std::string extractPath = getExtractPath("firewall/" + file.name);
            if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
                std::ifstream f(extractPath);
                if (f.is_open()) {
                    std::string line;
                    std::string currentTable = "filter"; // Default table
                    std::string currentChain;

                    while (std::getline(f, line)) {
                        // Trim
                        size_t start = line.find_first_not_of(" \t");
                        if (start == std::string::npos) continue;
                        line = line.substr(start);

                        if (line.empty() || line[0] == '#') continue;

                        // Table header: *filter, *nat, *mangle
                        if (line[0] == '*') {
                            currentTable = line.substr(1);
                            continue;
                        }

                        // COMMIT - end of table
                        if (line == "COMMIT") {
                            continue;
                        }

                        // Chain definition: :INPUT ACCEPT [0:0]
                        if (line[0] == ':') {
                            size_t spacePos = line.find(' ');
                            if (spacePos != std::string::npos) {
                                currentChain = line.substr(1, spacePos - 1);
                            }
                            continue;
                        }

                        // Rule: -A INPUT -p tcp --dport 22 -j ACCEPT
                        if (line.find("-A ") == 0 || line.find("-I ") == 0) {
                            FirewallRule rule;
                            rule.table = currentTable;
                            rule.ruleSpec = line;

                            std::istringstream ss(line);
                            std::string token;

                            while (ss >> token) {
                                if (token == "-A" || token == "-I") {
                                    ss >> rule.chain;
                                } else if (token == "-p") {
                                    ss >> rule.protocol;
                                } else if (token == "-s") {
                                    ss >> rule.source;
                                } else if (token == "-d") {
                                    ss >> rule.destination;
                                } else if (token == "--sport") {
                                    std::string port;
                                    ss >> port;
                                    try { rule.sourcePort = std::stoi(port); }
                                    catch (...) { rule.sourcePort = -1; }
                                } else if (token == "--dport") {
                                    std::string port;
                                    ss >> port;
                                    try { rule.destinationPort = std::stoi(port); }
                                    catch (...) { rule.destinationPort = -1; }
                                } else if (token == "-j") {
                                    ss >> rule.action;
                                }
                            }

                            allRules.push_back(rule);
                        }
                    }
                }
            }
        }
    }

    // Insert all rules to database
    for (const auto& rule : allRules) {
        linuxDb_->insertFirewallRule(rule);
    }

    AuditLog::instance().log("SYSTEM", "LINUX_FIREWALL_PARSED",
                              "Parsed " + std::to_string(allRules.size()) + " firewall rules");
}

void LinuxFilesAnalyzer::analyzeAuditLogs() {
    using namespace forensics::linux;

    std::cout << "Analyzing audit logs..." << std::endl;

    auto auditFiles = queryFilesByPattern("%/var/log/audit/audit.log%");
    std::vector<LinuxAuditLogEntry> allEntries;
    std::vector<AggregatedAuditEvent> allAggregatedEvents;
    int totalFiles = 0;
    int totalEvents = 0;

    for (const auto& file : auditFiles) {
        std::string extractPath = getExtractPath("audit/" + file.name);
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                totalFiles++;

                // Read entire file content for aggregation
                std::ostringstream content;
                content << f.rdbuf();
                f.close();

                std::string contentStr = content.str();

                // Aggregate multi-line events
                auto aggregatedEvents = AuditdAggregator::aggregate(contentStr);
                totalEvents += aggregatedEvents.size();

                // Set provenance for all aggregated events
                for (auto& event : aggregatedEvents) {
                    event.provenance.sourceFile = file.path;
                    event.provenance.sourceInode = file.inode;
                }

                allAggregatedEvents.insert(allAggregatedEvents.end(),
                    aggregatedEvents.begin(), aggregatedEvents.end());

                // Also create legacy line-by-line entries for backward compatibility
                std::istringstream stream(contentStr);
                std::string line;
                std::regex auditPattern(R"(type=(\w+)\s+msg=audit\((\d+)\.(\d+):(\d+)\):(.*))");

                while (std::getline(stream, line)) {
                    if (line.empty()) continue;

                    std::smatch match;
                    if (std::regex_search(line, match, auditPattern)) {
                        LinuxAuditLogEntry entry;
                        entry.type = match[1].str();

                        try {
                            entry.timestamp = std::stoll(match[2].str());
                        } catch (...) {
                            entry.timestamp = 0;
                        }

                        try {
                            entry.serialNumber = std::stoi(match[4].str());
                        } catch (...) {
                            entry.serialNumber = 0;
                        }

                        entry.message = line;

                        // Extract additional fields
                        std::string msgPart = match[5].str();

                        size_t resultPos = msgPart.find("res=");
                        if (resultPos != std::string::npos) {
                            size_t start = resultPos + 4;
                            size_t end = msgPart.find(' ', start);
                            entry.result = msgPart.substr(start, end - start);
                        }

                        size_t uidPos = msgPart.find("auid=");
                        if (uidPos != std::string::npos) {
                            size_t start = uidPos + 5;
                            size_t end = msgPart.find(' ', start);
                            entry.subject = "auid=" + msgPart.substr(start, end - start);
                        }

                        size_t exePos = msgPart.find("exe=\"");
                        if (exePos != std::string::npos) {
                            size_t start = exePos + 5;
                            size_t end = msgPart.find('"', start);
                            if (end != std::string::npos) {
                                entry.object = msgPart.substr(start, end - start);
                            }
                        }

                        if (entry.type.find("SYSCALL") != std::string::npos) {
                            entry.action = "syscall";
                        } else if (entry.type.find("USER_") != std::string::npos) {
                            entry.action = "user_action";
                        } else if (entry.type.find("LOGIN") != std::string::npos) {
                            entry.action = "login";
                        } else {
                            entry.action = "audit";
                        }

                        allEntries.push_back(entry);
                    }
                }

                std::cout << "  Parsed " << aggregatedEvents.size()
                          << " aggregated events from " << file.name << std::endl;
            }
        }
    }

    // Insert legacy entries
    if (!allEntries.empty()) {
        linuxDb_->insertAuditLogs(allEntries);
    }

    // Insert aggregated events
    if (!allAggregatedEvents.empty()) {
        if (!linuxDb_->insertAuditEvents(allAggregatedEvents)) {
            std::cerr << "  Failed to insert aggregated audit events" << std::endl;
        } else {
            std::cout << "  Stored " << allAggregatedEvents.size()
                      << " aggregated audit events in database" << std::endl;
        }
    }

    std::cout << "  Audit log analysis complete: "
              << totalFiles << " files, "
              << allEntries.size() << " raw entries, "
              << totalEvents << " aggregated events" << std::endl;

    AuditLog::instance().log("SYSTEM", "LINUX_AUDIT_LOGS_PARSED",
                              "Parsed " + std::to_string(allEntries.size()) + " raw entries, " +
                              std::to_string(totalEvents) + " aggregated events from " +
                              std::to_string(totalFiles) + " files");
}

// ============================================================================
// Browser Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeBrowserData() {
    std::cout << "Analyzing browser data..." << std::endl;

    // Chrome/Chromium profiles
    auto chromeProfiles = queryFilesByPattern("%/.config/google-chrome/%");
    auto chromiumProfiles = queryFilesByPattern("%/.config/chromium/%");

    // Firefox profiles
    auto firefoxProfiles = queryFilesByPattern("%/.mozilla/firefox/%");

    // Placeholder - actual browser parsing would use similar logic to Windows browser parser
    // but with Linux-appropriate paths

    for (const auto& file : chromeProfiles) {
        if (file.path.find("Default") != std::string::npos ||
            file.path.find("Profile") != std::string::npos) {
            LinuxBrowserProfile profile;
            profile.browserType = LinuxBrowserType::CHROME;
            profile.browserName = "Google Chrome";
            profile.profilePath = file.path;

            // Extract username from path
            size_t homePos = file.path.find("/home/");
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    profile.username = file.path.substr(start, end - start);
                }
            }

            linuxDb_->insertBrowserProfile(profile);
        }
    }

    for (const auto& file : firefoxProfiles) {
        if (file.name.find(".default") != std::string::npos) {
            LinuxBrowserProfile profile;
            profile.browserType = LinuxBrowserType::FIREFOX;
            profile.browserName = "Firefox";
            profile.profilePath = file.path;
            profile.profileName = file.name;

            size_t homePos = file.path.find("/home/");
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    profile.username = file.path.substr(start, end - start);
                }
            }

            linuxDb_->insertBrowserProfile(profile);
        }
    }
}
