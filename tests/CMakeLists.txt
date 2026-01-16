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

# File Classifier Tests
add_executable(
  test_file_classifier
  UnitTest/test_file_classifier.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifier.cpp
  ../src/core/DatabaseManager/FileClassifier/EncryptionUtils.cpp
  ../src/core/AuditLog/AuditLog.cpp)

target_link_libraries(
  test_file_classifier ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES} sqlite3 pthread
  nlohmann_json::nlohmann_json)

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
  ../src/core/FullTextSearch/TextExtractor.cpp)

target_link_libraries(test_fulltext_search_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} xapian pthread)

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
  ../src/integration/LLMIntegration/ConfigManager.cpp
  ../src/core/Logger/Logger.cpp
  ../src/core/ThreadPool/ThreadPool.cpp
  ../src/integration/LLMIntegration/LLMClient.cpp
  ../src/integration/LLMIntegration/ModelRouter.cpp
  ../src/integration/LLMIntegration/FileAnalyzer.cpp
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
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
          ${CMAKE_SOURCE_DIR}/src/analyzers/PDFAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/OfficeAnalyzer)

target_link_libraries(
  test_llm_integration
  ${GTEST_LIBRARIES}
  ${GMOCK_LIBRARIES}
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
                      ${GMOCK_LIBRARIES} duckx pthread)

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
  ../src/integration/LLMIntegration/ConfigManager.cpp
  ../src/core/Logger/Logger.cpp
  ../src/core/ThreadPool/ThreadPool.cpp
  ../src/integration/LLMIntegration/LLMClient.cpp
  ../src/integration/LLMIntegration/ModelRouter.cpp
  ../src/integration/LLMIntegration/FileAnalyzer.cpp
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
  ../src/integration/LLMIntegration/ConfigManager.cpp
  ../libs/cpp-dotenv/include/dotenv.h)

target_include_directories(
  test_config_manager PRIVATE ${CMAKE_SOURCE_DIR}/src/integration/LLMIntegration
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
