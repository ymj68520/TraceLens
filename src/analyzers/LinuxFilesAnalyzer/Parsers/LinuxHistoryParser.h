// LinuxHistoryParser.h
// Header for Linux shell history parsing

#pragma once
#ifndef LINUX_HISTORY_PARSER_H
#define LINUX_HISTORY_PARSER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"

// Shell history parsing utility class
class LinuxHistoryParser {
public:
    // Parse bash history file
    static std::vector<ShellHistoryEntry> parseBashHistory(const std::string& content,
                                                            const std::string& username,
                                                            const std::string& historyFile);

    // Parse zsh history file
    static std::vector<ShellHistoryEntry> parseZshHistory(const std::string& content,
                                                           const std::string& username,
                                                           const std::string& historyFile);

    // Parse fish history file (YAML format)
    static std::vector<ShellHistoryEntry> parseFishHistory(const std::string& content,
                                                            const std::string& username,
                                                            const std::string& historyFile);

    // Generic history file parser (auto-detect format)
    static std::vector<ShellHistoryEntry> parseHistoryFile(const std::string& content,
                                                            const std::string& username,
                                                            const std::string& historyFile,
                                                            const std::string& shellType);

    // Detect shell type from history file path
    static std::string detectShellType(const std::string& historyFile);
};

#endif // LINUX_HISTORY_PARSER_H
