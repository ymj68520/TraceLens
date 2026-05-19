// USBMountParser.h
// USB device events, mount entries, and desktop login log parsing

#pragma once
#ifndef USB_MOUNT_PARSER_H
#define USB_MOUNT_PARSER_H

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

#include <string>
#include <vector>
#include <cstdint>
#include "LinuxDataTypes.h"

namespace forensics {
namespace linux {

struct USBEvent {
    int64_t timestamp = 0;
    std::string eventType;      // CONNECT, DISCONNECT, MOUNT, UNMOUNT
    std::string vendorId;
    std::string productId;
    std::string serialNumber;
    std::string manufacturer;
    std::string product;
    std::string devicePath;
    std::string mountPoint;
    std::string filesystem;
    int64_t capacityBytes = 0;
    std::string kernelDevice;   // e.g., sdb1
    EvidenceProvenance provenance;
    NormalizedTimestamp normalizedTime;
};

struct MountEntry {
    int64_t timestamp = 0;
    std::string device;
    std::string mountPoint;
    std::string filesystem;
    std::string mountOptions;
    int64_t totalBytes = 0;
    int64_t usedBytes = 0;
    int64_t availableBytes = 0;
    bool isExternal = false;
    bool isNetwork = false;
    EvidenceProvenance provenance;
    NormalizedTimestamp normalizedTime;
};

struct DesktopLoginEvent {
    int64_t timestamp = 0;
    std::string displayManager; // lightdm, gdm, sddm, kdm
    std::string username;
    std::string session;
    std::string eventType;      // LOGIN, LOGOUT, SESSION_START, SESSION_END
    std::string display;        // :0, :1
    std::string remoteHost;
    EvidenceProvenance provenance;
    NormalizedTimestamp normalizedTime;
};

class USBMountParser {
public:
    // Parse USB events from kernel/syslog/journal logs
    static std::vector<USBEvent> parseUSBEvents(
        const std::vector<std::string>& logLines,
        const std::string& sourceFile);

    // Parse fstab file
    static std::vector<MountEntry> parseFstab(
        const std::string& content,
        const std::string& filePath);

    // Parse systemd mount units
    static std::vector<MountEntry> parseSystemdMounts(
        const std::string& content,
        const std::string& filePath);

    // Parse mount command output
    static std::vector<MountEntry> parseMountOutput(
        const std::string& content,
        const std::string& filePath);

    // Parse desktop login logs (lightdm, gdm)
    static std::vector<DesktopLoginEvent> parseDesktopLoginLogs(
        const std::vector<std::string>& logLines,
        const std::string& displayManager,
        const std::string& sourceFile);

    // Extract USB VID/PID from log line
    static bool extractUSBIds(const std::string& line,
                              std::string& vendorId,
                              std::string& productId);

private:
    static USBEvent parseUSBEventLine(const std::string& line,
                                      const std::string& sourceFile);
    static MountEntry parseFstabLine(const std::string& line,
                                     const std::string& filePath);
};

} // namespace linux
} // namespace forensics

#endif // USB_MOUNT_PARSER_H
