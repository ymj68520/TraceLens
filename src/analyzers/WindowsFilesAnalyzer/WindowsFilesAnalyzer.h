// WindowsFilesAnalyzer.h
// Main header for Windows Files Analyzer module

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
#include "Common/WindowsDataTypes.h"
#include "Database/WindowsAnalysisDatabase.h"
#include "Common/WindowsAnalyzerDeclarations.h"
#include "Parsers/WindowsEventLogParser.h"

// Implementation files:
// - Core/WindowsFilesAnalyzerCore.cpp: Core functionality (initialize, analyzeWindowsData)
// - Database/WindowsAnalysisDatabase.cpp: Database operations
// - Parsers/WindowsRegistryParser.cpp: Registry hive parsing
// - Parsers/WindowsEventLogParser.cpp: Event log (EVTX) parsing
// - Parsers/WindowsArtifactsParsers.cpp: Prefetch, LNK, Jump Lists, Recycle Bin parsing
