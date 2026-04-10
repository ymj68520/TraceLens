// LinuxAnalysisDatabase.cpp
// Implementation of LinuxAnalysisDatabase - Main file that includes detail implementations

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <iostream>
#include <sstream>
#include <mutex>

// Include detail implementation files
#include "Detail/LinuxAnalysisDatabaseCore.cpp"
#include "Detail/LinuxLogOperations.cpp"
#include "Detail/LinuxUserOperations.cpp"
#include "Detail/LinuxSystemOperations_Part1.cpp"
#include "Detail/LinuxSystemOperations_Part2.cpp"
#include "Detail/LinuxEnhancedOperations.cpp"

using namespace LinuxAnalysis;

// All implementation details are now in the detail files included above
// This file serves as the main entry point for the LinuxAnalysisDatabase implementation
