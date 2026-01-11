# DatabaseManager

## Overview
The DatabaseManager module is the data backbone of the project. It encapsulates SQLite operations, manages the database schemas (Raw, Events, Files), and provides utilities for data extraction, classification, and retrieval.

## Features
- **Database Management**: Handles connections, transactions, and schema initialization for SQLite databases.
- **File Extraction**: Retrieves raw file content from disk images for analysis (`FileExtractor`).
- **Event Extraction**: Generates a timeline of file system events (created, modified, accessed) into `_events.db` (`EventExtractor`).
- **File Classification**: Categorizes files into 13 distinct types (Images, Documents, Executables, etc.) into `_files.db` (`FileClassifier`).

## Components
- **Core**:
  - `DatabaseManager`: Main class for DB operations and `FileRecord` / `EventRecord` management.
- **Sub-modules**:
  - `EventExtractor`: Processes raw metadata to create timeline events.
  - `FileClassifier`: Sorts files based on extensions and signatures.
  - `FileExtractor`: Interface to read file data from forensic images.

## Usage
Typcial workflow involves initializing the manager and running sub-modules:

```cpp
// Initialize Manager
DatabaseManager dbManager(dbPath);
if (dbManager.initialize()) {
    // ... metadata inserted by ImageAnalyzer ...
    
    // Generate Timeline
    EventExtractor eventExt(dbManager);
    eventExt.extractEvents();
    
    // Classify Files
    FileClassifier classifier(dbManager);
    classifier.classifyFiles();
}
```

## Dependencies
- **SQLite3**: Core storage engine.
- **ImageAnalyzer**: Populates the initial raw metadata (files table).
