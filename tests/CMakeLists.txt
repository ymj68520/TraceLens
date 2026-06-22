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
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/LinuxHistoryParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp)

target_include_directories(
  test_linux_analyzer_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_linux_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME LinuxAnalyzerGTests COMMAND test_linux_analyzer_gtest)

# Compressed Log Parser Tests
add_executable(
  test_compressed_log_parser
  UnitTest/test_compressed_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/CompressedLogParser.cpp)

target_include_directories(
  test_compressed_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_compressed_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread
                      ${ZLIB_LIBRARIES}
                      ${LIBLZMA_LIBRARIES}
                      ${BZIP2_LIBRARIES}
                      ${ZSTD_LIBRARIES})

add_test(NAME CompressedLogParserTests COMMAND test_compressed_log_parser)

# Journal Parser Tests
add_executable(
  test_journal_parser
  UnitTest/test_journal_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/JournalParser.cpp)

target_include_directories(
  test_journal_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_journal_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME JournalParserTests COMMAND test_journal_parser)

# Timestamp Normalizer Tests
add_executable(
  test_timestamp_normalizer
  UnitTest/test_timestamp_normalizer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp)

target_include_directories(
  test_timestamp_normalizer
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_timestamp_normalizer ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME TimestampNormalizerTests COMMAND test_timestamp_normalizer)

# Auditd Aggregator Tests
add_executable(
  test_auditd_aggregator
  UnitTest/test_auditd_aggregator.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/AuditdAggregator.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp)

target_include_directories(
  test_auditd_aggregator
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_auditd_aggregator ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME AuditdAggregatorTests COMMAND test_auditd_aggregator)

# Log Tampering Detector Tests
add_executable(
  test_log_tampering_detector
  UnitTest/test_log_tampering_detector.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Analysis/LogTamperingDetector.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/JournalParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/AuditdAggregator.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/CompressedLogParser.cpp)

target_include_directories(
  test_log_tampering_detector
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Analysis
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_log_tampering_detector ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread
                      ${ZLIB_LIBRARIES}
                      ${LIBLZMA_LIBRARIES}
                      ${BZIP2_LIBRARIES}
                      ${ZSTD_LIBRARIES})

add_test(NAME LogTamperingDetectorTests COMMAND test_log_tampering_detector)

# Persistence Detector Tests
add_executable(
  test_persistence_detector
  UnitTest/test_persistence_detector.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Analysis/PersistenceDetector.cpp)

target_include_directories(
  test_persistence_detector
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Analysis
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_persistence_detector ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME PersistenceDetectorTests COMMAND test_persistence_detector)

# Middleware Log Parser Tests (Phase 7)
add_executable(
  test_middleware_log_parser
  UnitTest/test_middleware_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/MiddlewareLogParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/WebServer/MiddlewareLogParser_Middleware.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp)

target_include_directories(
  test_middleware_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_middleware_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME MiddlewareLogParserTests COMMAND test_middleware_log_parser)

# Container Runtime Log Parser Tests (Phase 8)
add_executable(
  test_container_runtime_log_parser
  UnitTest/test_container_runtime_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Container/ContainerRuntimeLogParser.cpp)

target_include_directories(
  test_container_runtime_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_container_runtime_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME ContainerRuntimeLogParserTests COMMAND test_container_runtime_log_parser)

# Package Manager Log Parser Tests (Phase 9)
add_executable(
  test_package_manager_log_parser
  UnitTest/test_package_manager_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/PackageManager/PackageManagerLogParser.cpp)

target_include_directories(
  test_package_manager_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_package_manager_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME PackageManagerLogParserTests COMMAND test_package_manager_log_parser)

# Account/SSH Security Analyzer Tests (Phase 10)
add_executable(
  test_account_ssh_analyzer
  UnitTest/test_account_ssh_analyzer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Analysis/AccountSSH/AccountSSHAnalyzer.cpp)

target_include_directories(
  test_account_ssh_analyzer
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Analysis
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_account_ssh_analyzer ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME AccountSSHAnalyzerTests COMMAND test_account_ssh_analyzer)

# Database Log Parser Tests
add_executable(
  test_database_log_parser
  UnitTest/test_database_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Database/DatabaseLogParser.cpp)

target_include_directories(
  test_database_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_database_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME DatabaseLogParserTests COMMAND test_database_log_parser)

