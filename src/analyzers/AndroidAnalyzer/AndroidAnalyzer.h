// AndroidAnalyzer.h
// Main header for Android Analyzer module

#pragma once

// IO、字符串与流
#include <iostream>
#include <sstream>
#include <fstream>
#include <streambuf>
#include <iomanip>

// 容器与迭代器
#include <vector>
#include <deque>
#include <list>
#include <forward_list>
#include <array>
#include <set>
#include <unordered_set>
#include <map>
#include <unordered_map>
#include <queue>
#include <stack>
#include <tuple>
#include <utility>
#include <iterator>

// 字符串处理与正则
#include <string>
#include <cstring>
#include <cctype>
#include <regex>

// 算法与函数对象
#include <algorithm>
#include <functional>
#include <numeric>
#include <sqlite3.h>
#include <tsk/libtsk.h>

#include "DatabaseManager/DatabaseManager.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"

#include "fileSystem.h"
#include "AndroidDataTypes.h"
#include "AndroidAnalysisDatabase.h"
#include "AndroidAnalyzerDeclarations.h"

// All implementations have been moved to separate .cpp files for better organization:
// - AndroidAnalyzerCore.cpp: Core functionality (constructors, initialize, analyzeAndroidData)
// - AndroidDataParsers.cpp: Data parsing functions (SMS, contacts, call logs, chat apps, Chrome)
// - AndroidSystemParsers.cpp: System parsing functions (WiFi, packages, usage stats, system analysis)
// - AndroidAnalysisDatabase.cpp: Database operations for AndroidAnalysisDatabase class

