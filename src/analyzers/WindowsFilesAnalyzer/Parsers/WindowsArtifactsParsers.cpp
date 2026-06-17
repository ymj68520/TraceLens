// WindowsArtifactsParsers.cpp
// Implementation of various Windows artifact parsers

#include "WindowsFilesAnalyzer.h"
#include "WindowsPrefetchParser.h"
#include "WindowsLnkParser.h"
#include "WindowsAmcacheParser.h"
#include "WindowsSrumParser.h"
#include "WindowsBrowserParser.h"
#include "WindowsJumpListParser.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"
#include <libfsntfs.h>
#include <pugixml.hpp>
#include <fstream>
#include <ctime>
#include <filesystem>

namespace fs = std::filesystem;

// --- Prefetch Analysis ---
// WindowsArtifactsParsers.cpp
// Implementation split across two sibling files:
//   - WindowsArtifactsParsers_ExecutionTraces.cpp  (prefetch/lnk/jumplist/recyclebin)
//   - WindowsArtifactsParsers_SystemAnalysis.cpp    (NTFS/users/services/tasks/amcache/SRUM)
