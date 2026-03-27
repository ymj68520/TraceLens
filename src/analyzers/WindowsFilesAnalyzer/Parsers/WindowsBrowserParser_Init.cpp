// WindowsBrowserParser_Init.cpp
// Constructor and destructor for WindowsBrowserParser

#include "WindowsBrowserParser.h"

WindowsBrowserParser::WindowsBrowserParser() {
    // Initialize member variables
}

WindowsBrowserParser::~WindowsBrowserParser() {
    // Cleanup if needed
}

int64_t WindowsBrowserParser::chromiumTimeToUnix(int64_t chromiumTime) {
    // Chrome uses microseconds since 1601-01-01
    // Convert to Unix timestamp (seconds since 1970-01-01)
    return (chromiumTime / 1000000) - 11644473600;
}

int64_t WindowsBrowserParser::firefoxTimeToUnix(int64_t prTime) {
    // Firefox uses microseconds since 1970-01-01
    // Already Unix timestamp, just convert from microseconds
    return prTime / 1000000;
}