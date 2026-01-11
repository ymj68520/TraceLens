#include "adbClient.h"
#include <cstdint>
#include <cstdlib>
#include <sstream>
#include <iostream>
#include <fstream>
#include <iomanip>

#ifdef _WIN32
#include <windows.h>
#include <io.h>
#include <fcntl.h>
#endif

// Initialize Windows console encoding for proper Unicode/Chinese character display
void initializeConsoleEncoding() {
#ifdef _WIN32
    // Set console to UTF-8 encoding
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);

    // Also try to enable virtual terminal processing for ANSI escape codes
    HANDLE hOut = GetStdHandle(STD_OUTPUT_HANDLE);
    if (hOut != INVALID_HANDLE_VALUE) {
        DWORD dwMode = 0;
        if (GetConsoleMode(hOut, &dwMode)) {
            dwMode |= ENABLE_VIRTUAL_TERMINAL_PROCESSING;
            SetConsoleMode(hOut, dwMode);
        }
    }

    // Set stderr to UTF-8 as well
    HANDLE hErr = GetStdHandle(STD_ERROR_HANDLE);
    if (hErr != INVALID_HANDLE_VALUE) {
        DWORD dwMode = 0;
        if (GetConsoleMode(hErr, &dwMode)) {
            dwMode |= ENABLE_VIRTUAL_TERMINAL_PROCESSING;
            SetConsoleMode(hErr, dwMode);
        }
    }
#endif
}

void ADBClient::initSocket()
{
    // Initialize console encoding for Windows
    initializeConsoleEncoding();

    // Socket initialization moved to constructor/connect logic
}

void ADBClient::cleanupSocket()
{
    if (sock != -1)
    {
#ifdef _WIN32
        closesocket(sock);
#else
        close(sock);
#endif
        sock = -1;
    }
}

ADBClient::ADBClient(const std::string &h, int p)
    : host(h), port(p), connected(false), sock(-1), in_sync_mode(false)
{
#ifdef _WIN32
    // Initialize console encoding first
    initializeConsoleEncoding();

    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif
}

ADBClient::~ADBClient()
{
    disconnect();
#ifdef _WIN32
    WSACleanup();
#endif
}

bool ADBClient::sendData(const std::string &data)
{
    int sent = send(sock, data.c_str(), data.length(), 0);
    return sent == (int)data.length();
}

std::string ADBClient::receiveData(int length)
{
    std::vector<char> buffer(length);
    if (!receiveExact(buffer.data(), length))
        return "";
    return std::string(buffer.data(), length);
}

bool ADBClient::receiveExact(char *buffer, int length)
{
    int total = 0;
    while (total < length)
    {
        int received = recv(sock, buffer + total, length - total, 0);
        if (received <= 0)
        {
            return false;
        }
        total += received;
    }
    return true;
}

bool ADBClient::sendADBCommand(const std::string &cmd)
{
    char length[5];
    snprintf(length, sizeof(length), "%04X", (unsigned int)cmd.length());
    std::string full_cmd = std::string(length) + cmd;
    return sendData(full_cmd);
}

bool ADBClient::receiveADBStatus()
{
    char status[5] = {0};
    if (!receiveExact(status, 4))
        return false;

    std::string s(status);
    if (s == "OKAY")
        return true;

    if (s == "FAIL")
    {
        char len_buf[5] = {0};
        if (receiveExact(len_buf, 4))
        {
            unsigned int length = strtoul(len_buf, nullptr, 16);
            std::string error = receiveData(length);
            std::cerr << "ADB Error: " << error << std::endl;
        }
    }
    else
    {
        std::cerr << "ADB Unknown Status: " << s << std::endl;
    }
    return false;
}

bool ADBClient::connect()
{
    sock = socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0)
    {
        std::cerr << "Socket creation failed" << std::endl;
        return false;
    }

    struct sockaddr_in server_addr;
    memset(&server_addr, 0, sizeof(server_addr));
    server_addr.sin_family = AF_INET;
    server_addr.sin_port = htons(port);
    inet_pton(AF_INET, host.c_str(), &server_addr.sin_addr);

    if (::connect(sock, (struct sockaddr *)&server_addr, sizeof(server_addr)) < 0)
    {
        std::cerr << "Connect ADB Server Failed! (" << host << ":" << port << ")" << std::endl;
        std::cerr << "Make sure ADB Server is running: adb start-server" << std::endl;
        cleanupSocket();
        return false;
    }

    connected = true;
    std::cout << "Connected to ADB Server at " << host << ":" << port << std::endl;
    return true;
}

