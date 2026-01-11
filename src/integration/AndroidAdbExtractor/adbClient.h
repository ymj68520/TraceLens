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

// Initialize Windows console encoding for proper Unicode/Chinese character display
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

    // 初始化socket库（Windows only）
    void initSocket();

    // 清理socket
    void cleanupSocket();

    // 发送数据
    bool sendData(const std::string &data);

    // 接收数据
    std::string receiveData(int length);

    // 接收固定长度数据
    bool receiveExact(char *buffer, int length);

    // 发送ADB命令格式：4字节长度（hex）+ 命令
    bool sendADBCommand(const std::string &cmd);

    // 接收abd响应状态
    bool receiveADBStatus();

public:
    ADBClient(const std::string &h = "127.0.0.1", int p = 5037);

    ~ADBClient();

    // 连接ABD服务器
    bool connect();

    // 断开连接
    bool disconnect();

    // 获取设备列表
    std::vector<std::string> getDevices();

    // 选择设备（用于后续命令）
    bool selectDevice(const std::string &serial);

    // 执行shell命令
    std::string executeShell(const std::string &command);

    // 同步连接(传输文件)
    bool syncConnect();

    // 接收文件
    bool receiveFile(const std::string &remote_path, const std::string &local_path, uint32_t total_file_size = 0);

    struct SyncEntry {
        std::string name;
        uint32_t mode;
        uint32_t size;
        uint32_t time;
    };

    // 列出目录 (Sync mode)
    std::vector<SyncEntry> listDirectory(const std::string &path);

    // 获取文件信息 (Sync mode)
    bool statFile(const std::string& remote_path, uint32_t& mode, uint32_t& size, uint32_t& time);

    // 检查是否有root权限
    bool checkRootAccess();

    // 尝试获取root权限
    bool acquireRoot();

    // 使用root权限执行命令
    std::string executeShellAsRoot(const std::string& command);

    // Raw execution (no PTY, useful for binary data)
    bool executeRaw(const std::string& command, std::vector<char>& output);

    // Shell-based fallback methods for Root extraction
    bool statFileShell(const std::string& remote_path, uint32_t& mode, uint32_t& size, uint32_t& time);
    std::vector<SyncEntry> listDirectoryShell(const std::string& path);
    bool pullFileShell(const std::string& remote_path, const std::string& local_path);
    
};

#endif // ADB_CLIENT_H