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
find_package(Boost REQUIRED COMPONENTS system thread)
find_package(PkgConfig REQUIRED)
pkg_check_modules(HIVEX REQUIRED hivex)
pkg_check_modules(LIBEVTX REQUIRED libevtx)
pkg_check_modules(LIBBFIO REQUIRED libbfio)
pkg_check_modules(LIBESEDB REQUIRED libesedb)
pkg_check_modules(LIBOLECF REQUIRED libolecf)
pkg_check_modules(XAPIAN REQUIRED xapian-core)

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
  ${XAPIAN_INCLUDE_DIRS}
  ${CMAKE_SOURCE_DIR}/libs/sqlite3
  # Source root
  ${CMAKE_SOURCE_DIR}/src
  # Core modules
  ${CMAKE_SOURCE_DIR}/src/core
  ${CMAKE_SOURCE_DIR}/src/core/FullTextSearch
  ${CMAKE_SOURCE_DIR}/src/core/DatabaseManager
  ${CMAKE_SOURCE_DIR}/src/core/AuditLog
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
  ${CMAKE_SOURCE_DIR}/src/analyzers/AndroidAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/ImageAnalyzer
  ${CMAKE_SOURCE_DIR}/src/analyzers/VisionAnalysis
  # Network modules
  ${CMAKE_SOURCE_DIR}/src/network
  ${CMAKE_SOURCE_DIR}/src/network/HTTPServer
  # Integration modules
  ${CMAKE_SOURCE_DIR}/src/integration
  ${CMAKE_SOURCE_DIR}/src/integration/LLMIntegration
  ${CMAKE_SOURCE_DIR}/src/integration/AndroidAdbExtractor
  # Libs
  ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
  ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
  # cpp-dotenv (include only, linked via add_subdirectory)
  ${CMAKE_SOURCE_DIR}/libs/cpp-dotenv/include)

# Add cpp-dotenv as subdirectory
add_subdirectory(libs/cpp-dotenv)

link_directories(${TSK_LIBRARY_DIR})

# Source files Common source files
set(LIB_SOURCES
    src/analyzers/ImageAnalyzer/ImageAnalyzer.cpp
    src/core/DatabaseManager/DatabaseManager.cpp
    src/core/DatabaseManager/EventExtractor/EventExtractor.cpp
    src/core/DatabaseManager/FileClassifier/FileClassifier.cpp
    src/core/DatabaseManager/FileClassifier/EncryptionUtils.cpp
    src/core/DatabaseManager/FileExtractor/FileExtractor.cpp
    src/analyzers/ImageAnalyzer/XFSHelper.cpp
    src/analyzers/ImageAnalyzer/NativeFilesystemWalker.cpp
    src/analyzers/ImageAnalyzer/TskFilesystemWalker.cpp
    src/network/HTTPServer/HTTPserver.cpp
    src/network/HTTPServer/TaskManager.cpp
    src/network/HTTPServer/SQLiteHelper.cpp
    src/analyzers/AndroidAnalyzer/AndroidAnalyzerCore.cpp
    src/analyzers/AndroidAnalyzer/AndroidDataParsers.cpp
    src/analyzers/AndroidAnalyzer/AndroidSystemParsers.cpp
    src/analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.cpp
    src/analyzers/AndroidAnalyzer/BuildPropAnalyzer.cpp
    src/analyzers/WindowsFilesAnalyzer/Core/WindowsFilesAnalyzerCore.cpp
    src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsRegistryParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsEventLogParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsArtifactsParsers.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsPrefetchParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsLnkParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsAmcacheParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsSrumParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserParser.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsBrowserAnalyzer.cpp
    src/analyzers/WindowsFilesAnalyzer/Parsers/WindowsJumpListParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp
    src/analyzers/LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxLogParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxUserParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxHistoryParser.cpp
    src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxArtifactsParsers.cpp
    src/core/AuditLog/AuditLog.cpp
    src/core/FullTextSearch/FullTextSearch.cpp
    src/core/FullTextSearch/TextExtractor.cpp
    src/analyzers/FileCarving/FileCarver.cpp
    # LLMIntegration module
    src/integration/LLMIntegration/LLMClient.cpp
    src/integration/LLMIntegration/ModelRouter.cpp
    src/integration/LLMIntegration/MCPIntegration.cpp
    src/integration/LLMIntegration/FileAnalyzer.cpp
    src/integration/LLMIntegration/ConfigManager.cpp
    src/analyzers/VisionAnalysis/VisionAnalyzer.cpp
    # cpp-mcp library sources
    libs/cpp-mcp/src/mcp_message.cpp
    libs/cpp-mcp/src/mcp_resource.cpp
    libs/cpp-mcp/src/mcp_server.cpp
    libs/cpp-mcp/src/mcp_sse_client.cpp
    libs/cpp-mcp/src/mcp_tool.cpp)

# Create executable Create executable
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
    ${SQLite3_LIBRARIES}
    ${Boost_LIBRARIES}
    ${HIVEX_LIBRARIES}
    ${LIBEVTX_LIBRARIES}
    ${LIBBFIO_LIBRARIES}
    ${LIBESEDB_LIBRARIES}
    ${LIBOLECF_LIBRARIES}
    ${XAPIAN_LIBRARIES}
    cpp_dotenv
    ${PLATFORM_LIBRARIES})
endif()

# Installation
install(TARGETS forensic_analyzer DESTINATION bin)

# Enable testing and add tests subdirectory for GTest-based tests
enable_testing()
add_subdirectory(tests)