# Email/VPN Log Parser Tests
add_executable(
  test_email_vpn_log_parser
  UnitTest/test_email_vpn_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/EmailVPN/EmailVPNLogParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/EmailVPN/EmailVPNLogParser_Email.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/EmailVPN/EmailVPNLogParser_VPN.cpp)

target_include_directories(
  test_email_vpn_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_email_vpn_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME EmailVPNLogParserTests COMMAND test_email_vpn_log_parser)

# Firewall/Security Log Parser Tests
add_executable(
  test_firewall_security_log_parser
  UnitTest/test_firewall_security_log_parser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/FirewallSecurity/FirewallSecurityLogParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/FirewallSecurity/FirewallSecurityLogParser_Firewall.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/FirewallSecurity/FirewallSecurityLogParser_SecurityProducts.cpp)

target_include_directories(
  test_firewall_security_log_parser
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_firewall_security_log_parser ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} pthread)

add_test(NAME FirewallSecurityLogParserTests COMMAND test_firewall_security_log_parser)

# Enhanced Parsers Tests (Phase 12-15: USB/Mount, Cloud, Extended History, Security Bypass)
add_executable(
  test_linux_enhanced_parsers_gtest
  UnitTest/test_linux_enhanced_parsers_gtest.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/USBMountParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/CloudParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/ExtendedHistoryParser.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SecurityBypassAnalyzer.cpp
  ../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.cpp)

target_include_directories(
  test_linux_enhanced_parsers_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Parsers/Security
          ${CMAKE_SOURCE_DIR}/src/analyzers/LinuxFilesAnalyzer/Common)

target_link_libraries(test_linux_enhanced_parsers_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME EnhancedParsersGTests COMMAND test_linux_enhanced_parsers_gtest)

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

# Scene Classifier Tests
add_executable(
  test_scene_classifier_gtest
  UnitTest/test_scene_classifier_gtest.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifier.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifierMappings.cpp
  ../src/core/DatabaseManager/FileClassifier/FileClassifierPatterns.cpp
  ../src/core/DatabaseManager/FileClassifier/EncryptionUtils.cpp
  ../src/core/AuditLog/AuditLog.cpp
  ../src/core/ConfigManager/ConfigManager.cpp
  ../src/core/PathManager/PathManager.cpp
  ../src/core/Logger/Logger.cpp
  ../src/network/HTTPServer/LLMAnalysisService.cpp
  ../src/integration/LLMIntegration/ModelRouter.cpp
  ../src/integration/LLMIntegration/FileAnalyzer.cpp
  ../src/integration/LLMIntegration/LLMClient.cpp
  ../src/integration/LLMIntegration/FileContentExtractor.cpp
  ../src/integration/LLMIntegration/FileTextProcessor.cpp
  ../src/integration/LLMIntegration/MarkitdownProxy.cpp
  ../src/core/ThreadPool/ThreadPool.cpp
  ../src/analyzers/PDFAnalyzer/PDFAnalyzer.cpp
  ../src/analyzers/OfficeAnalyzer/OfficeAnalyzer.cpp)

target_link_libraries(
  test_scene_classifier_gtest ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES} sqlite3 pthread
  nlohmann_json::nlohmann_json cpp_dotenv ${CURL_LIBRARIES} ${POPPLER_LIBRARIES} duckx)

add_test(NAME SceneClassifierGTests COMMAND test_scene_classifier_gtest)

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
  ../src/integration/LLMIntegration/MarkitdownProxy.cpp
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
          test_compressed_log_parser
          test_journal_parser
          test_timestamp_normalizer
          test_auditd_aggregator
          test_log_tampering_detector
          test_persistence_detector
          test_middleware_log_parser
          test_container_runtime_log_parser
          test_package_manager_log_parser
          test_account_ssh_analyzer
          test_database_log_parser
          test_email_vpn_log_parser
          test_firewall_security_log_parser
          test_linux_enhanced_parsers_gtest
          test_scene_classifier_gtest
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
  ../src/integration/LLMIntegration/MarkitdownProxy.cpp
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
  ../src/analyzers/OSSAnalyzer/Database/OSSAnalysisDatabase_Queries.cpp
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
../src/analyzers/DatabaseAnalyzer/Database/DBAnalysisDatabase_Queries.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/DBParserFactory.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/SQLiteAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/SQLiteAnalyzer_Forensics.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLDaemon.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLAnalyzer.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLDaemon.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/MySQLBinlogParser.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/InnoDBParser.cpp
  ../src/analyzers/DatabaseAnalyzer/Parsers/PostgreSQLHeapParser.cpp
  ../src/core/PathManager/PathManager.cpp)

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