bool ADBClient::disconnect()
{
    if (connected)
    {
        cleanupSocket();
        connected = false;
        in_sync_mode = false;
    }
    return true;
}

std::vector<std::string> ADBClient::getDevices()
{
    std::vector<std::string> devices;
    if (!connected)
        return devices;

    if (!sendADBCommand("host:devices"))
    {
        std::cerr << "Failed to send devices command" << std::endl;
        return devices;
    }

    if (!receiveADBStatus())
    {
        std::cerr << "ADB Server returned error for devices command" << std::endl;
        return devices;
    }

    char length_buf[5] = {0};
    if (!receiveExact(length_buf, 4))
    {
        std::cerr << "Failed to receive devices response length" << std::endl;
        return devices;
    }

    unsigned int length = strtoul(length_buf, nullptr, 16);
    std::string response = receiveData(length);
    if (response.empty())
    {
        std::cerr << "Failed to receive devices response data" << std::endl;
        return devices;
    }
    // Parse device list
    size_t pos = 0;
    while (pos < response.length())
    {
        size_t tab_pos = response.find('\t', pos);
        if (tab_pos == std::string::npos)
            break;

        std::string device_id = response.substr(pos, tab_pos - pos);
        if (!device_id.empty())
        {
            devices.push_back(device_id);
        }

        pos = response.find('\n', tab_pos);
        if (pos == std::string::npos)
            break;
        pos++;
    }

    return devices;
}

bool ADBClient::selectDevice(const std::string &serial)
{
    std::string cmd = "host:transport:" + serial;
    if (!sendADBCommand(cmd))
        return false;
    if (receiveADBStatus()) {
        current_serial = serial;
        return true;
    }
    return false;
}

std::string ADBClient::executeShell(const std::string &command)
{
    if (!connected && !current_serial.empty()) {
        connect();
        selectDevice(current_serial);
    }
    
    in_sync_mode = false; // Shell invalidates sync mode
    std::string cmd = "shell:" + command;
    if (!sendADBCommand(cmd))
    {
        std::cerr << "Failed to send shell command" << std::endl;
        disconnect();
        return "";
    }
    if (!receiveADBStatus()) {
        disconnect();
        return "";
    }

    std::string result;
    char buffer[4096];
    int received;

    while ((received = recv(sock, buffer, sizeof buffer, 0)) > 0)
    {
        result.append(buffer, received);
    }
    disconnect(); // Shell command consumes connection
    return result;
}

bool ADBClient::syncConnect()
{
    if (!connected && !current_serial.empty()) {
        connect();
        selectDevice(current_serial);
    }

    if (!sendADBCommand("sync:"))
        return false;
    if (receiveADBStatus()) {
        in_sync_mode = true;
        return true;
    }
    return false;
}

