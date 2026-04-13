# CMakeLists.txt for Forensics Project Tests
cmake_minimum_required(VERSION 3.16)

# Find required packages
find_package(GTest QUIET)
find_package(GMock QUIET)
find_package(PkgConfig REQUIRED)
pkg_check_modules(CURL REQUIRED libcurl)

# Include directories
include_directories(${GTEST_INCLUDE_DIRS})
include_directories(${GMOCK_INCLUDE_DIRS})
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/..)
include_directories(${CURL_INCLUDE_DIRS})

# Test scripts for running different test suites
# configure_file("${CMAKE_CURRENT_SOURCE_DIR}/run_unit_tests.sh.in"
# "${CMAKE_CURRENT_BINARY_DIR}/run_unit_tests.sh" @ONLY)
#
# configure_file("${CMAKE_CURRENT_SOURCE_DIR}/run_integration_tests.sh.in"
# "${CMAKE_CURRENT_BINARY_DIR}/run_integration_tests.sh" @ONLY)
#
# configure_file("${CMAKE_CURRENT_SOURCE_DIR}/run_performance_tests.sh.in"
# "${CMAKE_CURRENT_BINARY_DIR}/run_performance_tests.sh" @ONLY)
#
# configure_file("${CMAKE_CURRENT_SOURCE_DIR}/run_all_tests.sh.in"
# "${CMAKE_CURRENT_BINARY_DIR}/run_all_tests.sh" @ONLY)

# Make scripts executable file( CHMOD
# ${CMAKE_CURRENT_BINARY_DIR}/run_unit_tests.sh FILE_PERMISSIONS OWNER_READ
# OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)
# file( CHMOD ${CMAKE_CURRENT_BINARY_DIR}/run_integration_tests.sh
# FILE_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE
# WORLD_READ WORLD_EXECUTE) file( CHMOD
# ${CMAKE_CURRENT_BINARY_DIR}/run_performance_tests.sh FILE_PERMISSIONS
# OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ
# WORLD_EXECUTE) file( CHMOD ${CMAKE_CURRENT_BINARY_DIR}/run_all_tests.sh
# FILE_PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE
# WORLD_READ WORLD_EXECUTE)

# ============================================================================
# New GTest-based Unit Tests
# ============================================================================

# Linux Analyzer GTest Tests
add_executable(
  test_linux_analyzer_gtest
  UnitTest/test_linux_analyzer_gtest.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxLogParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxUserParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxHistoryParser.cpp)

target_link_libraries(test_linux_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME LinuxAnalyzerGTests COMMAND test_linux_analyzer_gtest)

# Web Server Parsers Tests
add_executable(
  test_webserver_parsers_gtest
  UnitTest/test_webserver_parsers_gtest.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/ApacheParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/NginxParser.cpp
  ../src/core/AuditLog/AuditLog.cpp)

target_include_directories(
  test_webserver_parsers_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common
          ${CMAKE_SOURCE_DIR}/src/core/AuditLog)

target_link_libraries(test_webserver_parsers_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME WebServerParsersGTests COMMAND test_webserver_parsers_gtest)

# Security Parsers Tests
add_executable(
  test_linux_security_parsers_gtest
  UnitTest/test_linux_security_parsers_gtest.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SetuidAnalyzer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Security/CapabilityAnalyzer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SELinuxAnalyzer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Security/AppArmorParser.cpp
  ../src/core/AuditLog/AuditLog.cpp)

target_include_directories(
  test_linux_security_parsers_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers/Security
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common
          ${CMAKE_SOURCE_DIR}/src/core/AuditLog)

target_link_libraries(test_linux_security_parsers_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME LinuxSecurityParsersGTests COMMAND test_linux_security_parsers_gtest)

# File Classifier Tests
add_executable(
  test_file_classifier
  UnitTest/test_file_classifier.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifier.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifierMappings.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifierPatterns.cpp
  ../src/core/DatabaseManager/FileClassifier/EncryptionUtils.cpp
  ../src/core/AuditLog/AuditLog.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp
  ../src/core/Logger/Logger.cpp)

target_link_libraries(
  test_file_classifier ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES} sqlite3 pthread
  nlohmann_json::nlohmann_json cpp_dotenv)

add_test(NAME FileClassifierTests COMMAND test_file_classifier)

# Audit Log GTest Tests
add_executable(test_audit_log_gtest UnitTest/test_audit_log_gtest.cpp
                                    ../src/core/AuditLog/AuditLog.cpp)

