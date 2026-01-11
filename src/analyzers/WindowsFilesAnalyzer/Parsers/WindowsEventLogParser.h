// WindowsEventLogParser.h
// Event Log (EVTX) parser using libevtx library
// Provides RAII wrappers and helper functions for EVTX parsing

#pragma once
#ifndef WINDOWS_EVENT_LOG_PARSER_H
#define WINDOWS_EVENT_LOG_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <memory>
#include <utility>

// libevtx library (C library)
#include <libevtx.h>

// Forward declarations
struct EventLogEntry;

// ============================================================================
// RAII Wrapper for libevtx_file_t
// Manages the lifecycle of EVTX file handles
// ============================================================================
class EvtxFileHandle {
public:
    // Opens EVTX file in constructor
    explicit EvtxFileHandle(const std::string& path);

    // Closes and frees file handle in destructor
    ~EvtxFileHandle();

    // Disable copying - file handles cannot be copied
    EvtxFileHandle(const EvtxFileHandle&) = delete;
    EvtxFileHandle& operator=(const EvtxFileHandle&) = delete;

    // Enable move semantics for transfer of ownership
    EvtxFileHandle(EvtxFileHandle&& other) noexcept;
    EvtxFileHandle& operator=(EvtxFileHandle&& other) noexcept;

    // Check if file handle is valid
    bool isValid() const { return file_ != nullptr; }

    // Get raw libevtx file pointer
    libevtx_file_t* get() const { return file_; }

    // Allow implicit conversion to libevtx_file_t*
    operator libevtx_file_t*() const { return file_; }

private:
    libevtx_file_t* file_ = nullptr;
};

// ============================================================================
// RAII Wrapper for libevtx_record_t
// Manages the lifecycle of EVTX record handles
// ============================================================================
class EvtxRecordHandle {
public:
    // Takes ownership of an existing record pointer
    explicit EvtxRecordHandle(libevtx_record_t* record = nullptr);

    // Frees record handle in destructor
    ~EvtxRecordHandle();

    // Disable copying
    EvtxRecordHandle(const EvtxRecordHandle&) = delete;
    EvtxRecordHandle& operator=(const EvtxRecordHandle&) = delete;

    // Enable move semantics
    EvtxRecordHandle(EvtxRecordHandle&& other) noexcept;
    EvtxRecordHandle& operator=(EvtxRecordHandle&& other) noexcept;

    // Check if record handle is valid
    bool isValid() const { return record_ != nullptr; }

    // Get raw libevtx record pointer
    libevtx_record_t* get() const { return record_; }

    // Release ownership of the record pointer (caller takes responsibility)
    libevtx_record_t* release();

private:
    libevtx_record_t* record_ = nullptr;
};

// ============================================================================
// Helper Functions for EVTX Parsing
// ============================================================================
namespace EvtxHelpers {

/**
 * Convert Windows event level (1-5) to human-readable string
 * @param level Event level number (1=Critical, 2=Error, 3=Warning, 4=Information, 5=Verbose)
 * @return String representation of the level
 */
std::string eventLevelToString(uint8_t level);

/**
 * Convert Windows FILETIME to Unix timestamp
 * @param filetime Windows FILETIME (100-nanosecond intervals since Jan 1, 1601)
 * @return Unix timestamp (seconds since Jan 1, 1970)
 */
int64_t filetimeToUnixTime(uint64_t filetime);

/**
 * Extract user SID from event XML data
 * Looks for common XML patterns like SubjectUserName, UserId, UserName
 * @param xmlString XML string from event record
 * @return Extracted user SID or default "S-1-0-0" if not found
 */
std::string extractUserDataFromXML(const std::string& xmlString);

/**
 * Extract log source (e.g., "System", "Security") from file path
 * @param logPath Full path to EVTX file
 * @return Log source name extracted from filename
 */
std::string getLogSourceFromPath(const std::string& logPath);

} // namespace EvtxHelpers

#endif // WINDOWS_EVENT_LOG_PARSER_H
