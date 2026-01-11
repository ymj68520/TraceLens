// LinuxUserParser.cpp
// Implementation of Linux user and authentication parsing

#include "LinuxUserParser.h"
#include <sstream>
#include <fstream>
#include <cstring>
#include <algorithm>

// utmp structure for wtmp/btmp parsing
// Defined in <utmp.h> but we define it here for portability
#pragma pack(push, 1)
struct UtmpEntry {
    int16_t ut_type;         // Type of login
    int32_t ut_pid;          // Process ID
    char ut_line[32];        // Device name
    char ut_id[4];           // Terminal identifier
    char ut_user[32];        // Username
    char ut_host[256];       // Hostname or IP
    int32_t ut_exit_e_termination;
    int32_t ut_exit_e_exit;
    int32_t ut_session;      // Session ID
    int32_t ut_tv_sec;       // Timestamp seconds
    int32_t ut_tv_usec;      // Timestamp microseconds
    int32_t ut_addr_v6[4];   // IPv6 address
    char __unused[20];       // Reserved
};
#pragma pack(pop)

// utmp types
#define UT_EMPTY         0
#define UT_RUN_LVL       1
#define UT_BOOT_TIME     2
#define UT_NEW_TIME      3
#define UT_OLD_TIME      4
#define UT_INIT_PROCESS  5
#define UT_LOGIN_PROCESS 6
#define UT_USER_PROCESS  7
#define UT_DEAD_PROCESS  8
#define UT_ACCOUNTING    9

std::vector<LinuxUserInfo> LinuxUserParser::parsePasswdFile(const std::string& content) {
    std::vector<LinuxUserInfo> users;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        LinuxUserInfo user = parsePasswdLine(line);
        if (!user.username.empty()) {
            users.push_back(user);
        }
    }

    return users;
}

LinuxUserInfo LinuxUserParser::parsePasswdLine(const std::string& line) {
    LinuxUserInfo user;
    user.uid = -1;
    user.gid = -1;
    user.lastPasswordChange = 0;
    user.passwordMaxAge = 0;
    user.passwordMinAge = 0;
    user.passwordWarnDays = 0;
    user.inactiveDays = 0;
    user.accountExpires = 0;
    user.isLocked = false;
    user.isSystemAccount = false;

    // Format: username:password:uid:gid:gecos:home:shell
    std::vector<std::string> fields;
    std::stringstream ss(line);
    std::string field;

    while (std::getline(ss, field, ':')) {
        fields.push_back(field);
    }

    if (fields.size() >= 7) {
        user.username = fields[0];
        // fields[1] is 'x' or password hash (usually x, meaning hash is in /etc/shadow)
        try {
            user.uid = std::stoi(fields[2]);
            user.gid = std::stoi(fields[3]);
        } catch (...) {
            // Invalid UID/GID
        }
        user.fullName = fields[4];
        user.homeDirectory = fields[5];
        user.shell = fields[6];
        user.isSystemAccount = isSystemAccount(user.uid);
    }

    return user;
}

void LinuxUserParser::parseShadowFile(const std::string& content, 
                                        std::vector<LinuxUserInfo>& users) {
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }

        // Parse shadow line
        std::vector<std::string> fields;
        std::stringstream ss(line);
        std::string field;

        while (std::getline(ss, field, ':')) {
            fields.push_back(field);
        }

        if (fields.size() >= 2) {
            std::string username = fields[0];

            // Find matching user and update info
            for (auto& user : users) {
                if (user.username == username) {
                    parseShadowLine(line, user);
                    break;
                }
            }
        }
    }
}

void LinuxUserParser::parseShadowLine(const std::string& line, LinuxUserInfo& user) {
    // Format: username:password:lastchg:min:max:warn:inactive:expire:reserved
    std::vector<std::string> fields;
    std::stringstream ss(line);
    std::string field;

    while (std::getline(ss, field, ':')) {
        fields.push_back(field);
    }

    if (fields.size() >= 2) {
        user.passwordHash = fields[1];
        user.isLocked = isAccountLocked(user.passwordHash);
    }

    if (fields.size() >= 3 && !fields[2].empty()) {
        try {
            user.lastPasswordChange = std::stoll(fields[2]) * 86400; // Days to seconds
        } catch (...) {}
    }

    if (fields.size() >= 4 && !fields[3].empty()) {
        try {
            user.passwordMinAge = std::stoi(fields[3]);
        } catch (...) {}
    }

    if (fields.size() >= 5 && !fields[4].empty()) {
        try {
            user.passwordMaxAge = std::stoi(fields[4]);
        } catch (...) {}
    }

    if (fields.size() >= 6 && !fields[5].empty()) {
        try {
            user.passwordWarnDays = std::stoi(fields[5]);
        } catch (...) {}
    }

    if (fields.size() >= 7 && !fields[6].empty()) {
        try {
            user.inactiveDays = std::stoi(fields[6]);
        } catch (...) {}
    }

    if (fields.size() >= 8 && !fields[7].empty()) {
        try {
            user.accountExpires = std::stoll(fields[7]) * 86400; // Days to seconds
        } catch (...) {}
    }
}

std::vector<LinuxGroupInfo> LinuxUserParser::parseGroupFile(const std::string& content) {
    std::vector<LinuxGroupInfo> groups;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }
        LinuxGroupInfo group = parseGroupLine(line);
        if (!group.groupName.empty()) {
            groups.push_back(group);
        }
    }

    return groups;
}

