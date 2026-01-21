#pragma once
// adb_client.h
#ifndef ADB_CLIENT_H
#define ADB_CLIENT_H

#include <string>
#include <vector>
#include <cstring>
#include <iostream>
#include <fstream>
#include <cstdint>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
typedef SOCKET socket_t;
#else
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
typedef int socket_t;
#endif

/**
 * @brief Initialize Windows console encoding
 * Sets console code page to UTF-8 for proper Unicode display
 */
void initializeConsoleEncoding();

class ADBClient
{
private:
    socket_t sock;
    std::string host;
    int port;
    bool connected;
    std::string current_serial; // Store selected device serial
    bool in_sync_mode; // Track if currently in sync mode

    /**
     * @brief Initialize socket library (Windows only)
     */
    void initSocket();

    /**
     * @brief Cleanup socket resources
     */
    void cleanupSocket();

    /**
     * @brief Send raw data to the socket
     * @param data The data string to send
     * @return true if sent successfully
     */
    bool sendData(const std::string &data);

    /**
     * @brief Receive data from socket
     * @param length Number of bytes to receive
     * @return Received data as string
     */
    std::string receiveData(int length);

    /**
     * @brief Receive exact number of bytes
     * @param buffer Buffer to store received data
     * @param length Number of bytes to receive
     * @return true if all bytes received successfully
     */
    bool receiveExact(char *buffer, int length);

    /**
     * @brief Send an ADB command
     * Format: 4-byte hex length + command string
     * @param cmd The ADB command to send
     * @return true if sent successfully
     */
    bool sendADBCommand(const std::string &cmd);

    /**
     * @brief Receive ADB command status
     * @return true if status is OKAY
     */
    bool receiveADBStatus();

public:
    ADBClient(const std::string &h = "127.0.0.1", int p = 5037);

    ~ADBClient();

    /**
     * @brief Connect to ADB server
     * @return true if connection successful
     */
    bool connect();

    /**
     * @brief Disconnect from ADB server
     * @return true if disconnected successfully
     */
    bool disconnect();

    /**
     * @brief Get list of connected devices
     * @return Vector of device serial numbers
     */
    std::vector<std::string> getDevices();

    /**
     * @brief Select a target device for subsequent commands
     * @param serial Device serial number
     * @return true if selected successfully
     */
    bool selectDevice(const std::string &serial);

    /**
     * @brief Execute a shell command on the device
     * @param command Shell command to execute
     * @return Command output
     */
    std::string executeShell(const std::string &command);

    /**
     * @brief Establish sync connection for file operations
     * @return true if sync mode established
     */
    bool syncConnect();

    /**
     * @brief Receive a file from the device
     * @param remote_path Source path on device
     * @param local_path Destination path on host
     * @param total_file_size Optional total size for progress tracking
     * @return true if transfer successful
     */
    bool receiveFile(const std::string &remote_path, const std::string &local_path, uint32_t total_file_size = 0);

    struct SyncEntry {
        std::string name;
        uint32_t mode;
        uint32_t size;
        uint32_t time;
    };

    /**
     * @brief List directory contents in sync mode
     * @param path Directory path
     * @return Vector of file entries
     */
    std::vector<SyncEntry> listDirectory(const std::string &path);

    /**
     * @brief Get file statistics in sync mode
     * @param remote_path Path on device
     * @param mode Output file mode
     * @param size Output file size
     * @param time Output file modification time
     * @return true if successful
     */
    bool statFile(const std::string& remote_path, uint32_t& mode, uint32_t& size, uint32_t& time);

    /**
     * @brief Check if root access is available
     * @return true if running as root
     */
    bool checkRootAccess();

    /**
     * @brief Attempt to acquire root privileges
     * @return true if root acquired
     */
    bool acquireRoot();

    /**
     * @brief Execute a shell command with root privileges
     * @param command Command to execute
     * @return Command output
     */
    std::string executeShellAsRoot(const std::string& command);

    // Raw execution (no PTY, useful for binary data)
    bool executeRaw(const std::string& command, std::vector<char>& output);

    // Shell-based fallback methods for Root extraction
    bool statFileShell(const std::string& remote_path, uint32_t& mode, uint32_t& size, uint32_t& time);
    std::vector<SyncEntry> listDirectoryShell(const std::string& path);
    bool pullFileShell(const std::string& remote_path, const std::string& local_path);
    
};

#endif // ADB_CLIENT_H