target_link_libraries(
  test_audit_log_gtest ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES} sqlite3 pthread
  nlohmann_json::nlohmann_json)

add_test(NAME AuditLogGTests COMMAND test_audit_log_gtest)

# File Carving Tests
add_executable(test_file_carving UnitTest/test_file_carving.cpp
                                 ../src/analyzers/FileCarving/FileCarver.cpp)

target_link_libraries(test_file_carving ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      sqlite3 tsk pthread)

add_test(NAME FileCarvingTests COMMAND test_file_carving)

# Installation rules for test scripts (Skipped lines handled by separate
# replacement)

# ============================================================================
# Additional GTest-based Unit Tests
# ============================================================================

# Windows Parsers Tests (header-only - tests data structures and constants)
add_executable(test_windows_parsers_gtest
               UnitTest/test_windows_parsers_gtest.cpp)

target_link_libraries(test_windows_parsers_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME WindowsParsersGTests COMMAND test_windows_parsers_gtest)

# Android Analyzer Tests
add_executable(test_android_analyzer_gtest
               UnitTest/test_android_analyzer_gtest.cpp)

target_link_libraries(test_android_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME AndroidAnalyzerGTests COMMAND test_android_analyzer_gtest)

# FullText Search Tests (with Xapian integration)
add_executable(
  test_fulltext_search_gtest
  UnitTest/test_fulltext_search_gtest.cpp
  ../src/core/FullTextSearch/FullTextSearch.cpp
  ../src/core/FullTextSearch/TextExtractor.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp
  ../src/core/Logger/Logger.cpp)

target_link_libraries(test_fulltext_search_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} xapian pthread cpp_dotenv)

add_test(NAME FullTextSearchGTests COMMAND test_fulltext_search_gtest)

# Image Analyzer Tests (header-only - tests data structures)
add_executable(test_image_analyzer_gtest UnitTest/test_image_analyzer_gtest.cpp)

target_link_libraries(test_image_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME ImageAnalyzerGTests COMMAND test_image_analyzer_gtest)

# LLM Integration Tests
add_executable(
  test_llm_integration
  UnitTest/test_llm_integration.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp
  ../src/core/Logger/Logger.cpp
  ../src/core/ThreadPool/ThreadPool.cpp
  ../src/integration/LLMIntegration/LLMClient.cpp
  ../src/integration/LLMIntegration/ModelRouter.cpp
  ../src/integration/LLMIntegration/FileAnalyzer.cpp
  ../src/integration/LLMIntegration/FileContentExtractor.cpp
  ../src/integration/LLMIntegration/FileTextProcessor.cpp
  ../src/analyzers/PDFAnalyzer/PDFAnalyzer.cpp
  ../src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp
  ../libs/cpp-mcp/src/mcp_message.cpp
  ../libs/cpp-mcp/src/mcp_resource.cpp
  ../libs/cpp-mcp/src/mcp_server.cpp
  ../libs/cpp-mcp/src/mcp_sse_client.cpp
  ../libs/cpp-mcp/src/mcp_tool.cpp)

target_include_directories(
  test_llm_integration
  PRIVATE ${CMAKE_SOURCE_DIR}/src/integration/LLMIntegration
          ${CMAKE_SOURCE_DIR}/src/core/PathManager
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
          ${CMAKE_SOURCE_DIR}/src/analyzers/PDFAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/OfficeAnalyzer)

target_link_libraries(
  test_llm_integration
  ${GTEST_LIBRARIES}
  ${GMOCK_LIBRARIES}
  ${CURL_LIBRARIES}
  pthread
  duckx
  ${POPPLER_LIBRARIES}
  cpp_dotenv)

add_test(NAME LLMIntegrationGTests COMMAND test_llm_integration)

# PDF Analyzer Tests
add_executable(test_pdf_analyzer UnitTest/test_pdf_analyzer.cpp
                                 ../src/analyzers/PDFAnalyzer/PDFAnalyzer.cpp)

target_link_libraries(test_pdf_analyzer ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      ${POPPLER_LIBRARIES} pthread)

# Should include PDFAnalyzer directory
target_include_directories(test_pdf_analyzer
                           PRIVATE ../src/analyzers/PDFAnalyzer)

add_test(NAME PDFAnalyzerTests COMMAND test_pdf_analyzer)