bool ADBClient::receiveFile(const std::string &remote_path, const std::string &local_path, uint32_t total_file_size)
{
    if (!connected || !in_sync_mode) {
        if (!current_serial.empty()) {
            disconnect();
            if(!connect()) return false;
            if(!selectDevice(current_serial)) return false;
            if(!syncConnect()) return false;
        } else {
            return false;
        }
    }

    // Send STAT command to check file
    std::string stat_cmd = "STAT";
    stat_cmd += std::string(4, '\0'); // Placeholder for length
    uint32_t path_len = remote_path.length();
    stat_cmd[4] = (path_len >> 0) & 0xFF;
    stat_cmd[5] = (path_len >> 8) & 0xFF;
    stat_cmd[6] = (path_len >> 16) & 0xFF;
    stat_cmd[7] = (path_len >> 24) & 0xFF;
    stat_cmd += remote_path;

    if (!sendData(stat_cmd))
    {
        std::cerr << "Failed to send STAT command" << std::endl;
        return false;
    }

    char response[16];
    if (!receiveExact(response, 16))
        return false;

    if (std::string(response, 4) != "STAT")
    {
        std::cerr << "File not found on device: " << remote_path << std::endl;
        return false;
    }

    // Send RECV command to receive file
    std::string recv_cmd = "RECV";
    recv_cmd += std::string(4, '\0'); // Placeholder for length
    recv_cmd[4] = (path_len >> 0) & 0xFF;
    recv_cmd[5] = (path_len >> 8) & 0xFF;
    recv_cmd[6] = (path_len >> 16) & 0xFF;
    recv_cmd[7] = (path_len >> 24) & 0xFF;
    recv_cmd += remote_path;

    if (!sendData(recv_cmd))
    {
        std::cerr << "Failed to send RECV command" << std::endl;
        return false;
    }

    // Receive data
    std::ofstream outfile(local_path, std::ios::binary);
    if (!outfile.is_open())
    {
        std::cerr << "Failed to open local file for writing: " << local_path << std::endl;
        return false;
    }

    uint64_t total_received_bytes = 0; // Use uint64_t for large files

    while (true)
    {
        char chunk_header[8];
        if (!receiveExact(chunk_header, 8))
        {
            std::cerr << "Failed to receive chunk header" << std::endl;
            break;
        }

        std::string chunk_id(chunk_header, 4);
        uint32_t chunk_size = *(uint32_t *)(chunk_header + 4);
        if (chunk_id == "DONE")
            break;
        if (chunk_id == "FAIL")
        {
            std::cerr << "File transfer failed from device" << std::endl;
            outfile.close();
            return false;
        }
        if (chunk_id == "DATA")
        {
            std::vector<char> data(chunk_size);
            if (!receiveExact(data.data(), chunk_size))
            {
                std::cerr << "Failed to receive data chunk" << std::endl;
                break;
            }
            outfile.write(data.data(), chunk_size);
            total_received_bytes += chunk_size;

            if (total_file_size > 0)
            {
                int progress = (total_received_bytes * 100) / total_file_size;
                std::cout << "\rReceiving: " << remote_path << " - " << progress << "% ("
                          << total_received_bytes << "/" << total_file_size << " bytes)";
                std::cout.flush();
            }
        }
    }
    outfile.close();

    if (total_file_size > 0)
    {
        std::cout << std::endl; // New line after progress bar
    }
    return true;
}

bool ADBClient::statFile(const std::string &remote_path, uint32_t &mode, uint32_t &size, uint32_t &time)
{
    if (!connected || !in_sync_mode) {
        if (!current_serial.empty()) {
            disconnect();
            if(!connect()) return false;
            if(!selectDevice(current_serial)) return false;
            if(!syncConnect()) return false;
        } else {
            return false;
        }
    }

    char len_buf[4];
    uint32_t len = remote_path.length();
    len_buf[0] = (len >> 0) & 0xFF;
    len_buf[1] = (len >> 8) & 0xFF;
    len_buf[2] = (len >> 16) & 0xFF;
    len_buf[3] = (len >> 24) & 0xFF;

    std::string msg = "STAT" + std::string(len_buf, 4) + remote_path;

    if (!sendData(msg))
        return false;

    char header[4];
    if (!receiveExact(header, 4))
        return false;
    if (std::string(header, 4) != "STAT")
        return false;

    char stat_data[12];
    if (!receiveExact(stat_data, 12))
        return false;

    mode = *(uint32_t *)(stat_data);
    size = *(uint32_t *)(stat_data + 4);
    time = *(uint32_t *)(stat_data + 8);

    return true;
}

std::vector<ADBClient::SyncEntry> ADBClient::listDirectory(const std::string &path)
{
    std::vector<SyncEntry> entries;

    if (!connected || !in_sync_mode) {
        if (!current_serial.empty()) {
            disconnect();
            if(!connect()) ; // error handling? returns empty entries
            if(!selectDevice(current_serial)) ;
            if(!syncConnect()) ;
        }
        if (!connected || !in_sync_mode) return entries;
    }

    char len_buf[4];
    uint32_t len = path.length();
    len_buf[0] = (len >> 0) & 0xFF;
    len_buf[1] = (len >> 8) & 0xFF;
    len_buf[2] = (len >> 16) & 0xFF;
    len_buf[3] = (len >> 24) & 0xFF;

    std::string msg = "LIST" + std::string(len_buf, 4) + path;
    if (!sendData(msg))
        return entries;

    while (true)
    {
        char header[4];
        if (!receiveExact(header, 4))
            break;
        std::string id(header, 4);

        if (id == "DONE")
            break;
        if (id == "FAIL")
        {
            char len_buf[4];
            if (receiveExact(len_buf, 4))
            {
                uint32_t len = *(uint32_t *)len_buf;
                receiveData(len); // Consume error message
            }
            break;
        }
        if (id != "DENT")
            break;

        char stat_data[16];
        if (!receiveExact(stat_data, 16))
            break;

        SyncEntry entry;
        entry.mode = *(uint32_t *)(stat_data);
        entry.size = *(uint32_t *)(stat_data + 4);
        entry.time = *(uint32_t *)(stat_data + 8);
        uint32_t name_len = *(uint32_t *)(stat_data + 12);

        if (name_len > 0)
        {
            std::vector<char> name_buf(name_len);
            if (!receiveExact(name_buf.data(), name_len))
                break;
            entry.name = std::string(name_buf.data(), name_len);
            entries.push_back(entry);
        }
    }
    return entries;
}

