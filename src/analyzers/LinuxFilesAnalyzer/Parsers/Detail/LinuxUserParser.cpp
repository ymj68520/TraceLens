// LinuxUserParser.cpp
// User and authentication analysis implementation

#include "../LinuxFilesAnalyzer.h"
#include "LinuxUserParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <filesystem>

namespace fs = std::filesystem;

// ============================================================================
// User and Authentication Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeUserAccounts() {
    std::cout << "Analyzing user accounts..." << std::endl;

    // Find and parse /etc/passwd
    auto passwdFiles = queryFilesByPattern("%/etc/passwd");
    std::vector<LinuxUserInfo> users;

    for (const auto& file : passwdFiles) {
        std::string extractPath = getExtractPath("etc/passwd");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                users = LinuxUserParser::parsePasswdFile(buffer.str());
            }
        }
        break; // Only one passwd file
    }

    // Find and parse /etc/shadow (if accessible)
    auto shadowFiles = queryFilesByPattern("%/etc/shadow");
    for (const auto& file : shadowFiles) {
        std::string extractPath = getExtractPath("etc/shadow");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                LinuxUserParser::parseShadowFile(buffer.str(), users);
            }
        }
        break;
    }

    // Save users to database
    linuxDb_->insertUserInfos(users);
    AuditLog::instance().log("SYSTEM", "LINUX_USERS_PARSED",
                              "Parsed " + std::to_string(users.size()) + " user accounts");

    // Find and parse /etc/group
    auto groupFiles = queryFilesByPattern("%/etc/group");
    for (const auto& file : groupFiles) {
        std::string extractPath = getExtractPath("etc/group");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                auto groups = LinuxUserParser::parseGroupFile(buffer.str());
                for (const auto& group : groups) {
                    linuxDb_->insertGroupInfo(group);
                }
            }
        }
        break;
    }
}

void LinuxFilesAnalyzer::analyzeLoginHistory() {
    std::cout << "Analyzing login history (wtmp, btmp)..." << std::endl;

    // Parse wtmp (successful logins)
    auto wtmpFiles = queryFilesByPattern("%/var/log/wtmp%");
    for (const auto& file : wtmpFiles) {
        std::string extractPath = getExtractPath("var/log/wtmp");
        if (extractFileToPath(file.inode, extractPath)) {
            auto records = LinuxUserParser::parseWtmpFile(extractPath);
            linuxDb_->insertLoginRecords(records);
            AuditLog::instance().log("SYSTEM", "LINUX_WTMP_PARSED",
                                      "Parsed " + std::to_string(records.size()) + " login records from wtmp");
        }
    }

    // Parse btmp (failed logins)
    auto btmpFiles = queryFilesByPattern("%/var/log/btmp%");
    for (const auto& file : btmpFiles) {
        std::string extractPath = getExtractPath("var/log/btmp");
        if (extractFileToPath(file.inode, extractPath)) {
            auto records = LinuxUserParser::parseBtmpFile(extractPath);
            linuxDb_->insertLoginRecords(records);
            AuditLog::instance().log("SYSTEM", "LINUX_BTMP_PARSED",
                                      "Parsed " + std::to_string(records.size()) + " failed login records from btmp");
        }
    }
}

