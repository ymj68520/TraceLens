// LinuxHistoryParser.cpp
// Implementation of Linux shell history parsing

#include "LinuxHistoryParser.h"
#include <sstream>
#include <algorithm>
#include <regex>

std::vector<ShellHistoryEntry> LinuxHistoryParser::parseBashHistory(const std::string& content,
                                                                      const std::string& username,
                                                                      const std::string& historyFile) {
    std::vector<ShellHistoryEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNumber = 0;
    int64_t currentTimestamp = 0;

    while (std::getline(stream, line)) {
        lineNumber++;

        if (line.empty()) {
            continue;
        }

        // Check for timestamp line (HISTTIMEFORMAT support)
        // Format: #1234567890 (Unix timestamp preceded by #)
        if (line.length() > 1 && line[0] == '#') {
            try {
                currentTimestamp = std::stoll(line.substr(1));
                continue; // Timestamp line, next line is the command
            } catch (...) {
                // Not a valid timestamp, treat as comment or command
            }
        }

        ShellHistoryEntry entry;
        entry.username = username;
        entry.shellType = "bash";
        entry.command = line;
        entry.timestamp = currentTimestamp;
        entry.lineNumber = lineNumber;
        entry.historyFile = historyFile;

        // Reset timestamp after using it
        currentTimestamp = 0;

        entries.push_back(entry);
    }

    return entries;
}

std::vector<ShellHistoryEntry> LinuxHistoryParser::parseZshHistory(const std::string& content,
                                                                     const std::string& username,
                                                                     const std::string& historyFile) {
    std::vector<ShellHistoryEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNumber = 0;

    // zsh history format with EXTENDED_HISTORY:
    // : 1234567890:0;command
    // Without EXTENDED_HISTORY: just command

    std::regex extendedPattern("^: (\\d+):\\d+;(.*)$");

    while (std::getline(stream, line)) {
        lineNumber++;

        if (line.empty()) {
            continue;
        }

        ShellHistoryEntry entry;
        entry.username = username;
        entry.shellType = "zsh";
        entry.lineNumber = lineNumber;
        entry.historyFile = historyFile;

        std::smatch match;
        if (std::regex_match(line, match, extendedPattern)) {
            // Extended history format
            try {
                entry.timestamp = std::stoll(match[1].str());
            } catch (...) {
                entry.timestamp = 0;
            }
            entry.command = match[2].str();
        } else {
            // Simple format
            entry.timestamp = 0;
            entry.command = line;
        }

        entries.push_back(entry);
    }

    return entries;
}

std::vector<ShellHistoryEntry> LinuxHistoryParser::parseFishHistory(const std::string& content,
                                                                      const std::string& username,
                                                                      const std::string& historyFile) {
    std::vector<ShellHistoryEntry> entries;
    std::istringstream stream(content);
    std::string line;
    int lineNumber = 0;
    
    ShellHistoryEntry currentEntry;
    currentEntry.username = username;
    currentEntry.shellType = "fish";
    currentEntry.historyFile = historyFile;
    currentEntry.timestamp = 0;
    bool hasEntry = false;

    // fish history is YAML-like:
    // - cmd: command here
    //   when: 1234567890

    while (std::getline(stream, line)) {
        lineNumber++;

        if (line.empty()) {
            continue;
        }

        if (line.find("- cmd:") == 0) {
            // Save previous entry if exists
            if (hasEntry && !currentEntry.command.empty()) {
                entries.push_back(currentEntry);
            }

            // Start new entry
            currentEntry = ShellHistoryEntry();
            currentEntry.username = username;
            currentEntry.shellType = "fish";
            currentEntry.historyFile = historyFile;
            currentEntry.lineNumber = lineNumber;
            currentEntry.timestamp = 0;

            // Extract command (after "- cmd: ")
            if (line.length() > 7) {
                currentEntry.command = line.substr(7);
            }
            hasEntry = true;
        } else if (line.find("  when:") == 0 && hasEntry) {
            // Extract timestamp
            if (line.length() > 7) {
                try {
                    currentEntry.timestamp = std::stoll(line.substr(7));
                } catch (...) {}
            }
        }
    }

    // Save last entry
    if (hasEntry && !currentEntry.command.empty()) {
        entries.push_back(currentEntry);
    }

    return entries;
}

std::vector<ShellHistoryEntry> LinuxHistoryParser::parseHistoryFile(const std::string& content,
                                                                      const std::string& username,
                                                                      const std::string& historyFile,
                                                                      const std::string& shellType) {
    std::string type = shellType;
    if (type.empty()) {
        type = detectShellType(historyFile);
    }

    if (type == "bash") {
        return parseBashHistory(content, username, historyFile);
    } else if (type == "zsh") {
        return parseZshHistory(content, username, historyFile);
    } else if (type == "fish") {
        return parseFishHistory(content, username, historyFile);
    } else {
        // Default to bash-style parsing
        return parseBashHistory(content, username, historyFile);
    }
}

std::string LinuxHistoryParser::detectShellType(const std::string& historyFile) {
    std::string lowerFile = historyFile;
    std::transform(lowerFile.begin(), lowerFile.end(), lowerFile.begin(), ::tolower);

    if (lowerFile.find("bash_history") != std::string::npos ||
        lowerFile.find(".bash_history") != std::string::npos) {
        return "bash";
    }
    if (lowerFile.find("zsh_history") != std::string::npos ||
        lowerFile.find(".zsh_history") != std::string::npos ||
        lowerFile.find("histfile") != std::string::npos) {
        return "zsh";
    }
    if (lowerFile.find("fish") != std::string::npos ||
        lowerFile.find("fish_history") != std::string::npos) {
        return "fish";
    }
    if (lowerFile.find("sh_history") != std::string::npos) {
        return "sh";
    }

    return "bash"; // Default
}
