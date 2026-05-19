// LinuxFilesAnalyzer.h
// Main header for Linux Files Analyzer module

#pragma once

// IO and streams
#include <iostream>
#include <sstream>
#include <fstream>
#include <iomanip>

// Containers
#include <vector>
#include <map>
#include <unordered_map>
#include <set>
#include <queue>

// String processing
#include <string>
#include <cstring>
#include <cctype>
#include <regex>

// Algorithms and utilities
#include <algorithm>
#include <functional>
#include <memory>
#include <cstdint>

// External libraries
#include <sqlite3.h>
#include <tsk/libtsk.h>

// Project includes
#include "DatabaseManager/DatabaseManager.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"

// Module includes
#include "Common/LinuxDataTypes.h"
#include "Database/LinuxAnalysisDatabase.h"
#include "Common/LinuxAnalyzerDeclarations.h"

// Implementation files:
// - Core/LinuxFilesAnalyzerCore.cpp: Core functionality (initialize, analyzeLinuxData)
// - Database/LinuxAnalysisDatabase.cpp: Database operations
// - Parsers/LinuxLogParser.cpp: System log parsing
// - Parsers/LinuxUserParser.cpp: User and authentication parsing
// - Parsers/LinuxHistoryParser.cpp: Shell history parsing
// - Parsers/LinuxArtifactsParsers.cpp: Various artifact parsers
// - Parsers/CompressedLogParser.cpp: Compressed and rotated log parsing (Phase 1)
