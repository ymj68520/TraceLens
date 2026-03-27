# SQLiteHelper Query Modules

This directory contains modular implementations of SQLiteHelper database queries, split from the original monolithic `SQLiteHelper.cpp` (1519 lines) into specialized modules.

## Architecture

The query modules follow a logical separation of concerns:

### Core Module
- **SQLiteHelperCore.cpp** (141 lines)
  - Database connection management
  - Query execution utilities
  - Helper methods (timestamp parsing, table existence checks)
  - Utility functions (suspicious file/path detection)

### Timeline Analysis Module
- **TimelineQueries.cpp** (372 lines)
  - Comprehensive timeline with event clustering
  - Timeline details and distribution
  - File activity timeline
  - Timeline filtering by type, time range, file path
  - Event statistics by period (hourly, daily, weekly, monthly)
  - Full timeline export with pagination

### File Analysis Module
- **FileAnalysisQueries.cpp** (220 lines)
  - File summary statistics
  - Largest files identification
  - Recent files detection
  - Suspicious file analysis
  - Duplicate file detection
  - Extension and category analysis
  - LLM analysis results

### Statistical Analysis Module
- **StatisticsQueries.cpp** (453 lines)
  - Overview statistics (raw, events, files databases)
  - File distribution analysis
  - Activity patterns (hourly, weekly)
  - Deleted files analysis
  - Suspicious pattern detection
  - User activity analysis
  - System events and summaries

### Android Forensics Module
- **AndroidQueries.cpp** (197 lines)
  - Communication summary (SMS, WhatsApp, contacts, calls)
  - App usage statistics
  - Device information (build props, WiFi, Chrome history)
  - Media file analysis

### Event Export Module
- **EventExportQueries.cpp** (200 lines)
  - JSON export
  - CSV export
  - Visualization-ready JSON export

## Design Benefits

1. **Maintainability**: Each module focuses on a specific domain, making it easier to locate and modify code
2. **Testability**: Smaller files are easier to unit test
3. **Readability**: Developers can quickly find relevant functionality
4. **Compilation**: Changes to one module don't require recompiling others
5. **Scalability**: New query types can be added as separate modules

## Usage

All modules are included in the main `SQLiteHelper.cpp` file:

```cpp
#include "Queries/SQLiteHelperCore.cpp"
#include "Queries/TimelineQueries.cpp"
#include "Queries/FileAnalysisQueries.cpp"
#include "Queries/StatisticsQueries.cpp"
#include "Queries/AndroidQueries.cpp"
#include "Queries/EventExportQueries.cpp"
```

The public API remains unchanged - all methods are still part of the `SQLiteHelper` class as defined in `SQLiteHelper.h`.

## Build System

The modules are registered in both:
- `CMakeLists.txt` (main build)
- `tests/CMakeLists.txt` (test builds)

## File Size Summary

| Module | Lines | Purpose |
|--------|-------|---------|
| SQLiteHelperCore.cpp | 141 | Core utilities |
| TimelineQueries.cpp | 372 | Timeline analysis |
| FileAnalysisQueries.cpp | 220 | File analysis |
| StatisticsQueries.cpp | 453 | Statistical analysis |
| AndroidQueries.cpp | 197 | Android forensics |
| EventExportQueries.cpp | 200 | Event export |
| **Total** | **1583** | **All modules** |

The original `SQLiteHelper.cpp` was reduced from **1519 lines** to **20 lines** (just includes).