# DLL Analyzer Tests (SQL schema + data structures + database operations + PE parsers + anomaly detection)
add_executable(test_dll_analyzer_gtest
               UnitTest/test_dll_analyzer_gtest.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/PEImportExportParser.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/ELFParser.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/ELFParser_Sections.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/ELFParser_Dynamic.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/SignatureVerifier.cpp
               ../src/analyzers/DLLAnalyzer/Core/PEAnalyzer.cpp
               ../src/analyzers/DLLAnalyzer/Core/AnomalyDetector.cpp
               ../src/analyzers/DLLAnalyzer/Core/DependencyAnalyzer.cpp
               ../src/analyzers/DLLAnalyzer/Core/DLLAnalyzerCore.cpp
               ../src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.cpp
../src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase_Queries.cpp
               # Windows Files Analyzer (for forensic correlation)
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Prefetch.cpp
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Registry.cpp
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_EventLog.cpp
               ../src/core/AuditLog/AuditLog.cpp
               ../src/core/Logger/Logger.cpp
               ../src/core/ThreadPool/ThreadPool.cpp)

target_link_libraries(test_dll_analyzer_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread OpenSSL::SSL)

target_include_directories(test_dll_analyzer_gtest
                           PRIVATE ${CMAKE_SOURCE_DIR}/src
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Common
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Core
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Parsers
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Database
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Database
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Common
                                   ${CMAKE_SOURCE_DIR}/src/core
                                   ${CMAKE_SOURCE_DIR}/src/core/AuditLog
                                   ${CMAKE_SOURCE_DIR}/src/core/Logger
                                   ${CMAKE_SOURCE_DIR}/src/core/ThreadPool)

add_test(NAME DLLAnalyzerGTests COMMAND test_dll_analyzer_gtest)

# DLL Analyzer Integration Tests
add_executable(test_dll_analyzer_integration
               integration_dll_analyzer.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/PEHeaderParser.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/PEImportExportParser.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/ELFParser.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/ELFParser_Sections.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/ELFParser_Dynamic.cpp
               ../src/analyzers/DLLAnalyzer/Parsers/SignatureVerifier.cpp
               ../src/analyzers/DLLAnalyzer/Core/PEAnalyzer.cpp
               ../src/analyzers/DLLAnalyzer/Core/AnomalyDetector.cpp
               ../src/analyzers/DLLAnalyzer/Core/DependencyAnalyzer.cpp
               ../src/analyzers/DLLAnalyzer/Core/DLLAnalyzerCore.cpp
               ../src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.cpp
../src/analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase_Queries.cpp
               # Windows Files Analyzer (for forensic correlation)
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsAnalysisDatabase.cpp
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Prefetch.cpp
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_Registry.cpp
               ../src/analyzers/WindowsFilesAnalyzer/Database/WindowsDBOperations_EventLog.cpp
               ../src/core/AuditLog/AuditLog.cpp
               ../src/core/Logger/Logger.cpp
               ../src/core/ThreadPool/ThreadPool.cpp)

target_link_libraries(test_dll_analyzer_integration ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread OpenSSL::SSL)

target_include_directories(test_dll_analyzer_integration
                           PRIVATE ${CMAKE_SOURCE_DIR}/src
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Common
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Core
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Parsers
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Database
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Database
                                   ${CMAKE_SOURCE_DIR}/src/analyzers/WindowsFilesAnalyzer/Common
                                   ${CMAKE_SOURCE_DIR}/src/core
                                   ${CMAKE_SOURCE_DIR}/src/core/AuditLog
                                   ${CMAKE_SOURCE_DIR}/src/core/Logger
                                   ${CMAKE_SOURCE_DIR}/src/core/ThreadPool
                                   ${CMAKE_CURRENT_SOURCE_DIR})

target_compile_definitions(test_dll_analyzer_integration PRIVATE
    TEST_SAMPLES_DIR="${CMAKE_CURRENT_SOURCE_DIR}/samples")

add_test(NAME DLLAnalyzerIntegrationTests COMMAND test_dll_analyzer_integration)

