// LinuxUserParser.h
// Header for Linux user and authentication parsing

#pragma once
#ifndef LINUX_USER_PARSER_H
#define LINUX_USER_PARSER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"

// User and authentication parsing utility class
class LinuxUserParser {
public:
    // Parse /etc/passwd file
    static std::vector<LinuxUserInfo> parsePasswdFile(const std::string& content);
    static LinuxUserInfo parsePasswdLine(const std::string& line);

    // Parse /etc/shadow file and merge with existing user info
    static void parseShadowFile(const std::string& content, 
                                 std::vector<LinuxUserInfo>& users);
    static void parseShadowLine(const std::string& line, LinuxUserInfo& user);

    // Parse /etc/group file
    static std::vector<LinuxGroupInfo> parseGroupFile(const std::string& content);
    static LinuxGroupInfo parseGroupLine(const std::string& line);

    // Parse wtmp/utmp binary file (login records)
    static std::vector<LinuxLoginRecord> parseWtmpFile(const std::string& filePath);

    // Parse btmp binary file (failed login attempts)
    static std::vector<LinuxLoginRecord> parseBtmpFile(const std::string& filePath);

    // Parse lastlog binary file
    static std::vector<LinuxLoginRecord> parseLastlogFile(const std::string& filePath,
                                                           const std::vector<LinuxUserInfo>& users);

    // Determine if user is a system account
    static bool isSystemAccount(int uid);

    // Check if account is locked based on password hash
    static bool isAccountLocked(const std::string& passwordHash);
};

#endif // LINUX_USER_PARSER_H