void LinuxFilesAnalyzer::analyzeSSHArtifacts() {
    std::cout << "Analyzing SSH artifacts..." << std::endl;

    // Find authorized_keys files
    auto authKeysFiles = queryFilesByPattern("%/.ssh/authorized_keys");
    for (const auto& file : authKeysFiles) {
        std::string extractPath = getExtractPath("ssh/" + std::to_string(file.inode) + "_authorized_keys");
        if (extractFileToPath(file.inode, extractPath)) {
            // Extract username from path
            std::string username = "unknown";
            size_t homePos = file.path.find("/home/");
            size_t rootPos = file.path.find("/root/");

            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    username = file.path.substr(start, end - start);
                }
            } else if (rootPos != std::string::npos) {
                username = "root";
            }

            auto keys = parseAuthorizedKeys(extractPath, username);
            linuxDb_->insertSSHKeys(keys);
        }
    }

    // Find known_hosts files
    auto knownHostsFiles = queryFilesByPattern("%/.ssh/known_hosts");
    for (const auto& file : knownHostsFiles) {
        std::string extractPath = getExtractPath("ssh/" + std::to_string(file.inode) + "_known_hosts");
        if (extractFileToPath(file.inode, extractPath)) {
            // Extract username from path
            std::string username = "unknown";
            size_t homePos = file.path.find("/home/");
            size_t rootPos = file.path.find("/root/");

            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    username = file.path.substr(start, end - start);
                }
            } else if (rootPos != std::string::npos) {
                username = "root";
            }

            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                while (std::getline(f, line)) {
                    if (line.empty() || line[0] == '#') continue;

                    SSHKnownHost host;
                    host.username = username;

                    std::istringstream ss(line);
                    std::string hostname, keyType, publicKey;

                    ss >> hostname >> keyType >> publicKey;

                    // Check for hashed hostname format: |1|salt|hash
                    if (hostname.find("|1|") == 0) {
                        host.isHashed = true;
                        host.hostname = hostname; // Keep the hash
                    } else {
                        host.isHashed = false;
                        // Hostname can be comma-separated list
                        host.hostname = hostname;
                    }

                    host.keyType = keyType;
                    host.publicKey = publicKey;

                    linuxDb_->insertSSHKnownHost(host);
                }

                AuditLog::instance().log("SYSTEM", "LINUX_SSH_KNOWN_HOSTS_PARSED",
                                          "Parsed known_hosts for user " + username);
            }
        }
    }
}

std::vector<SSHKeyInfo> LinuxFilesAnalyzer::parseAuthorizedKeys(const std::string& keysPath,
                                                                  const std::string& username) {
    std::vector<SSHKeyInfo> keys;

    std::ifstream file(keysPath);
    if (!file.is_open()) {
        return keys;
    }

    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }

        SSHKeyInfo key;
        key.username = username;
        key.keyPath = keysPath;

        // Format: [options] key-type base64-key [comment]
        // Common key types: ssh-rsa, ssh-ed25519, ecdsa-sha2-nistp256

        std::istringstream ss(line);
        std::string token;
        std::vector<std::string> tokens;

        while (ss >> token) {
            tokens.push_back(token);
        }

        if (tokens.empty()) continue;

        size_t keyTypeIdx = 0;

        // Check if first token is options (doesn't start with ssh- or ecdsa-)
        if (!tokens[0].empty() &&
            tokens[0].find("ssh-") != 0 &&
            tokens[0].find("ecdsa-") != 0) {
            key.options = tokens[0];
            keyTypeIdx = 1;
        }

        if (keyTypeIdx < tokens.size()) {
            key.keyType = tokens[keyTypeIdx];
        }

        if (keyTypeIdx + 1 < tokens.size()) {
            key.publicKey = tokens[keyTypeIdx + 1];
        }

        // Rest is comment
        if (keyTypeIdx + 2 < tokens.size()) {
            key.comment = tokens[keyTypeIdx + 2];
            for (size_t i = keyTypeIdx + 3; i < tokens.size(); ++i) {
                key.comment += " " + tokens[i];
            }
        }

        keys.push_back(key);
    }

    return keys;
}

// ============================================================================
// User Parsing Wrappers
// ============================================================================

std::vector<LinuxUserInfo> LinuxFilesAnalyzer::parsePasswdFile(const std::string& passwdPath) {
    std::ifstream file(passwdPath);
    if (!file.is_open()) {
        return {};
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return LinuxUserParser::parsePasswdFile(buffer.str());
}

std::vector<LinuxUserInfo> LinuxFilesAnalyzer::parseShadowFile(const std::string& shadowPath,
                                                                 std::vector<LinuxUserInfo>& users) {
    std::ifstream file(shadowPath);
    if (!file.is_open()) {
        return users;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    LinuxUserParser::parseShadowFile(buffer.str(), users);
    return users;
}

std::vector<LinuxGroupInfo> LinuxFilesAnalyzer::parseGroupFile(const std::string& groupPath) {
    std::ifstream file(groupPath);
    if (!file.is_open()) {
        return {};
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return LinuxUserParser::parseGroupFile(buffer.str());
}

std::vector<LinuxLoginRecord> LinuxFilesAnalyzer::parseWtmpFile(const std::string& wtmpPath) {
    return LinuxUserParser::parseWtmpFile(wtmpPath);
}

std::vector<LinuxLoginRecord> LinuxFilesAnalyzer::parseBtmpFile(const std::string& btmpPath) {
    return LinuxUserParser::parseBtmpFile(btmpPath);
}
