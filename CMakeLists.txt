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
  ${CMAKE_SOURCE_DIR}/FullTextSearch
  # FileCarving
  ${CMAKE_SOURCE_DIR}/FileCarving
  # WindowsFilesAnalyzer includes
  ${CMAKE_SOURCE_DIR}/WindowsFilesAnalyzer
  ${CMAKE_SOURCE_DIR}/WindowsFilesAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/WindowsFilesAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/WindowsFilesAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/WindowsFilesAnalyzer/Parsers
  # LinuxFilesAnalyzer includes
  ${CMAKE_SOURCE_DIR}/LinuxFilesAnalyzer
  ${CMAKE_SOURCE_DIR}/LinuxFilesAnalyzer/Common
  ${CMAKE_SOURCE_DIR}/LinuxFilesAnalyzer/Core
  ${CMAKE_SOURCE_DIR}/LinuxFilesAnalyzer/Database
  ${CMAKE_SOURCE_DIR}/LinuxFilesAnalyzer/Parsers
  # LLMIntegration and cpp-mcp
  ${CMAKE_SOURCE_DIR}/LLMIntegration
  ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
  ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
  # cpp-dotenv (include only, linked via add_subdirectory)
  ${CMAKE_SOURCE_DIR}/libs/cpp-dotenv/include
  # Add Crow include path if needed, e.g., ${CMAKE_SOURCE_DIR}/crow/include
)

# Add cpp-dotenv as subdirectory
add_subdirectory(libs/cpp-dotenv)

link_directories(${TSK_LIBRARY_DIR})

# Source files Common source files
set(LIB_SOURCES
    ImageAnalyzer/ImageAnalyzer.cpp
    DatabaseManager/DatabaseManager.cpp
    DatabaseManager/EventExtractor/EventExtractor.cpp
    DatabaseManager/FileClassifier/FileClassifier.cpp
    DatabaseManager/FileClassifier/EncryptionUtils.cpp
    DatabaseManager/FileExtractor/FileExtractor.cpp
    ImageAnalyzer/XFSHelper.cpp
    ImageAnalyzer/XFSHelper.cpp
    ImageAnalyzer/NativeFilesystemWalker.cpp
    ImageAnalyzer/TskFilesystemWalker.cpp
    HTTPServer/HTTPserver.cpp
    HTTPServer/TaskManager.cpp
    HTTPServer/SQLiteHelper.cpp
    AndroidAnalyzer/AndroidAnalyzerCore.cpp
    AndroidAnalyzer/AndroidDataParsers.cpp
    AndroidAnalyzer/AndroidSystemParsers.cpp
    AndroidAnalyzer/AndroidAnalysisDatabase.cpp
    AndroidAnalyzer/BuildPropAnalyzer.cpp
    WindowsFilesAnalyzer/Core/WindowsFilesAnalyzerCore.cpp
    WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp
    WindowsFilesAnalyzer/Parsers/WindowsRegistryParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsEventLogParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsArtifactsParsers.cpp
    WindowsFilesAnalyzer/Parsers/WindowsPrefetchParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsLnkParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsAmcacheParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsSrumParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsBrowserParser.cpp
    WindowsFilesAnalyzer/Parsers/WindowsBrowserAnalyzer.cpp
    WindowsFilesAnalyzer/Parsers/WindowsJumpListParser.cpp
    LinuxFilesAnalyzer/Core/LinuxFilesAnalyzerCore.cpp
    LinuxFilesAnalyzer/Database/LinuxAnalysisDatabase.cpp
    LinuxFilesAnalyzer/Parsers/LinuxLogParser.cpp
    LinuxFilesAnalyzer/Parsers/LinuxUserParser.cpp
    LinuxFilesAnalyzer/Parsers/LinuxHistoryParser.cpp
    LinuxFilesAnalyzer/Parsers/LinuxArtifactsParsers.cpp
    LinuxFilesAnalyzer/Parsers/LinuxArtifactsParsers.cpp
    AuditLog/AuditLog.cpp
    FullTextSearch/FullTextSearch.cpp
    FullTextSearch/TextExtractor.cpp
    FileCarving/FileCarver.cpp
    # LLMIntegration module
    LLMIntegration/LLMClient.cpp
    LLMIntegration/ModelRouter.cpp
    LLMIntegration/MCPIntegration.cpp
    LLMIntegration/FileAnalyzer.cpp
    LLMIntegration/VisionAnalyzer.cpp
    LLMIntegration/ConfigManager.cpp
    # cpp-mcp library sources
    libs/cpp-mcp/src/mcp_message.cpp
    libs/cpp-mcp/src/mcp_resource.cpp
    libs/cpp-mcp/src/mcp_server.cpp
    libs/cpp-mcp/src/mcp_sse_client.cpp
    libs/cpp-mcp/src/mcp_tool.cpp)

# Create executable Create executable
add_executable(forensic_analyzer main.cpp ${LIB_SOURCES})

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
