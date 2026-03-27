// ADBClient_Init.cpp
// ADB client initialization and connection methods

#include "adbClient.h"
#include <algorithm>

void initializeConsoleEncoding() {
    // Console encoding initialization - empty on non-Windows
}

void ADBClient::initSocket() {
    socket_fd_ = socket(AF_INET, SOCK_STREAM, 0);
    if (socket_fd_ < 0) {
        std::cerr << "Failed to create socket" << std::endl;
        return;
    }

    int yes = 1;
    setsockopt(socket_fd_, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
    fcntl(socket_fd_, F_SETFL, O_NONBLOCK);
}

void ADBClient::cleanupSocket() {
    if (socket_fd_ >= 0) {
        close(socket_fd_);
        socket_fd_ = -1;
    }
}

bool ADBClient::sendData(const std::string &data) {
    if (socket_fd_ < 0) return false;

    ssize_t sent = send(socket_fd_, data.c_str(), data.length(), 0);
    return sent == static_cast<ssize_t>(data.length());
}

std::string ADBClient::receiveData(int length) {
    if (socket_fd_ < 0) return "";

    std::vector<char> buffer(length);
    std::string result;

    fd_set read_fds;
    FD_ZERO(&read_fds);
    FD_SET(socket_fd_, &read_fds);

    struct timeval timeout;
    timeout.tv_sec = 30;
    timeout.tv_usec = 0;

    int ret = select(socket_fd_ + 1, &read_fds, NULL, NULL, &timeout);
    if (ret > 0) {
        ssize_t received = recv(socket_fd_, buffer.data(), length, 0);
        if (received > 0) {
            result.assign(buffer.data(), received);
        }
    }

    return result;
}

bool ADBClient::receiveExact(char *buffer, int length) {
    int received = 0;
    while (received < length) {
        ssize_t r = recv(socket_fd_, buffer + received, length - received, 0);
        if (r <= 0) return false;
        received += r;
    }
    return true;
}

bool ADBClient::sendADBCommand(const std::string &cmd) {
    std::string message = cmd;
    message += "\0";

    uint32_t length = htonl(message.length());
    if (!sendData(std::string(reinterpret_cast<char*>(&length), 4))) return false;

    return sendData(message);
}

bool ADBClient::receiveADBStatus() {
    char status[4];
    if (!receiveExact(status, 4)) return false;
    return std::string(status, 4) == "OKAY";
}

bool ADBClient::connect() {
    if (socket_fd_ >= 0) {
        cleanupSocket();
    }

    initSocket();

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(5037);
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");

    if (connect(socket_fd_, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        std::cerr << "Failed to connect to ADB server" << std::endl;
        return false;
    }

    // Send AUTH
    if (!sendADBCommand("HOST")) {
        return false;
    }

    // Wait for OKAY
    return receiveADBStatus();
}

bool ADBClient::disconnect() {
    if (socket_fd_ >= 0) {
        sendADBCommand("QUIT");
        cleanupSocket();
    }
    return true;
}