bool ADBClient::checkRootAccess()
{
    std::string result = executeShell("id");
    return (result.find("uid=0") != std::string::npos);
}

bool ADBClient::acquireRoot()
{
    std::cout << "Attempting to acquire root..." << std::endl;

    if (!connected && !current_serial.empty()) {
        connect();
        selectDevice(current_serial);
    }

    if (!sendADBCommand("root:"))
    {
        std::cout << "  Failed to send root command" << std::endl;
        disconnect(); // Reset on failure
    }
    else
    {
        if (receiveADBStatus()) {
            std::cout << "  Sent root command, waiting for device restart..." << std::endl;
            disconnect();
#ifdef _WIN32
            Sleep(3000);
#else
            sleep(3);
#endif
            if (connect()) {
                if (!current_serial.empty()) selectDevice(current_serial);
                // Check id
                std::string result = executeShell("id"); 
                // executeShell will disconnect at end!
                if (result.find("uid=0") != std::string::npos) {
                    std::cout << "[OK] Root access acquired (via adb root)" << std::endl;
                    return true;
                }
            }
        } else {
             std::cout << "  'adb root' failed (likely production build)" << std::endl;
             disconnect(); // Reset
        }
    }

    // Method 2: su command
    std::string su_test = executeShell("su -c 'id'");
    if (su_test.find("uid=0") != std::string::npos)
    {
        std::cout << "[OK] su available" << std::endl;
        return true;
    }

    // Method 3: su version 2
    su_test = executeShell("su 0 id");
    if (su_test.find("uid=0") != std::string::npos)
    {
        std::cout << "[OK] su (ver 2) available" << std::endl;
        return true;
    }

    std::cout << "[FAIL] Failed to acquire root" << std::endl;
    return false;
}



std::string ADBClient::executeShellAsRoot(const std::string& command) {
        // 先尝试直接执行（如果已经是root）
        std::string direct_result = executeShell("id");
        if (direct_result.find("uid=0") != std::string::npos) {
            return executeShell(command);
        }
        
        // 尝试使用su
        std::string su_result = executeShell("su -c '" + command + "'");
        if (!su_result.empty() && su_result.find("not found") == std::string::npos) {
            return su_result;
        }
        
        // 尝试su的另一种形式
        su_result = executeShell("su 0 " + command);
        if (!su_result.empty() && su_result.find("not found") == std::string::npos) {
            return su_result;
        }
        
        // 都失败了，返回普通执行结果
        return executeShell(command);
    }

bool ADBClient::executeRaw(const std::string& command, std::vector<char>& output) {
    if (!connected && !current_serial.empty()) {
        connect();
        selectDevice(current_serial);
    }
    
    in_sync_mode = false;
    std::string cmd = "exec:" + command;
    if (!sendADBCommand(cmd)) { disconnect(); return false; }
    if (!receiveADBStatus()) { disconnect(); return false; }

    char buffer[4096];
    int received;
    output.clear();
    while ((received = recv(sock, buffer, sizeof buffer, 0)) > 0) {
        output.insert(output.end(), buffer, buffer + received);
    }
    disconnect();
    return true;
}

// ... statFileShell ... listDirectoryShell ... pullFileShell ... (which call executeShellAsRoot -> executeShell)
// They rely on executeShell handling connection, which it now does.



