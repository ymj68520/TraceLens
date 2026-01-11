# AndroidAdbExtractor

## Overview
The AndroidAdbExtractor module provides functionality to interact with Android devices via the Android Debug Bridge (ADB). It allows for file extraction, device information retrieval, and logical data acquisition.

## Features
- **ADB Connection**: Connects to the local ADB server.
- **Device Management**: Lists connected devices and retrieves their status.
- **File Pulling**: Extracts specific files or directories from the device to the local system.
- **Shell Execution**: Executes shell commands on the device for data gathering.

## Components
- **Core**:
  - `adbClient`: Handles low-level socket communication with the ADB server.
  - `adbExtractor`: High-level interface for extraction workflows.

## Usage
Can be used to extract specific artifacts before analysis:

```cpp
adbClient client;
if (client.connect()) {
    client.pullFile("/data/system/packages.xml", "./output/packages.xml");
}
```

## Dependencies
- **ADB Binary**: Requires `adb` to be installed and running on the host system.
- **Boost.Asio**: For socket communication.