# DLL Analyzer LLM Service Tests
add_executable(test_dll_analyzer_llm
               UnitTest/test_dll_analyzer_llm.cpp
               ../src/analyzers/DLLAnalyzer/Core/DLLAnalyzerLLMService.cpp
               ../src/core/ConfigManager/ConfigManager.cpp
               ../src/core/PathManager/PathManager.cpp
               ../src/core/Logger/Logger.cpp
               ../src/core/ThreadPool/ThreadPool.cpp
               ../src/integration/LLMIntegration/LLMClient.cpp
               ../src/integration/LLMIntegration/ModelRouter.cpp
               ../src/integration/LLMIntegration/FileAnalyzer.cpp
               ../src/integration/LLMIntegration/MarkitdownProxy.cpp
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
  test_dll_analyzer_llm
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Common
          ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Core
          ${CMAKE_SOURCE_DIR}/src/analyzers/DLLAnalyzer/Parsers
          ${CMAKE_SOURCE_DIR}/src/core
          ${CMAKE_SOURCE_DIR}/src/core/ConfigManager
          ${CMAKE_SOURCE_DIR}/src/core/PathManager
          ${CMAKE_SOURCE_DIR}/src/core/Logger
          ${CMAKE_SOURCE_DIR}/src/core/ThreadPool
          ${CMAKE_SOURCE_DIR}/src/integration/LLMIntegration
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/include
          ${CMAKE_SOURCE_DIR}/libs/cpp-mcp/common
          ${CMAKE_SOURCE_DIR}/src/analyzers/PDFAnalyzer
          ${CMAKE_SOURCE_DIR}/src/analyzers/OfficeAnalyzer)

target_link_libraries(test_dll_analyzer_llm ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} ${CURL_LIBRARIES} sqlite3 pthread
                      nlohmann_json::nlohmann_json cpp_dotenv duckx
                      ${POPPLER_LIBRARIES})

add_test(NAME DLLAnalyzerLLMTests COMMAND test_dll_analyzer_llm)

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

# Task Scenarios Tests (ForensicScenario enum, serialization, backward compat)
add_executable(
  test_task_scenarios
  UnitTest/test_task_scenarios_gtest.cpp
  ../src/network/HTTPServer/TaskSerialization.cpp
  ../src/core/PathManager/PathManager.cpp)

target_include_directories(test_task_scenarios PRIVATE ${CMAKE_SOURCE_DIR}/src)

target_link_libraries(test_task_scenarios ${GTEST_LIBRARIES} ${GMOCK_LIBRARIES}
                      nlohmann_json::nlohmann_json pthread)

add_test(NAME TaskScenarioTests COMMAND test_task_scenarios)

# WeChat Decryptor Tests (conditional on SQLCipher availability)
if(SQLCIPHER_FOUND)
  add_executable(
    test_wechat_decryptor_gtest
    UnitTest/test_wechat_decryptor_gtest.cpp
    ../src/analyzers/AndroidAnalyzer/WeChatDecryptor.cpp
    ../src/analyzers/AndroidAnalyzer/SqlCipherDatabase.cpp)

  target_include_directories(
    test_wechat_decryptor_gtest
    PRIVATE ${CMAKE_SOURCE_DIR}/src
            ${CMAKE_SOURCE_DIR}/src/analyzers/AndroidAnalyzer
            ${SQLCIPHER_INCLUDE_DIRS})

  target_link_libraries(
    test_wechat_decryptor_gtest
    ${GTEST_LIBRARIES}
    ${GMOCK_LIBRARIES}
    ${SQLCIPHER_LIBRARIES}
    OpenSSL::SSL
    OpenSSL::Crypto
    pthread)

  add_test(NAME WeChatDecryptorGTests COMMAND test_wechat_decryptor_gtest)
else()
  message(STATUS "Skipping WeChat decryptor tests - SQLCipher not found")
endif()

# WeChat Parser Tests (standalone - uses raw sqlite3 only, no SQLCipher needed)
add_executable(test_wechat_parser_gtest UnitTest/test_wechat_parser_gtest.cpp)

target_link_libraries(test_wechat_parser_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME WeChatParserGTests COMMAND test_wechat_parser_gtest)

# Install WeChat test targets
install(TARGETS test_wechat_parser_gtest RUNTIME DESTINATION bin/tests)

if(SQLCIPHER_FOUND)
  install(TARGETS test_wechat_decryptor_gtest RUNTIME DESTINATION bin/tests)
endif()

