# ImageAnalyzer

## Overview
The ImageAnalyzer module handles the low-level processing of forensic disk images. It opens images, detects partitions and file systems, traverses directories, and extracts file metadata into the raw database.

## Features
- **Image Support**: Reads raw (DD) and EnCase (E01) images.
- **Filesystem Support**: Analyzes NTFS, FAT, EXT2/3/4, and XFS.
- **XFS Fallback**: Provides alternative parsing strategies for XFS when TSK fails:
  - **Native**: Uses system mount (Linux only, requires root).
  - **Pure**: Custom XFS structure parsing.
- **Metadata Extraction**: Captures MAC times, permissions, file type, and size.

## Components
- **Core**:
  - `ImageAnalyzer`: Main interface for image and filesystem operations.
- **Helpers**:
  - `XFSHelper`: Implements custom XFS parsing logic.
  - `NativeFilesystemWalker`: interacting with mounted filesystems.

## Usage
Usually called by the main application loop:

```cpp
ImageAnalyzer imgAnalyzer(imagePath);
if (imgAnalyzer.openImage()) {
    // Extract metadata to raw database
    imgAnalyzer.extractToDatabase(dbPath);
}
```

## Dependencies
- **The Sleuth Kit (TSK)**: For image and filesystem parsing.
- **libewf**: For E01 image support.
- **DatabaseManager**: For inserting file records.
