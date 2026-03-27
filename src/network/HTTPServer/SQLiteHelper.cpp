#include "SQLiteHelper.h"
#include <iostream>
#include <algorithm>
#include <ctime>
#include <regex>
#include <sstream>
#include <iomanip>

// Include modular query implementations
#include "Queries/SQLiteHelperCore.cpp"
#include "Queries/TimelineQueries.cpp"
#include "Queries/FileAnalysisQueries.cpp"
#include "Queries/StatisticsQueries.cpp"
#include "Queries/AndroidQueries.cpp"
#include "Queries/EventExportQueries.cpp"

using json = nlohmann::json;

// All implementations are now in the modular query files included above.
// This file serves as the central point that brings all query modules together.