bool ADBClient::statFileShell(const std::string& remote_path, uint32_t& mode, uint32_t& size, uint32_t& time) {
    // Try using 'stat' command (toybox/busybox)
    // Format: %f (hex raw mode), %s (size), %Y (time)
    std::string cmd = "stat -c '%f %s %Y' " + remote_path;
    std::string result = executeShellAsRoot(cmd);
    
    // Check for error
    if (result.empty() || result.find("No such file") != std::string::npos || result.find("stat:") != std::string::npos) {
        // Fallback: simple existence check for directory? 
        // Parsing ls -l is harder for exact mode. 
        // Let's assume failure for now if stat is missing, 
        // but most rooted devices have stat.
        return false;
    }

    uint32_t raw_mode = 0;
    unsigned long long raw_size = 0;
    unsigned long long raw_time = 0;
    
    if (sscanf(result.c_str(), "%x %llu %llu", &raw_mode, &raw_size, &raw_time) == 3) {
        mode = raw_mode;
        size = (uint32_t)raw_size;
        time = (uint32_t)raw_time;
        return true;
    }
    return false;
}

std::vector<ADBClient::SyncEntry> ADBClient::listDirectoryShell(const std::string& path) {
    std::vector<SyncEntry> entries;
    // ls -ln: numeric uid/gid. 
    // Format usually: mode links uid gid size date time name
    // Android toybox ls -ln:
    // drwxrwx--x 3 1000 1000 4096 2023-01-01 12:00 name
    
    std::string cmd = "ls -ln " + path;
    std::string result = executeShellAsRoot(cmd);
    
    std::istringstream stream(result);
    std::string line;
    while (std::getline(stream, line)) {
        if (line.empty() || line.find("total ") == 0) continue;
        
        char permissions[11];
        int links;
        int uid, gid;
        unsigned long long size;
        std::string date, time_str, name;
        
        // Simple heuristic parser. 
        // Note: Date/Time parsing varies (year vs time). We'll set time to 0 for simplicity or implement complex parsing.
        // We mainly need Name, Mode (dir vs file), Size.
        
        std::stringstream ss(line);
        std::string perm_str;
        ss >> perm_str;
        
        if (perm_str.length() != 10) continue; // Invalid line

        SyncEntry entry;
        entry.size = 0;
        entry.time = 0;
        entry.mode = 0;
        
        // Parse type
        if (perm_str[0] == 'd') entry.mode |= 0x4000; // S_IFDIR
        else if (perm_str[0] == '-') entry.mode |= 0x8000; // S_IFREG
        else continue; // Skip links/sockets for now
        
        // Skip links, uid, gid
        std::string dummy;
        ss >> dummy >> dummy >> dummy; // links, uid, gid
        
        ss >> entry.size;
        ss >> dummy >> dummy; // date, time
        
        // Read remaining as name (can contain spaces)
        std::string part;
        std::string full_name = "";
        while (ss >> part) {
            if (!full_name.empty()) full_name += " ";
            full_name += part;
        }
        entry.name = full_name;
        
        if (!entry.name.empty() && entry.name != "." && entry.name != "..") {
             entries.push_back(entry);
        }
    }
    return entries;
}

bool ADBClient::pullFileShell(const std::string& remote_path, const std::string& local_path) {
    // Attempt to pull using 'cat' via 'exec' service (no PTY, binary safe-ish)
    // Command: su -c 'cat "path"'
    // Note: quoting path is important.
    
    std::string cmd;
    // Check if we need su
    std::string id = executeShell("id");
    if (id.find("uid=0") != std::string::npos) {
        cmd = "cat \"" + remote_path + "\"";
    } else {
        // Try su
        // Note: exec:su -c ... works on some devices, fails on others.
        // fallback to shell:su ... but that has PTY issues (CRLF).
        // Let's try exec:su first.
        cmd = "su -c 'cat \"" + remote_path + "\"'";
    }
    
    std::vector<char> data;
    if (!executeRaw(cmd, data)) {
        std::cerr << "Failed to pull file via shell: " << remote_path << std::endl;
        return false;
    }
    
    if (data.empty()) {
        // Empty file or error. Check if file exists?
        // Assume empty file is fine if stat succeeded before.
    }
    
    std::ofstream outfile(local_path, std::ios::binary);
    if (!outfile.is_open()) return false;
    
    outfile.write(data.data(), data.size());
    outfile.close();
    
    return true;
}
