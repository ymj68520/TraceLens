# TraceLens client HTTP agent — standalone CMake project.
#
# Deliberately separate from the root ForensicAnalyzer build: the agent needs
# only cpp-httplib (header-only), OpenSSL (TLS), Threads, nlohmann/json, and
# SQLite3 (Task 18 in-flight command store) — NOT the heavy forensic deps
# (hivex/evtx/xapian/poppler/...) the root requires. SQLite is an ubiquitous
# lightweight dep and is the analyzer's own output format, so it stays within
# the standalone-build principle.
# Build & test directly:
#   cmake -S src/http_agent -B build/http_agent -DCMAKE_BUILD_TYPE=Release
#   cmake --build build/http_agent
#   ctest --test-dir build/http_agent --output-on-failure
#
# Wiring into the root build via add_subdirectory is forward work: the root
# configure currently hard-requires the forensic libs, so it must gain
# dep-gating first (see task-16 brief, design decision 3).

cmake_minimum_required(VERSION 3.16)
project(TraceLensHttpAgent LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

find_package(OpenSSL REQUIRED)
find_package(SQLite3 REQUIRED)
find_package(Threads REQUIRED)

set(AGENT_DIR ${CMAKE_CURRENT_SOURCE_DIR})
# httplib.h + json.hpp live here (vendored alongside cpp-mcp).
set(COMMON_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../libs/cpp-mcp/common)

add_library(tracelens_agent_lib STATIC
    http_client.cpp
    jwt_client.cpp
    poller.cpp
    status_reporter.cpp
    command_executor.cpp
    http_agent_service.cpp
    client_config.cpp
    process_runner.cpp
    result_uploader.cpp
    command_store.cpp
)
target_include_directories(tracelens_agent_lib PUBLIC
    ${AGENT_DIR}
    ${COMMON_DIR}
)
# httplib.h does NOT auto-detect OpenSSL: the consumer must define
# CPPHTTPLIB_OPENSSL_SUPPORT before including it (mirrors libs/cpp-mcp line 39),
# else an https:// URL silently falls back to plaintext.
target_compile_definitions(tracelens_agent_lib PUBLIC CPPHTTPLIB_OPENSSL_SUPPORT)
# OpenSSL include dir is propagated as a usage requirement by OpenSSL::SSL, and
# must precede cpp-httplib's own (per libs/cpp-mcp/CMakeLists.txt note).
target_include_directories(tracelens_agent_lib PRIVATE ${OPENSSL_INCLUDE_DIR})
target_link_libraries(tracelens_agent_lib PUBLIC
    OpenSSL::SSL OpenSSL::Crypto SQLite::SQLite3 Threads::Threads)

# The production agent executable.
add_executable(tracelens_agent http_agent_main.cpp)
target_link_libraries(tracelens_agent PRIVATE tracelens_agent_lib)

# Self-contained unit tests (no GTest, no live server).
add_executable(tracelens_agent_test tests/test_http_agent.cpp)
target_link_libraries(tracelens_agent_test PRIVATE tracelens_agent_lib)

enable_testing()
add_test(NAME http_agent_unit COMMAND tracelens_agent_test)
