// ADBClient_Shell.cpp
// Shell execution and file transfer methods

#include "adbClient.h"
#include <fstream>

std::string ADBClient::executeShell(const std::string &command) {
    if (current_device_.empty()) {
        return "";
    }

    if (!sendADBCommand("SHELL:" + command)) {
        return "";
    }

    // For shell commands, we might not always get OKAY
    // Try to read response anyway
    std::string response = receiveData(8192);

    // Trim trailing null characters
    size_t end = response.find('\0');
    if (end != std::string::npos) {
        response = response.substr(0, end);
    }

    return response;
}

bool ADBClient::syncConnect() {
    std::string cmd = "SYNC:";
    if (!sendADBCommand(cmd)) {
        return false;
    }
    return receiveADBStatus();
}

bool ADBClient::receiveFile(const std::string &remote_path,
                             const std::string &local_path,
                             uint32_t total_file_size) {
    if (current_device_.empty()) {
        return false;
    }

    // Use shell-based approach for simplicity
    std::string cmd = "dd if=" + remote_path + " bs=4096 2>/dev/null";
    std::string data = executeShell(cmd);

    if (data.empty()) {
        return false;
    }

    std::ofstream out(local_path, std::ios::binary);
    if (!out.is_open()) {
        return false;
    }

    out.write(data.data(), data.size());
    out.close();

    return true;
}

bool ADBClient::statFile(const std::string &remote_path,
                         uint32_t &mode, uint32_t &size, uint32_t &time) {
    return statFileShell(remote_path, mode, size, time);
}

std::vector<ADBClient::SyncEntry> ADBClient::listDirectory(const std::string &path) {
    return listDirectoryShell(path);
}

bool ADBClient::checkRootAccess() {
    std::string result = executeShell("id");
    return result.find("uid=0") != std::string::npos;
}

bool ADBClient::acquireRoot() {
    // Remount with root
    std::string result = executeShell("su -c 'id'");
    return result.find("uid=0") != std::string::npos;
}

std::string ADBClient::executeShellAsRoot(const std::string& command) {
    return executeShell("su -c '" + command + "'");
}

bool ADBClient::executeRaw(const std::string& command, std::vector<char>& output) {
    std::string result = executeShell(command);
    output.assign(result.begin(), result.end());
    return !result.empty();
}

bool ADBClient::statFileShell(const std::string& remote_path,
                               uint32_t& mode, uint32_t& size, uint32_t& time) {
    std::string cmd = "stat -c '%a %s %Y' " + remote_path;
    std::string result = executeShell(cmd);

    std::istringstream iss(result);
    iss >> mode >> size >> time;

    return !result.empty();
}

std::vector<ADBClient::SyncEntry> ADBClient::listDirectoryShell(const std::string& path) {
    std::vector<SyncEntry> entries;

    std::string cmd = "ls -la " + path;
    std::string result = executeShell(cmd);

    std::istringstream iss(result);
    std::string line;

    while (std::getline(iss, line)) {
        if (line.empty() || line[0] == 'd' || line[0] == '-') {
            SyncEntry entry;
            std::istringstream line_ss(line);
            line_ss >> entry.permissions >> entry.size;
            // Additional parsing would go here
            entries.push_back(entry);
        }
    }

    return entries;
}

bool ADBClient::pullFileShell(const std::string& remote_path,
                             const std::string& local_path) {
    std::string data = executeShell("cat " + remote_path);

    std::ofstream out(local_path, std::ios::binary);
    if (!out.is_open()) {
        return false;
    }

    out.write(data.data(), data.size());
    out.close();

    return true;
}