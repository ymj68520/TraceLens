# AndroidAnalyzer

## Overview
This module analyzes Android forensic images and backups to extract both user data (communications, browsing history) and system information (configuration, installed apps).

## Features
- **User Data Analysis**:
  - **Communications**: SMS/MMS (`mmssms.db`), Contacts (`contacts2.db`), Call Logs (`calllog.db`), WhatsApp (`msgstore.db`).
  - **Browsing**: Chrome History and Bookmarks.
  - **Connectivity**: WiFi configurations (`WifiConfigStore.xml`, `wpa_supplicant.conf`).
- **System Analysis**:
  - **Configuration**: Parses `build.prop` for device details.
  - **Applications**: Lists installed packages (`packages.xml`) and system apps (`/system/app`).
  - **Framework**: Analyzes framework files.

## Components
- **Core**:
  - `AndroidAnalyzer`: Main class for Android artifact analysis.
- **Parsers**:
  - `AndroidDataParsers`: Handles user data databases (SMS, Contacts, WhatsApp).
  - `AndroidSystemParsers`: Processes system applications and framework files.
  - `BuildPropAnalyzer`: Parses `build.prop` configuration.
- **Database**:
  - `AndroidAnalysisDatabase`: Manages `*_android.db` for storing results.

## Usage
Integrated into the main application:

```cpp
// Initialize analyzer
AndroidAnalyzer analyzer(imagePath, &dbManager);

if (analyzer.initialize()) {
    // Run full analysis
    analyzer.analyzeAndroidData();
}
```

## Dependencies
- **DatabaseManager**: For file metadata and result storage (`*_android.db`).
- **FileExtractor**: For retrieving file content from disk images.
- **SQLite3**: For database operations.