# Office Analyzer Tests
add_executable(
  test_office_analyzer UnitTest/test_office_analyzer.cpp
                       ../src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp)

target_link_libraries(test_office_analyzer ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} duckx ${CURL_LIBRARIES} pthread)

target_include_directories(test_office_analyzer
                           PRIVATE ../src/analyzers/OfficeAnalyzer)

add_test(NAME OfficeAnalyzerTests COMMAND test_office_analyzer)

# ============================================================================
# Installation Rules
# ============================================================================

# Installation rules for test executables (optional)
install(
  TARGETS test_linux_analyzer_gtest
          test_file_classifier
          test_audit_log_gtest
          test_file_carving
          test_windows_parsers_gtest
          test_android_analyzer_gtest
          test_fulltext_search_gtest
          test_image_analyzer_gtest
  RUNTIME DESTINATION bin/tests)

# Test for 13 Files Multi-Model Analysis
add_executable(
  llm_files_test
  llm_files_test.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp
  ../src/core/Logger/Logger.cpp
  ../src/core/ThreadPool/ThreadPool.cpp
  ../src/integration/LLMIntegration/LLMClient.cpp
  ../src/integration/LLMIntegration/ModelRouter.cpp
  ../src/integration/LLMIntegration/FileAnalyzer.cpp
  ../src/integration/LLMIntegration/FileContentExtractor.cpp
  ../src/integration/LLMIntegration/FileTextProcessor.cpp
  ../src/analyzers/VisionAnalysis/VisionAnalyzer.cpp
  ../src/analyzers/PDFAnalyzer/PDFAnalyzer.cpp
  ../src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp
  ../libs/cpp-mcp/src/mcp_message.cpp
  ../libs/cpp-mcp/src/mcp_resource.cpp
  ../libs/cpp-mcp/src/mcp_server.cpp
  ../libs/cpp-mcp/src/mcp_sse_client.cpp
  ../libs/cpp-mcp/src/mcp_tool.cpp)

target_include_directories(
  llm_files_test
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
          ${CMAKE_SOURCE_DIR}/libs/cpp-dotenv/include
          ${CMAKE_SOURCE_DIR}/libs/nlohmann_json/include
          ${CMAKE_SOURCE_DIR}/libs/antlr4-runtime/runtime/src)

target_link_libraries(
  llm_files_test
  ${CURL_LIBRARIES}
  pthread
  antlr4_cpp_runtime
  cpp_dotenv
  duckx
  ${POPPLER_LIBRARIES})

# Config Manager Tests
add_executable(
  test_config_manager
  UnitTest/test_config_manager.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp ../libs/cpp-dotenv/include/dotenv.h)

target_include_directories(
  test_config_manager
  PRIVATE ${CMAKE_SOURCE_DIR}/src/integration/LLMIntegration
          ${CMAKE_SOURCE_DIR}/src/core/PathManager
          ${CMAKE_SOURCE_DIR}/libs/cpp-dotenv/include)

target_link_libraries(test_config_manager ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      pthread cpp_dotenv)

add_test(NAME ConfigManagerTests COMMAND test_config_manager)

# ============================================================================
# New Core Module Tests
# ============================================================================

# ThreadPool Tests
add_executable(test_thread_pool UnitTest/test_thread_pool.cpp
                                ../src/core/ThreadPool/ThreadPool.cpp)

target_include_directories(test_thread_pool PRIVATE ${CMAKE_SOURCE_DIR}/src)

target_link_libraries(test_thread_pool ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      pthread)

add_test(NAME ThreadPoolTests COMMAND test_thread_pool)

# Logger Tests
add_executable(test_logger UnitTest/test_logger.cpp
                           ../src/core/Logger/Logger.cpp)

target_include_directories(test_logger PRIVATE ${CMAKE_SOURCE_DIR}/src)

target_link_libraries(test_logger ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES} pthread)

add_test(NAME LoggerTests COMMAND test_logger)

# ErrorHandling Tests
add_executable(test_error_handling UnitTest/test_error_handling.cpp)

target_include_directories(test_error_handling PRIVATE ${CMAKE_SOURCE_DIR}/src)

target_link_libraries(test_error_handling ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      pthread)

add_test(NAME ErrorHandlingTests COMMAND test_error_handling)

# TOONExporter Tests
add_executable(test_toon_exporter UnitTest/test_toon_exporter.cpp
                                  ../src/core/TOONExporter/TOONExporter.cpp)

