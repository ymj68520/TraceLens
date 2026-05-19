// USBMountParser.cpp
// USB device events, mount entries, and desktop login log parsing

#include "USBMountParser.h"
#include "TimestampNormalizer.h"
#include <sstream>
#include <regex>
#include <algorithm>

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// ============================================================================
// USB Event Parsing
// ============================================================================

std::vector<USBEvent> USBMountParser::parseUSBEvents(
    const std::vector<std::string>& logLines,
    const std::string& sourceFile) {

    std::vector<USBEvent> events;
    for (const auto& line : logLines) {
        if (line.find("usb") == std::string::npos &&
            line.find("USB") == std::string::npos &&
            line.find("New USB") == std::string::npos &&
            line.find("Product:") == std::string::npos &&
            line.find("Manufacturer:") == std::string::npos) {
            continue;
        }
        auto event = parseUSBEventLine(line, sourceFile);
        if (!event.devicePath.empty() || !event.vendorId.empty()) {
            events.push_back(std::move(event));
        }
    }
    return events;
}

USBEvent USBMountParser::parseUSBEventLine(const std::string& line,
                                            const std::string& sourceFile) {
    USBEvent event;
    event.provenance.parserName = "USBMountParser";
    event.provenance.parserVersion = "1.0";
    event.provenance.sourceFile = sourceFile;

    // Extract VID/PID: "ID vendorid:productid"
    std::regex vidPidRegex(R"(ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4}))");
    std::smatch match;
    if (std::regex_search(line, match, vidPidRegex)) {
        event.vendorId = match[1].str();
        event.productId = match[2].str();
    }

    // Extract kernel device: "sd[a-z][0-9]*"
    std::regex devRegex(R"(sd[a-z][0-9]*)");
    if (std::regex_search(line, match, devRegex)) {
        event.kernelDevice = match[0].str();
        event.devicePath = "/dev/" + event.kernelDevice;
    }

    // Detect event type
    if (line.find("new high-speed") != std::string::npos ||
        line.find("new SuperSpeed") != std::string::npos ||
        line.find("new full-speed") != std::string::npos ||
        line.find("New USB device") != std::string::npos) {
        event.eventType = "CONNECT";
    } else if (line.find("USB disconnect") != std::string::npos) {
        event.eventType = "DISCONNECT";
    } else if (line.find("mounted") != std::string::npos) {
        event.eventType = "MOUNT";
    } else if (line.find("unmounted") != std::string::npos) {
        event.eventType = "UNMOUNT";
    }

    // Extract product/manufacturer strings
    std::regex productRegex(R"(Product:\s*(.+))");
    if (std::regex_search(line, match, productRegex)) {
        event.product = match[1].str();
    }
    std::regex mfgRegex(R"(Manufacturer:\s*(.+))");
    if (std::regex_search(line, match, mfgRegex)) {
        event.manufacturer = match[1].str();
    }

    // Extract serial number
    std::regex serialRegex(R"(SerialNumber:\s*(\S+))");
    if (std::regex_search(line, match, serialRegex)) {
        event.serialNumber = match[1].str();
    }

    event.provenance.rawRecord = line;
    return event;
}

bool USBMountParser::extractUSBIds(const std::string& line,
                                    std::string& vendorId,
                                    std::string& productId) {
    std::regex vidPidRegex(R"(ID\s+([0-9a-fA-F]{4}):([0-9a-fA-F]{4}))");
    std::smatch match;
    if (std::regex_search(line, match, vidPidRegex)) {
        vendorId = match[1].str();
        productId = match[2].str();
        return true;
    }
    return false;
}

// ============================================================================
// Mount Entry Parsing
// ============================================================================

std::vector<MountEntry> USBMountParser::parseFstab(
    const std::string& content,
    const std::string& filePath) {

    std::vector<MountEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        // Skip comments and empty lines
        if (line.empty() || line[0] == '#') continue;

        auto entry = parseFstabLine(line, filePath);
        if (!entry.device.empty()) {
            entries.push_back(std::move(entry));
        }
    }
    return entries;
}

