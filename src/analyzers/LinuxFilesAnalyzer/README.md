# LinuxFilesAnalyzer

## Overview
This module specializes in the forensic analysis of Linux system artifacts. It extracts key files from forensic images (via `FileExtractor`) and parses them to uncover user activity, system configuration, and security-related information.

## Features
- **Log Analysis**: Parses system logs (syslog, messages, auth.log, kern.log) and application logs (dpkg, apt).
- **User & Authentication**: Analyzes `/etc/passwd`, `/etc/shadow`, login records (`wtmp`, `btmp`, `lastlog`), and SSH keys (`authorized_keys`, `known_hosts`).
- **Shell History**: Extracts command history from Bash, Zsh, and Fish shells.
- **System Configuration**: Parses cron jobs, network configuration, and installed packages.
- **Browser Forensics**: Detects and analyzes web browser profiles (Chrome, Firefox).

## Components
- **Core**:
  - `LinuxFilesAnalyzer`: Main controller for the Linux analysis workflow.
- **Parsers**:
  - Log parsers (`SyslogParser`, `AuthLogParser`, etc.)
  - Configuration parsers (`CronParser`, `NetworkConfigParser`)
  - User data parsers (`ShadowParser`, `ShellHistoryParser`)
- **Database**:
  - `LinuxAnalysisDatabase`: Manages `*_linux.db` for storing analyzed artifacts.

## Usage
Integrated into the main application logic:

```cpp
// Initialize with image path and database manager
LinuxFilesAnalyzer analyzer(imagePath, &dbManager);

if (analyzer.initialize()) {
    // Run full analysis
    analyzer.analyzeLinuxData();
}
```

## Dependencies
- **DatabaseManager**: For file metadata and result storage (`*_linux.db`).
- **FileExtractor**: For retrieving file content from disk images.
- **SQLite3**: For database operations.
