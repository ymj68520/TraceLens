cmake_minimum_required(VERSION 3.20)
project(
  ForensicAnalyzer
  VERSION 1.0.0
  LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Find required packages
find_package(SQLite3 REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(Boost REQUIRED COMPONENTS system thread)
find_package(PkgConfig REQUIRED)
pkg_check_modules(HIVEX REQUIRED hivex)
pkg_check_modules(LIBEVTX REQUIRED libevtx)
pkg_check_modules(LIBBFIO REQUIRED libbfio)
pkg_check_modules(LIBESEDB REQUIRED libesedb)
pkg_check_modules(LIBOLECF REQUIRED libolecf)
pkg_check_modules(LIBFSNTFS REQUIRED libfsntfs)
pkg_check_modules(XAPIAN REQUIRED xapian-core)
pkg_check_modules(POPPLER REQUIRED poppler-cpp)

# Optional SQLCipher for encrypted database support (WeChat, etc.)
pkg_check_modules(SQLCIPHER QUIET sqlcipher)
if(SQLCIPHER_FOUND)
  message(STATUS "SQLCipher found - encrypted database support enabled")
  add_definitions(-DHAVE_SQLCIPHER)
  # Use sqlcipher as drop-in replacement for sqlite3 (superset with encryption)
  set(SQLITE_LINK_LIBRARIES ${SQLCIPHER_LIBRARIES})
else()
  message(STATUS "SQLCipher not found - encrypted database support disabled")
  set(SQLITE_LINK_LIBRARIES ${SQLite3_LIBRARIES})
endif()

# Optional libzip for reading Android logical-extraction archives (Image.zip)
# directly, without extracting the whole archive to disk.
pkg_check_modules(LIBZIP QUIET libzip)
if(LIBZIP_FOUND)
  message(STATUS "libzip found - Android zip-source backend enabled")
  add_definitions(-DHAVE_LIBZIP)
else()
  message(STATUS "libzip not found - Android zip-source backend disabled (dir source still works)")
endif()

# Optional database connectors
pkg_check_modules(MYSQLCLIENT mysqlclient)
pkg_check_modules(LIBPQ libpq)

# Optional compression libraries for compressed log parsing
find_package(ZLIB QUIET)
find_package(LibLZMA QUIET)
find_package(BZip2 QUIET)
pkg_check_modules(ZSTD QUIET libzstd)

# Set compression library flags
if(ZLIB_FOUND)
  message(STATUS "zlib found - gzip support enabled")
  add_definitions(-DHAVE_ZLIB)
  add_compile_definitions(USE_ZLIB)
else()
  message(STATUS "zlib not found - gzip support disabled")
endif()

if(LIBLZMA_FOUND)
  message(STATUS "liblzma found - xz support enabled")
  add_definitions(-DHAVE_LIBLZMA)
else()
  message(STATUS "liblzma not found - xz support disabled")
endif()

if(BZIP2_FOUND)
  message(STATUS "bzip2 found - bz2 support enabled")
  add_definitions(-DHAVE_BZIP2)
else()
  message(STATUS "bzip2 not found - bz2 support disabled")
endif()

if(ZSTD_FOUND)
  message(STATUS "zstd found - zst support enabled")
  add_definitions(-DHAVE_ZSTD)
else()
  message(STATUS "zstd not found - zst support disabled")
endif()

# Find nlohmann/json (try multiple methods)
find_package(nlohmann_json QUIET)
if(NOT nlohmann_json_FOUND)
  # Try to find via pkg-config if available
  find_package(PkgConfig QUIET)
  if(PKG_CONFIG_FOUND)
    pkg_check_modules(NLOHMANN_JSON QUIET nlohmann_json)
  endif()

  if(NOT NLOHMANN_JSON_FOUND)
    # Fallback to using header-only version
    message(STATUS "Using system-installed nlohmann/json headers")
    set(NLOHMANN_JSON_INCLUDE_DIRS "/usr/include/nlohmann")
  endif()
endif()

# Find asio (usually header-only)
find_package(asio QUIET)
if(NOT asio_FOUND)
  message(STATUS "Using system-installed asio headers")
  set(ASIO_INCLUDE_DIRS "/usr/include")
endif()

# TSK library paths
if(WIN32)
  # Windows: Use local TSK build
  set(TSK_INCLUDE_DIR
      "${CMAKE_SOURCE_DIR}/sleuthkit"
      CACHE PATH "TSK include directory")
  set(TSK_LIBRARY_DIR
      "${CMAKE_SOURCE_DIR}/sleuthkit/win32/x64/Release_NoLibs"
      CACHE PATH "TSK library directory")
  set(TSK_LIBRARIES "libtsk.lib")
  set(PLATFORM_LIBRARIES "ole32")
else()
  # Linux/Unix: Use system-installed TSK
  set(TSK_INCLUDE_DIR
      "/usr/local/include"
      CACHE PATH "TSK include directory")
  set(TSK_LIBRARY_DIR
      "/usr/local/lib"
      CACHE PATH "TSK library directory")
  set(TSK_LIBRARIES "tsk")
  set(PLATFORM_LIBRARIES "pthread" "dl")
endif()

include_directories(
  ${CMAKE_SOURCE_DIR}
  ${TSK_INCLUDE_DIR}
  ${SQLite3_INCLUDE_DIRS}
  ${Boost_INCLUDE_DIRS}
  ${NLOHMANN_JSON_INCLUDE_DIRS}
  ${ASIO_INCLUDE_DIRS}
  ${HIVEX_INCLUDE_DIRS}
  ${LIBEVTX_INCLUDE_DIRS}
  ${LIBBFIO_INCLUDE_DIRS}
  ${LIBESEDB_INCLUDE_DIRS}
  ${LIBOLECF_INCLUDE_DIRS}
  ${LIBFSNTFS_INCLUDE_DIRS}
  ${XAPIAN_INCLUDE_DIRS}
  ${POPPLER_INCLUDE_DIRS}
  ${ZLIB_INCLUDE_DIRS}
  ${LIBLZMA_INCLUDE_DIRS}
  ${BZIP2_INCLUDE_DIRS}
  ${ZSTD_INCLUDE_DIRS}
  ${SQLCIPHER_INCLUDE_DIRS}
  ${CMAKE_SOURCE_DIR}/libs/sqlite3
  /usr/include/postgresql
  /usr/include/postgresql/16/server
  /usr/include/mysql
  # Source root
  ${CMAKE_SOURCE_DIR}/src
  # Core modules
  ${CMAKE_SOURCE_DIR}/src/core
  ${CMAKE_SOURCE_DIR}/src/core/FullTextSearch
  ${CMAKE_SOURCE_DIR}/src/core/DatabaseManager
  ${CMAKE_SOURCE_DIR}/src/core/AuditLog
  ${CMAKE_SOURCE_DIR}/src/core/PathManager
  ${CMAKE_SOURCE_DIR}/src/core/DatabaseManager/EventCorrelationEngine
  # Analyzer modules
  ${CMAKE_SOURCE_DIR}/src/analyzers
  ${CMAKE_SOURCE_DIR}/src/analyzers/FileCarving
  ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Parsers
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers/Security
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers/Container
  ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Analysis
  ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Volatility
  ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Parsers
  ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/src/analyzers/AndroidAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/ImageAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/VisionAnalysis
  ${CMAKE_SOURCE_DIR}/src/analyzers/PDFAnalyzer
  # Network modules
  ${CMAKE_SOURCE_DIR}/src/network
  ${CMAKE_SOURCE_DIR}/src/network/HTTPServer
  ${CMAKE_SOURCE_DIR}/src/network/HTTPServer/routes
  ${CMAKE_SOURCE_DIR}/src/network/HTTPServer/Queries
  # Office Module
  ${CMAKE_SOURCE_DIR}/src/analyzers/OfficeAnalyzer
  # Integration modules
  ${CMAKE_SOURCE_DIR}/src/integration
  ${CMAKE_SOURCE_DIR}/src/integration/LLMIntegration
  ${CMAKE_SOURCE_DIR}/src/integration/AndroidAdbExtractor
  # TOONExporter
  ${CMAKE_SOURCE_DIR}/src/core/TOONExporter
  # OSSAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Client
  ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Exporters
  # DatabaseAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Parsers
  # DLLAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Parsers
  # Aliyun OSS SDK
  ${CMAKE_SOURCE_DIR}/libs/aliyun-oss-cpp-sdk/sdk/include
  # Libs
  ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
  ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
  # cpp-dotenv (include only, linked via add_subdirectory)
  ${CMAKE_SOURCE_DIR}/libs/cpp-dotenv/include)

# Add cpp-dotenv as subdirectory
add_subdirectory(libs/cpp-dotenv)
add_subdirectory(libs/DuckX)

link_directories(${TSK_LIBRARY_DIR})

# Find Aliyun OSS C++ SDK (vendored at libs/aliyun-oss-cpp-sdk)
find_library(OSS_SDK_LIB
  NAMES alibabacloud-oss-cpp-sdk
  PATHS ${CMAKE_SOURCE_DIR}/libs/aliyun-oss-cpp-sdk/build/lib
  NO_DEFAULT_PATH
  DOC "Aliyun OSS C++ SDK library"
)
if(OSS_SDK_LIB)
  message(STATUS "Aliyun OSS C++ SDK found: ${OSS_SDK_LIB}")
else()
  message(FATAL_ERROR
    "Aliyun OSS C++ SDK not found!\n"
    "The SDK library is expected at: libs/aliyun-oss-cpp-sdk/build/lib/libalibabacloud-oss-cpp-sdk.a\n"
    "Please build it first by running:\n"
    "  ./setup.sh\n"
    "Or manually:\n"
    "  cd libs/aliyun-oss-cpp-sdk && mkdir -p build && cd build\n"
    "  cmake .. -DBUILD_SAMPLE=OFF -DBUILD_TESTS=OFF && make -j$(nproc)\n"
  )
endif()

link_directories(${CMAKE_SOURCE_DIR}/libs/aliyun-oss-cpp-sdk/build/lib)

# Source files Common source files
set(LIB_SOURCES
    src/analyzers/ImageAnalyzer/ImageAnalyzer.cpp
    src/analyzers/PDFAnalyzer/PDFAnalyzer.cpp
    src/core/DatabaseManager/DatabaseManager.cpp
    src/core/DatabaseManager/EventExtractor/Detail/EventExtractorCore.cpp
    src/core/DatabaseManager/EventExtractor/Detail/FileSystemEventExtractor.cpp
    src/core/DatabaseManager/EventExtractor/Detail/SystemEventExtractor.cpp
    src/core/DatabaseManager/EventExtractor/Detail/EventCorrelationExtractor.cpp
    src/core/DatabaseManager/FileClassifier/FileClassifier.cpp
    src/core/DatabaseManager/FileClassifier/FileClassifier_SceneRules.cpp
    src/core/DatabaseManager/FileClassifier/FileClassifierMappings.cpp
    src/core/DatabaseManager/FileClassifier/FileClassifierPatterns.cpp
    src/core/DatabaseManager/FileClassifier/EncryptionUtils.cpp
    src/core/DatabaseManager/FileExtractor/FileExtractor.cpp
    src/core/DatabaseManager/FileExtractor/FileExtractor_Extract.cpp
    src/core/Logger/Logger.cpp
    src/core/ThreadPool/ThreadPool.cpp
    src/analyzers/ImageAnalyzer/XFSHelper.cpp
    src/analyzers/ImageAnalyzer/NativeFilesystemWalker.cpp
    src/analyzers/ImageAnalyzer/TskFilesystemWalker.cpp
    src/analyzers/ImageAnalyzer/KeyFileLoader.cpp
    src/network/Swagger/Swagger.cpp
    src/network/HTTPServer/HTTPserver.cpp
    src/network/HTTPServer/TaskManager.cpp
    src/network/HTTPServer/TaskManagerAnalysis.cpp
    src/network/HTTPServer/SQLiteHelper.cpp
    src/network/HTTPServer/LLMAnalysisService.cpp
    src/network/HTTPServer/WindowsLLMAnalysisService.cpp
    src/network/HTTPServer/WindowsLLMAnalysisService_ArtifactAnalyzers.cpp
    src/network/HTTPServer/WindowsLLMAnalysisService_Database.cpp
    src/network/HTTPServer/LinuxLLMAnalysisService.cpp
    src/network/HTTPServer/LinuxLLMAnalysisService_ArtifactAnalyzers.cpp
    src/network/HTTPServer/LinuxLLMAnalysisService_SystemAnalyzers.cpp
    src/network/HTTPServer/LinuxLLMAnalysisService_Database.cpp
    src/network/HTTPServer/LLMPythonProxy.cpp
    src/network/HTTPServer/EventClusterAnalyzer.cpp
    src/network/HTTPServer/routes/TaskRoutes.cpp
    src/network/HTTPServer/routes/TaskHelpers.cpp
    src/network/HTTPServer/routes/TaskCRUDRoutes.cpp
    src/network/HTTPServer/routes/TaskBatchRoutes.cpp
    src/network/HTTPServer/routes/TaskMonitoringRoutes.cpp
    src/network/HTTPServer/routes/CaseCRUDRoutes.cpp
    src/network/HTTPServer/routes/FilterRoutes.cpp
    src/network/HTTPServer/CaseManager.cpp
    src/network/HTTPServer/TaskSerialization.cpp
    src/network/HTTPServer/TaskPersistence.cpp
    src/network/HTTPServer/TaskWatchdog.cpp
    src/network/HTTPServer/routes/ForensicsRoutes.cpp
    src/network/HTTPServer/routes/RouteHelpers.cpp
    src/network/HTTPServer/routes/TimelineRoutes.cpp
    src/network/HTTPServer/routes/EventClusterRoutes.cpp
    src/network/HTTPServer/routes/ExportRoutes.cpp
    src/network/HTTPServer/routes/FileAnalysisRoutes.cpp
    src/network/HTTPServer/routes/FileExtractionRoutes.cpp
    src/network/HTTPServer/routes/StatisticsRoutes.cpp
    src/network/HTTPServer/routes/AndroidForensicsRoutes.cpp
    src/network/HTTPServer/routes/MemoryForensicsRoutes.cpp
    src/network/HTTPServer/routes/DLLAnalysisRoutes.cpp
    src/network/HTTPServer/routes/SystemEventRoutes.cpp
    src/network/HTTPServer/routes/SceneQueryRoutes.cpp
    src/network/HTTPServer/routes/SystemRoutes.cpp
    src/network/HTTPServer/routes/SystemHealthRoutes.cpp
    src/network/HTTPServer/routes/SystemInfoRoutes.cpp
    src/network/HTTPServer/routes/SystemDocsRoutes.cpp
    src/network/HTTPServer/routes/SearchRoutes.cpp
    src/network/HTTPServer/routes/OSSRoutes.cpp
    src/network/HTTPServer/routes/OSSAnalysisRoutes.cpp
    src/network/HTTPServer/routes/OSSQueryRoutes.cpp
    src/network/HTTPServer/routes/OSSStatsRoutes.cpp
    src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp
    src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp
    src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp
    src/analyzers/AndroidAnalyzer/AndroidSystemParsers.cpp
    src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp
    src/analyzers/AndroidAnalyzer/BuildPropAnalyzer.cpp
    src/analyzers/AndroidAnalyzer/AndroidLogParser.cpp
    src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp
    # WeChatDecryptor always owns a SqlCipherDatabase instance, so its
    # implementation must be linked even when SQLCipher itself is unavailable.
    # In that case it builds against SQLite and encrypted opens fail cleanly.
    src/analyzers/AndroidAnalyzer/SqlCipherDatabase.cpp
    src/analyzers/AndroidAnalyzer/AndroidLogicalParsers.cpp
    # Android logical-extraction backends (dir / zip sources, bypassing TSK)
    src/analyzers/AndroidAnalyzer/LogicalDirExtractor.cpp
    src/analyzers/AndroidAnalyzer/ZipArchiveExtractor.cpp
    src/analyzers/WindowsFilesAnalyzer/Core/WindowsFilesAnalyzerCore.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Registry.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_EventLog.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Prefetch.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Lnk.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Browser.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_User.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_System.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsRegistryParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsRegistryArtifacts.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsEventLogParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsArtifactsParsers.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsArtifactsParsers_ExecutionTraces.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsArtifactsParsers_SystemAnalysis.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsPrefetchParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsPrefetchParser_Helpers.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsLnkParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsAmcacheParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsSrumParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserParser_Init.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserParser_Helpers.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserParser_Chromium.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserParser_Firefox.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserAnalyzer.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsJumpListParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerLogs.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerContainers.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerSecurity.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerServices.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerArtifacts.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerEnhanced.cpp
    src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxArtifactsParsers.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxUserParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxHistoryParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/CompressedLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/JournalParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/AuditdAggregator.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/ApacheParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/NginxParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/MiddlewareLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/MiddlewareLogParser_Middleware.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SetuidAnalyzer.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Security/CapabilityAnalyzer.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SELinuxAnalyzer.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Security/AppArmorParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Container/DockerContainerParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Container/PodmanParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Container/ContainerRuntimeLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/PackageManager/PackageManagerLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/PackageManager/PackageManagerLogParser_LinuxParsers.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/PackageManager/PackageManagerLogParser_UniversalAndAnalysis.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/AccountSSH/AccountSSHAnalyzer.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/AccountSSH/AccountSSHAnalyzer_Accounts.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/AccountSSH/AccountSSHAnalyzer_SSH.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Database/DatabaseLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/EmailVPN/EmailVPNLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/EmailVPN/EmailVPNLogParser_Email.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/EmailVPN/EmailVPNLogParser_VPN.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/FirewallSecurity/FirewallSecurityLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/FirewallSecurity/FirewallSecurityLogParser_Firewall.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/FirewallSecurity/FirewallSecurityLogParser_SecurityProducts.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/LogCorrelationEngine.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/TimelineReconstructor.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/AnomalyDetector.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/LogTamperingDetector.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetector.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetectorScripts.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetectorSystem.cpp
    src/analyzers/LinuxFilesAnalyzer/Analysis/RuleEngine.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/USBMountParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/CloudParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/ExtendedHistoryParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SecurityBypassAnalyzer.cpp
    src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerCore.cpp
    src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp
    src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/WindowsParsers.cpp
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp
    src/core/AuditLog/AuditLog.cpp
    src/core/AuditLog/AuditLog_Queries.cpp
    src/core/PathManager/PathManager.cpp
    src/core/FullTextSearch/FullTextSearch.cpp
    src/core/FullTextSearch/TextExtractor.cpp
    src/core/TOONExporter/TOONExporter.cpp
    src/core/FileFilter/FileFilter.cpp
    src/analyzers/FileCarving/FileCarver.cpp
    # EventCorrelationEngine module
    src/core/EventCorrelationEngine/Detail/EventCorrelationEngineCore.cpp
    src/core/EventCorrelationEngine/Detail/EventCorrelationAnalyzer.cpp
    src/core/EventCorrelationEngine/Detail/EventChainBuilder.cpp
    src/core/EventCorrelationEngine/Detail/EventCorrelationExporter.cpp
    src/core/EventCorrelationEngine/Detail/EventCorrelationUtils.cpp
    # LLMIntegration module
    src/integration/LLMIntegration/LLMClient.cpp
    src/integration/LLMIntegration/ModelRouter.cpp
    src/integration/LLMIntegration/MCPIntegration.cpp
    src/integration/LLMIntegration/FileAnalyzer.cpp
    src/integration/LLMIntegration/MarkitdownProxy.cpp
    src/integration/LLMIntegration/FileContentExtractor.cpp
    src/integration/LLMIntegration/FileTextProcessor.cpp
    src/core/ConfigManager/ConfigManager.cpp
    src/CommandLineParser.cpp
    src/AnalysisOrchestrator.cpp
    src/report/ReportGenerator.cpp
    # Text dump export module (bounded text-dump pipeline + production adapters)
    src/export/TextDumpExporter.cpp
    src/export/TextDumpAdapters.cpp
    src/analyzers/VisionAnalysis/VisionAnalyzer.cpp
    # OSSAnalyzer module
    src/analyzers/OSSAnalyzer/Core/OSSAnalyzerCore.cpp
    src/analyzers/OSSAnalyzer/Database/OSSAnalysisDatabase.cpp
    src/analyzers/OSSAnalyzer/Database/OSSAnalysisDatabase_Queries.cpp
    src/analyzers/OSSAnalyzer/Client/OSSClient.cpp
    # DatabaseAnalyzer module
    src/analyzers/DatabaseAnalyzer/Core/DatabaseAnalyzerCore.cpp
    src/analyzers/DatabaseAnalyzer/Database/DBAnalysisDatabase.cpp
src/analyzers/DatabaseAnalyzer/Database/DBAnalysisDatabase_Queries.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/DBParserFactory.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/SQLiteAnalyzer.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/SQLiteAnalyzer_Forensics.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/MySQLAnalyzer.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/MySQLDaemon.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLAnalyzer.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLDaemon.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/MySQLBinlogParser.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/InnoDBParser.cpp
    src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLHeapParser.cpp
    # DLLAnalyzer module
    src/analyzers/DLLAnalyzer/Core/DLLAnalyzerCore.cpp
    src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.cpp
src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase_Queries.cpp
    src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.cpp
    src/analyzers/DLLAnalyzer/Parsers/PEImportExportParser.cpp
    src/analyzers/DLLAnalyzer/Parsers/ELFParser.cpp
    src/analyzers/DLLAnalyzer/Parsers/ELFParser_Sections.cpp
    src/analyzers/DLLAnalyzer/Parsers/ELFParser_Dynamic.cpp
    src/analyzers/DLLAnalyzer/Parsers/SignatureVerifier.cpp
    src/analyzers/DLLAnalyzer/Core/PEAnalyzer.cpp
    src/analyzers/DLLAnalyzer/Core/AnomalyDetector.cpp
    src/analyzers/DLLAnalyzer/Core/DependencyAnalyzer.cpp
    # cpp-mcp library sources
    libs/cpp-mcp/src/mcp_message.cpp
    libs/cpp-mcp/src/mcp_resource.cpp
    libs/cpp-mcp/src/mcp_server.cpp
    libs/cpp-mcp/src/mcp_sse_client.cpp
    libs/cpp-mcp/src/mcp_tool.cpp)

# Create executable Create executable
if(UNIX)
  list(APPEND LIB_SOURCES src/analyzers/ImageAnalyzer/DecryptionModule.cpp)
else()
  list(APPEND LIB_SOURCES src/analyzers/ImageAnalyzer/DecryptionModuleStub.cpp)
endif()

add_executable(forensic_analyzer src/main.cpp ${LIB_SOURCES})

# Link libraries
if(WIN32)
  target_link_libraries(forensic_analyzer ${TSK_LIBRARIES} sqlite3.lib
                        ${Boost_LIBRARIES} ${PLATFORM_LIBRARIES})
else()
  target_link_libraries(
    forensic_analyzer
    ${TSK_LIBRARIES}
    ewf
    ${SQLITE_LINK_LIBRARIES}
    ${Boost_LIBRARIES}
    ${HIVEX_LIBRARIES}
    ${LIBEVTX_LIBRARIES}
    ${LIBBFIO_LIBRARIES}
    ${LIBESEDB_LIBRARIES}
    ${LIBOLECF_LIBRARIES}
    ${LIBFSNTFS_LIBRARIES}
    ${XAPIAN_LIBRARIES}
    ${POPPLER_LIBRARIES}
    mysqlclient
    pq
    cpp_dotenv
    duckx
    ${OSS_SDK_LIB}
    curl
    OpenSSL::SSL
    OpenSSL::Crypto
    ${ZLIB_LIBRARIES}
    ${LIBLZMA_LIBRARIES}
    ${BZIP2_LIBRARIES}
    ${ZSTD_LIBRARIES}
    ${LIBZIP_LIBRARIES}
    ${PLATFORM_LIBRARIES})
endif()

# Installation
install(TARGETS forensic_analyzer DESTINATION bin)
install(PROGRAMS scripts/bitlocker_fvek_decrypt.py DESTINATION bin/scripts)

# Enable testing and add tests subdirectory for GTest-based tests
enable_testing()
add_subdirectory(tests)

# ================================
# C++ Client HTTP Agent
# ================================
# Standalone sub-project (Tasks 16-21) with minimal deps (OpenSSL, SQLite3,
# Threads, nlohmann/json vendored). Does NOT depend on forensic libs.
# Conditioned only on http_agent's deps (NOT on forensic deps), so it builds
# as long as its own minimal deps are available, regardless of whether the
# heavy forensic libs are present. This enables root builds that include the
# client agent without gating it on the forensic dep chain.
#
# NOTE: The conditional checks only OpenSSL_FOUND and SQLite3_FOUND (not
# Threads_FOUND or nlohmann_json_FOUND from brief D1) because: (a) Threads is
# universally available and resolved by http_agent's own find_package(Threads
# REQUIRED), and (b) nlohmann/json is vendored in libs/cpp-mcp/common, so no
# find_package check is needed. The else-branch is unreachable in a normal
# root build because root does find_package(OpenSSL/SQLite3 REQUIRED), but it
# serves as defensive forward-compatible code if those REQUIRED calls are
# ever softened to QUIET.
if(OpenSSL_FOUND AND SQLite3_FOUND)
  add_subdirectory(src/http_agent)
else()
  message(WARNING "http_agent deps (OpenSSL or SQLite3) missing — skipping src/http_agent")
endif()

# ================================
# Web Frontend Build Integration
# ================================

option(BUILD_WEB_FRONTEND "Build React frontend" ON)

if(BUILD_WEB_FRONTEND)
  # Find Node.js and npm
  find_program(NODE_EXECUTABLE node)
  find_program(NPM_EXECUTABLE npm)

  if(NOT NODE_EXECUTABLE OR NOT NPM_EXECUTABLE)
    message(WARNING "Node.js and npm not found. Skipping frontend build.")
    message(
      WARNING
        "Install Node.js to build the frontend: sudo apt-get install nodejs npm"
    )
  else()
    # Frontend build configuration
    set(WEB_SOURCE_DIR "${CMAKE_SOURCE_DIR}/web")
    set(WEB_BUILD_DIR "${CMAKE_BINARY_DIR}/web")
    set(WEB_OUTPUT_DIR "${CMAKE_BINARY_DIR}/web/dist")

    # Check if web directory exists
    if(EXISTS "${WEB_SOURCE_DIR}")
      # Install frontend dependencies
      add_custom_command(
        OUTPUT ${WEB_SOURCE_DIR}/node_modules/.timestamp
        COMMAND ${NPM_EXECUTABLE} install
        COMMAND ${CMAKE_COMMAND} -E touch
                ${WEB_SOURCE_DIR}/node_modules/.timestamp
        WORKING_DIRECTORY ${WEB_SOURCE_DIR}
        COMMENT "Installing frontend dependencies")

      # Single custom target that always runs (letting Vite handle caching) This
      # builds the frontend and copies it to the build directory
      add_custom_target(
        web_frontend ALL
        COMMAND ${NPM_EXECUTABLE} run build
        COMMAND ${CMAKE_COMMAND} -E make_directory ${WEB_OUTPUT_DIR}
        COMMAND ${CMAKE_COMMAND} -E copy_directory ${WEB_SOURCE_DIR}/dist
                ${WEB_OUTPUT_DIR}
        WORKING_DIRECTORY ${WEB_SOURCE_DIR}
        COMMENT "Building and copying Web Frontend")

      # Install built frontend to binary directoryInstall built frontend to
      # binary directory
      install(
        DIRECTORY ${WEB_OUTPUT_DIR}/
        DESTINATION bin/web
        FILES_MATCHING
        PATTERN *)

      message(STATUS "Web frontend build configured")
      message(STATUS "  Source: ${WEB_SOURCE_DIR}")
      message(STATUS "  Build: ${WEB_BUILD_DIR}")
      message(STATUS "  Output: ${WEB_OUTPUT_DIR}")
    else()
      message(WARNING "Web source directory not found: ${WEB_SOURCE_DIR}")
      message(
        WARNING "Skipping frontend build. Create the web/ directory to enable.")
    endif()
  endif()
endif()

# Print build summary
message(STATUS "")
message(STATUS "========================================")
message(STATUS "Forensic Analyzer Build Configuration")
message(STATUS "========================================")
message(STATUS "Build Type: ${CMAKE_BUILD_TYPE}")
message(STATUS "Build Frontend: ${BUILD_WEB_FRONTEND}")
message(STATUS "Build Python Service: ${BUILD_PYTHON_SERVICE}")
message(STATUS "========================================")
message(STATUS "")

# ================================
# Python Service Build Integration
# ================================

option(BUILD_PYTHON_SERVICE "Setup Python service environment" ON)

if(BUILD_PYTHON_SERVICE)
  # Find Python3
  find_package(Python3 COMPONENTS Interpreter)

  if(NOT Python3_FOUND)
    message(WARNING "Python3 not found. Skipping Python service setup.")
    message(
      WARNING
        "Install Python3: sudo apt-get install python3 python3-venv python3-pip"
    )
  else()
    set(PYTHON_SERVICE_DIR "${CMAKE_SOURCE_DIR}/python_service")
    set(PYTHON_VENV_DIR "${PYTHON_SERVICE_DIR}/.venv")
    set(PYTHON_REQUIREMENTS "${PYTHON_SERVICE_DIR}/httpserver/requirements.txt")

    if(EXISTS "${PYTHON_SERVICE_DIR}")
      # Create virtual environment
      add_custom_command(
        OUTPUT ${PYTHON_VENV_DIR}/pyvenv.cfg
        COMMAND ${Python3_EXECUTABLE} -m venv ${PYTHON_VENV_DIR}
        COMMENT "Creating Python virtual environment")

      # Install dependencies
      add_custom_command(
        OUTPUT ${PYTHON_VENV_DIR}/.deps_installed
        DEPENDS ${PYTHON_VENV_DIR}/pyvenv.cfg ${PYTHON_REQUIREMENTS}
        COMMAND ${PYTHON_VENV_DIR}/bin/pip install --upgrade pip
        COMMAND ${PYTHON_VENV_DIR}/bin/pip install -r ${PYTHON_REQUIREMENTS}
        COMMAND ${CMAKE_COMMAND} -E touch ${PYTHON_VENV_DIR}/.deps_installed
        WORKING_DIRECTORY ${PYTHON_SERVICE_DIR}
        COMMENT "Installing Python dependencies")

      # Python service setup target
      add_custom_target(
        python_service
        DEPENDS ${PYTHON_VENV_DIR}/.deps_installed
        COMMENT "Python service environment ready")

      # Python syntax check target (optional)
      add_custom_target(
        python_check
        COMMAND
          ${PYTHON_VENV_DIR}/bin/python -m py_compile
          ${PYTHON_SERVICE_DIR}/httpserver/main.py
          ${PYTHON_SERVICE_DIR}/httpserver/config.py
        WORKING_DIRECTORY ${PYTHON_SERVICE_DIR}
        COMMENT "Checking Python syntax")

      # Start Python service target (for development)
      add_custom_target(
        run_python_service
        COMMAND ${PYTHON_VENV_DIR}/bin/python -m httpserver.main
        WORKING_DIRECTORY ${PYTHON_SERVICE_DIR}
        COMMENT "Starting Python HTTP service on port 8090")

      # Start all services target (C++ + Python + Web)
      add_custom_target(
        start_all
        COMMAND ${CMAKE_SOURCE_DIR}/scripts/start_all_services.sh
        WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
        COMMENT
          "Starting all services (C++ server, Python service, Web frontend)")

      message(STATUS "Python service setup configured")
      message(STATUS "  Source: ${PYTHON_SERVICE_DIR}")
      message(STATUS "  Venv: ${PYTHON_VENV_DIR}")
      message(STATUS "  Requirements: ${PYTHON_REQUIREMENTS}")
    else()
      message(
        WARNING "Python service directory not found: ${PYTHON_SERVICE_DIR}")
    endif()
  endif()
endif()
