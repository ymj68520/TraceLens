// LinuxArtifactsParsers.cpp
// Implementation of various Linux artifact parsers
// This file now serves as a dispatcher that includes the modular implementations

#include "LinuxFilesAnalyzer.h"
#include "LinuxLogParser.h"
#include "LinuxUserParser.h"
#include "LinuxHistoryParser.h"
#include "AuditLog/AuditLog.h"

// Include modular implementations
#include "Detail/LinuxLogParser.cpp"
#include "Detail/LinuxUserParser.cpp"
#include "Detail/LinuxSystemParser.cpp"
#include "Detail/LinuxNetworkParser.cpp"