# Generic SQLCipher opener (extracted from WeChatDecryptor; used by Phase 2
# encrypted app-DB inventory). Requires the sqlcipher CLI at runtime.
if(SQLCIPHER_FOUND)
  add_executable(
    test_sqlcipher_database_gtest
    UnitTest/test_sqlcipher_database_gtest.cpp
    ../src/analyzers/AndroidAnalyzer/SqlCipherDatabase.cpp)

  target_include_directories(
    test_sqlcipher_database_gtest
    PRIVATE ${CMAKE_SOURCE_DIR}/src
            ${CMAKE_SOURCE_DIR}/src/analyzers/AndroidAnalyzer)

  target_compile_definitions(test_sqlcipher_database_gtest PRIVATE HAVE_SQLCIPHER)
  target_link_libraries(
    test_sqlcipher_database_gtest
    ${GTEST_LIBRARIES}
    ${GMOCK_LIBRARIES}
    ${SQLITE_LINK_LIBRARIES}
    pthread)

  add_test(NAME SqlCipherDatabaseGTests COMMAND test_sqlcipher_database_gtest)
  install(TARGETS test_sqlcipher_database_gtest RUNTIME DESTINATION bin/tests)
endif()

# Android logical-extraction source backends (dir / zip), bypassing TSK.
add_executable(
  test_android_logical_source_gtest
  UnitTest/test_android_logical_source_gtest.cpp
  ../src/analyzers/AndroidAnalyzer/LogicalDirExtractor.cpp
  ../src/analyzers/AndroidAnalyzer/ZipArchiveExtractor.cpp
  ../src/core/AuditLog/AuditLog.cpp)

target_include_directories(
  test_android_logical_source_gtest
  PRIVATE ${CMAKE_SOURCE_DIR}/src
          ${CMAKE_SOURCE_DIR}/src/core
          ${CMAKE_SOURCE_DIR}/src/analyzers/AndroidAnalyzer)

if(LIBZIP_FOUND)
  target_compile_definitions(test_android_logical_source_gtest PRIVATE HAVE_LIBZIP)
  target_include_directories(test_android_logical_source_gtest PRIVATE ${LIBZIP_INCLUDE_DIRS})
endif()

target_link_libraries(
  test_android_logical_source_gtest
  ${GTEST_LIBRARIES}
  ${GMOCK_LIBRARIES}
  sqlite3
  ${LIBZIP_LIBRARIES}
  pthread)

add_test(NAME AndroidLogicalSourceGTests COMMAND test_android_logical_source_gtest)
install(TARGETS test_android_logical_source_gtest RUNTIME DESTINATION bin/tests)

# Scene Database Tests (SQL schema definitions for scene specialization)
add_executable(test_scene_database_gtest UnitTest/test_scene_database_gtest.cpp
    ../src/core/DatabaseManager/EventExtractor/Detail/EventExtractorCore.cpp
    ../src/core/DatabaseManager/EventExtractor/Detail/FileSystemEventExtractor.cpp
    ../src/core/DatabaseManager/EventExtractor/Detail/SystemEventExtractor.cpp
    ../src/core/DatabaseManager/EventExtractor/Detail/EventCorrelationExtractor.cpp
    ../src/core/EventCorrelationEngine/Detail/EventCorrelationEngineCore.cpp
    ../src/core/EventCorrelationEngine/Detail/EventCorrelationAnalyzer.cpp
    ../src/core/EventCorrelationEngine/Detail/EventChainBuilder.cpp
    ../src/core/EventCorrelationEngine/Detail/EventCorrelationExporter.cpp
    ../src/core/EventCorrelationEngine/Detail/EventCorrelationUtils.cpp
    ../src/core/AuditLog/AuditLog.cpp)

target_include_directories(test_scene_database_gtest PRIVATE
    ${CMAKE_SOURCE_DIR}/src/core
    ${CMAKE_SOURCE_DIR}/src)

target_link_libraries(test_scene_database_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread
                      nlohmann_json::nlohmann_json)

add_test(NAME SceneDatabaseGTests COMMAND test_scene_database_gtest)

# Scene Performance Tests (LLM analysis optimization with scene specialization)
add_executable(test_scene_performance_gtest UnitTest/test_scene_performance_gtest.cpp)

target_link_libraries(test_scene_performance_gtest ${GTEST_LIBRARIES}
                      ${GMOCK_LIBRARIES} sqlite3 pthread)

add_test(NAME ScenePerformanceGTests COMMAND test_scene_performance_gtest)
