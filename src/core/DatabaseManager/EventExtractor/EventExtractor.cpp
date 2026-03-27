// EventExtractor.cpp - Main implementation file that includes detail modules
// This file serves as the main entry point and includes all split modules

#include "EventExtractor.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <sqlite3.h>
#include <algorithm>

// Include detail implementation files
#include "Detail/EventExtractorCore.cpp"
#include "Detail/FileSystemEventExtractor.cpp"
#include "Detail/SystemEventExtractor.cpp"
#include "Detail/EventCorrelationExtractor.cpp"
