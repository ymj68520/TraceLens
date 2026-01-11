# WindowsFilesAnalyzer

## Overview
This module specializes in the forensic analysis of Windows system artifacts. It extracts key files from forensic images (via `FileExtractor`) and parses them to uncover user activity, system configuration, and application usage history.

## Features
- **Registry Analysis**: Extracts and parses SAM, SYSTEM, SOFTWARE, and NTUSER.DAT hives for user accounts, USB history, and system services.
- **Event Log Analysis**: Parses Windows Event Logs (`.evtx`) including Security, System, and Application logs.
- **Artifact Analysis**: 
  - **Prefetch & Shimcache**: Tracks application execution.
  - **LNK & Jump Lists**: Identifies accessed files and folder history.
  - **Recycle Bin**: Recovers deleted file metadata.
  - **Browser History**: Analyzes web browsing activity.

## Components
- **Core**:
  - `WindowsFilesAnalyzer`: Main class coordinating the analysis process.
- **Parsers**:
  - `WindowsRegistryParser`: Handles Hive file parsing.
  - `WindowsEventLogParser`: Processes EVTX files.
  - `WindowsArtifactsParsers`: Manages Prefetch, LNK, and other artifact parsing.
- **Database**:
  - `WindowsAnalysisDatabase`: Manages the SQLite storage for parsed Windows artifacts.

## Usage
The module is integrated into the main `ForensicAnalyzer` application.

```cpp
// Initialize with image path and database manager
WindowsFilesAnalyzer analyzer(imagePath, &dbManager);

if (analyzer.initialize()) {
    // Execute full analysis workflow
    analyzer.analyzeWindowsData();
}
```

## Dependencies
- **DatabaseManager**: For file metadata and result storage (`*_windows.db`).
- **FileExtractor**: For retrieving file content from disk images.
- **Third-party Libraries**: 
  - `libhivex`: For Registry parsing.
  - `libevtx`: For Event Log parsing.
  - `libolecf`: For OLE Compound File (LNK/JumpList) parsing.
  - `SQLite3`: For database operations.