target_include_directories(
  test_toon_exporter PRIVATE ${CMAKE_SOURCE_DIR}/src
                             ${CMAKE_SOURCE_DIR}/src/core/TOONExporter)

target_link_libraries(test_toon_exporter ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      sqlite3 pthread)

add_test(NAME TOONExporterTests COMMAND test_toon_exporter)

# OSS Analyzer Tests (Database and Data Types only - no SDK dependency)
add_executable(
  test_oss_analyzer_gtest
  UnitTest/test_oss_analyzer_gtest.cpp
  ../src/analyzers/OSSAnalyzer/Database/OSSAnalysisDatabase.cpp
  ../src/core/AuditLog/AuditLog.cpp ../src/core/Logger/Logger.cpp)

target_include_directories(
  test_oss_analyzer_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/core
          ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Common
          ${CMAKE_SOURCE_DIR}/src/analyzers/OSSAnalyzer/Database)

target_link_libraries(test_oss_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME OSSAnalyzerGTests COMMAND test_oss_analyzer_gtest)

# Database Analyzer Tests
add_executable(
  test_database_analyzer_gtest
  UnitTest/test_database_analyzer_gtest.cpp
  ../src/analyzers/DatabaseAnalyzer/Database/DBAnalysisDatabase.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/DBParserFactory.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/SQLiteAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLDaemon.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLDaemon.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLBinlogParser.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/InnoDBParser.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLHeapParser.cpp)

target_include_directories(
  test_database_analyzer_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Common
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Database
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Parsers
          /usr/include/postgresql
          /usr/include/postgresql/16/server
          /usr/include/mysql)

target_link_libraries(test_database_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread mysqlclient pq)

add_test(NAME DatabaseAnalyzerGTests COMMAND test_database_analyzer_gtest)

# Integration Test for MySQL Daemon
add_executable(
  test_mysql_daemon
  test_mysql_daemon.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLDaemon.cpp
  ../src/core/Logger/Logger.cpp)

target_include_directories(
  test_mysql_daemon
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Common
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Database
          ${CMAKE_SOURCE_DIR}/src/analyzers/DatabaseAnalyzer/Parsers
          /usr/include/mysql)

target_link_libraries(test_mysql_daemon pthread mysqlclient)

# Event Correlation Engine Tests
add_executable(
  test_event_correlation_engine
  UnitTest/test_event_correlation_engine.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationEngineCore.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationAnalyzer.cpp
  ../src/core/EventCorrelationEngine/Detail/EventChainBuilder.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationExporter.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationUtils.cpp
  ../src/core/AuditLog/AuditLog.cpp)

target_include_directories(
  test_event_correlation_engine
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/core
          ${CMAKE_SOURCE_DIR}/src/core/EventCorrelationEngine
          ${CMAKE_SOURCE_DIR}/src/core/AuditLog)

target_link_libraries(test_event_correlation_engine ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread cpp_dotenv nlohmann_json::nlohmann_json)

add_test(NAME EventCorrelationEngineTests COMMAND test_event_correlation_engine)

# Event Timeline Tests
add_executable(
  test_event_timeline
  UnitTest/test_event_timeline_gtest.cpp
  ../src/core/DatabaseManager/EventExtractor/EventExtractor.cpp
  ../src/core/DatabaseManager/DatabaseManager.cpp
  ../src/core/AuditLog/AuditLog.cpp
  ../src/network/HTTPServer/SQLiteHelper.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationEngineCore.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationAnalyzer.cpp
  ../src/core/EventCorrelationEngine/Detail/EventChainBuilder.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationExporter.cpp
  ../src/core/EventCorrelationEngine/Detail/EventCorrelationUtils.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp)

target_include_directories(
  test_event_timeline
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/core
          ${CMAKE_SOURCE_DIR}/src/core/DatabaseManager
          ${CMAKE_SOURCE_DIR}/src/core/AuditLog
          ${CMAKE_SOURCE_DIR}/src/network/HTTPServer
          ${CMAKE_SOURCE_DIR}/src/core/EventCorrelationEngine
          ${CMAKE_SOURCE_DIR}/src/core/ConfigManager
          ${CMAKE_SOURCE_DIR}/src/core/PathManager)

target_link_libraries(test_event_timeline ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread cpp_dotenv nlohmann_json::nlohmann_json)

add_test(NAME EventTimelineTests COMMAND test_event_timeline)