MountEntry USBMountParser::parseFstabLine(const std::string& line,
                                           const std::string& filePath) {
    MountEntry entry;
    entry.provenance.parserName = "USBMountParser";
    entry.provenance.parserVersion = "1.0";
    entry.provenance.sourceFile = filePath;

    std::istringstream stream(line);
    std::string device, mountPoint, fsType, options, dump, pass;

    if (!(stream >> device >> mountPoint >> fsType >> options >> dump >> pass)) {
        return entry;
    }

    entry.device = device;
    entry.mountPoint = mountPoint;
    entry.filesystem = fsType;
    entry.mountOptions = options;

    // Detect external/network mounts
    if (device.find("/dev/sd") != std::string::npos ||
        device.find("/dev/hd") != std::string::npos ||
        device.find("UUID=") != std::string::npos) {
        entry.isExternal = true;
    }
    if (fsType == "nfs" || fsType == "cifs" || fsType == "smbfs" ||
        fsType == "sshfs" || fsType == "fuse.sshfs") {
        entry.isNetwork = true;
    }

    entry.provenance.rawRecord = line;
    return entry;
}

std::vector<MountEntry> USBMountParser::parseSystemdMounts(
    const std::string& content,
    const std::string& filePath) {

    std::vector<MountEntry> entries;
    // Basic systemd mount unit parsing
    MountEntry entry;
    entry.provenance.parserName = "USBMountParser";
    entry.provenance.parserVersion = "1.0";
    entry.provenance.sourceFile = filePath;
    entry.provenance.rawRecord = content;

    std::regex whatRegex(R"(What=(.+))");
    std::regex whereRegex(R"(Where=(.+))");
    std::regex typeRegex(R"(Type=(.+))");
    std::regex optionsRegex(R"(Options=(.+))");
    std::smatch match;

    if (std::regex_search(content, match, whatRegex)) entry.device = match[1].str();
    if (std::regex_search(content, match, whereRegex)) entry.mountPoint = match[1].str();
    if (std::regex_search(content, match, typeRegex)) entry.filesystem = match[1].str();
    if (std::regex_search(content, match, optionsRegex)) entry.mountOptions = match[1].str();

    if (!entry.device.empty() && !entry.mountPoint.empty()) {
        entries.push_back(std::move(entry));
    }
    return entries;
}

std::vector<MountEntry> USBMountParser::parseMountOutput(
    const std::string& content,
    const std::string& filePath) {

    std::vector<MountEntry> entries;
    std::istringstream stream(content);
    std::string line;

    // Format: "device on mountpoint type fstype (options)"
    std::regex mountRegex(R"((\S+)\s+on\s+(\S+)\s+type\s+(\S+)\s+\(([^)]*)\))");

    while (std::getline(stream, line)) {
        std::smatch match;
        if (std::regex_search(line, match, mountRegex)) {
            MountEntry entry;
            entry.provenance.parserName = "USBMountParser";
            entry.provenance.parserVersion = "1.0";
            entry.provenance.sourceFile = filePath;
            entry.device = match[1].str();
            entry.mountPoint = match[2].str();
            entry.filesystem = match[3].str();
            entry.mountOptions = match[4].str();
            entry.provenance.rawRecord = line;
            entries.push_back(std::move(entry));
        }
    }
    return entries;
}

// ============================================================================
// Desktop Login Log Parsing
// ============================================================================

std::vector<DesktopLoginEvent> USBMountParser::parseDesktopLoginLogs(
    const std::vector<std::string>& logLines,
    const std::string& displayManager,
    const std::string& sourceFile) {

    std::vector<DesktopLoginEvent> events;

    for (const auto& line : logLines) {
        DesktopLoginEvent event;
        event.provenance.parserName = "USBMountParser";
        event.provenance.parserVersion = "1.0";
        event.provenance.sourceFile = sourceFile;
        event.displayManager = displayManager;

        // LightDM: "session opened for user username"
        // GDM: "session opened for user username"
        std::regex sessionOpenRegex(R"(session opened for user (\S+))");
        std::regex sessionCloseRegex(R"(session closed for user (\S+))");
        std::smatch match;

        if (std::regex_search(line, match, sessionOpenRegex)) {
            event.username = match[1].str();
            event.eventType = "SESSION_START";
        } else if (std::regex_search(line, match, sessionCloseRegex)) {
            event.username = match[1].str();
            event.eventType = "SESSION_END";
        } else {
            continue;
        }

        // Extract display :0, :1 etc
        std::regex displayRegex(R"((:\d+))");
        if (std::regex_search(line, match, displayRegex)) {
            event.display = match[1].str();
        }

        event.provenance.rawRecord = line;
        events.push_back(std::move(event));
    }
    return events;
}

} // namespace linux
} // namespace forensics