LinuxGroupInfo LinuxUserParser::parseGroupLine(const std::string& line) {
    LinuxGroupInfo group;
    group.gid = -1;

    // Format: group_name:password:gid:user_list
    std::vector<std::string> fields;
    std::stringstream ss(line);
    std::string field;

    while (std::getline(ss, field, ':')) {
        fields.push_back(field);
    }

    if (fields.size() >= 3) {
        group.groupName = fields[0];
        // fields[1] is password (usually 'x' or empty)
        try {
            group.gid = std::stoi(fields[2]);
        } catch (...) {}

        // Parse member list (comma-separated)
        if (fields.size() >= 4 && !fields[3].empty()) {
            std::stringstream memberStream(fields[3]);
            std::string member;
            while (std::getline(memberStream, member, ',')) {
                if (!member.empty()) {
                    group.members.push_back(member);
                }
            }
        }
    }

    return group;
}

std::vector<LinuxLoginRecord> LinuxUserParser::parseWtmpFile(const std::string& filePath) {
    std::vector<LinuxLoginRecord> records;

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return records;
    }

    UtmpEntry entry;
    while (file.read(reinterpret_cast<char*>(&entry), sizeof(UtmpEntry))) {
        LinuxLoginRecord record;

        // Only process user process, login process, and boot time entries
        if (entry.ut_type != UT_USER_PROCESS && 
            entry.ut_type != UT_LOGIN_PROCESS &&
            entry.ut_type != UT_BOOT_TIME &&
            entry.ut_type != UT_DEAD_PROCESS) {
            continue;
        }

        record.username = std::string(entry.ut_user, strnlen(entry.ut_user, 32));
        record.terminal = std::string(entry.ut_line, strnlen(entry.ut_line, 32));
        record.remoteHost = std::string(entry.ut_host, strnlen(entry.ut_host, 256));
        record.loginTime = entry.ut_tv_sec;
        record.logoutTime = 0; // Would need to match with corresponding dead process
        record.pid = entry.ut_pid;
        record.isSuccess = true;

        // Determine login type
        if (entry.ut_type == UT_BOOT_TIME) {
            record.loginType = "reboot";
        } else if (record.terminal.find("pts") == 0) {
            record.loginType = "ssh";
        } else if (record.terminal.find("tty") == 0) {
            record.loginType = "console";
        } else {
            record.loginType = "login";
        }

        records.push_back(record);
    }

    return records;
}

std::vector<LinuxLoginRecord> LinuxUserParser::parseBtmpFile(const std::string& filePath) {
    std::vector<LinuxLoginRecord> records;

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return records;
    }

    UtmpEntry entry;
    while (file.read(reinterpret_cast<char*>(&entry), sizeof(UtmpEntry))) {
        LinuxLoginRecord record;

        record.username = std::string(entry.ut_user, strnlen(entry.ut_user, 32));
        record.terminal = std::string(entry.ut_line, strnlen(entry.ut_line, 32));
        record.remoteHost = std::string(entry.ut_host, strnlen(entry.ut_host, 256));
        record.loginTime = entry.ut_tv_sec;
        record.logoutTime = 0;
        record.pid = entry.ut_pid;
        record.isSuccess = false; // btmp records failed attempts

        // Determine login type
        if (record.terminal.find("ssh") != std::string::npos) {
            record.loginType = "ssh";
        } else {
            record.loginType = "login";
        }

        records.push_back(record);
    }

    return records;
}

std::vector<LinuxLoginRecord> LinuxUserParser::parseLastlogFile(const std::string& filePath,
                                                                  const std::vector<LinuxUserInfo>& users) {
    std::vector<LinuxLoginRecord> records;

    // lastlog format: fixed-size entries indexed by UID
    // Each entry is: time_t ll_time, char ll_line[32], char ll_host[256]
    
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        return records;
    }

    struct LastlogEntry {
        int32_t ll_time;
        char ll_line[32];
        char ll_host[256];
    };

    const size_t entrySize = sizeof(LastlogEntry);

    for (const auto& user : users) {
        if (user.uid < 0) continue;

        // Seek to the user's entry
        file.seekg(user.uid * entrySize);
        if (!file.good()) continue;

        LastlogEntry entry;
        if (!file.read(reinterpret_cast<char*>(&entry), entrySize)) {
            continue;
        }

        // Skip if no login recorded
        if (entry.ll_time == 0) continue;

        LinuxLoginRecord record;
        record.username = user.username;
        record.terminal = std::string(entry.ll_line, strnlen(entry.ll_line, 32));
        record.remoteHost = std::string(entry.ll_host, strnlen(entry.ll_host, 256));
        record.loginTime = entry.ll_time;
        record.logoutTime = 0;
        record.pid = 0;
        record.isSuccess = true;
        record.loginType = "lastlogin";

        records.push_back(record);
    }

    return records;
}

bool LinuxUserParser::isSystemAccount(int uid) {
    // On most Linux systems, UIDs below 1000 are system accounts
    // Some systems use 500 as the cutoff (older RHEL/CentOS)
    return uid >= 0 && uid < 1000;
}

bool LinuxUserParser::isAccountLocked(const std::string& passwordHash) {
    if (passwordHash.empty()) {
        return false;
    }

    // Account is locked if password starts with '!' or '*'
    // '!!' means password has never been set
    // '*' means account cannot login with password
    // '!$...' means account is locked (has password but disabled)
    return passwordHash[0] == '!' || passwordHash[0] == '*';
}
