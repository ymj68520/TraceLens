// ADBClient_Devices.cpp
// Device enumeration and device selection methods

#include "adbClient.h"

std::vector<std::string> ADBClient::getDevices() {
    std::vector<std::string> devices;

    if (socket_fd_ < 0 && !connect()) {
        return devices;
    }

    if (!sendADBCommand("HOST:devices")) {
        return devices;
    }

    if (!receiveADBStatus()) {
        return devices;
    }

    std::string response = receiveData(4096);
    std::istringstream iss(response);
    std::string line;

    while (std::getline(iss, line)) {
        size_t tab_pos = line.find('\t');
        if (tab_pos != std::string::npos) {
            std::string serial = line.substr(0, tab_pos);
            std::string status = line.substr(tab_pos + 1);
            if (status == "device") {
                devices.push_back(serial);
            }
        }
    }

    return devices;
}

bool ADBClient::selectDevice(const std::string &serial) {
    if (serial.empty()) {
        return false;
    }

    current_device_ = serial;

    std::string cmd = "HOST:transport:" + serial;
    if (!sendADBCommand(cmd)) {
        return false;
    }

    if (!receiveADBStatus()) {
        return false;
    }

    // Switch to device
    if (!sendADBCommand("DEV")) {
        return false;
    }

    return receiveADBStatus();
}