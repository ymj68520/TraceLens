// TimelineReconstructor.h
// Reconstruct unified timeline from Linux artifacts

#pragma once
#ifndef TIMELINE_RECONSTRUCTOR_H
#define TIMELINE_RECONSTRUCTOR_H

#include <string>
#include <vector>
#include <sqlite3.h>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Unified timeline from multiple Linux artifacts
 */
struct Timeline {
    std::vector<LinuxTimelineEvent> events;
    std::vector<TimelineGap> gaps;

    bool hasUnexplainedGaps() const;
};

/**
 * @brief Reconstructs timeline from Linux forensic data
 *
 * Merges events from system logs, authentication, shell history,
 * file access, and network activity into a single chronological timeline.
 */
class TimelineReconstructor {
public:
    /**
     * @brief Analysis result structure
     */
    struct ReconstructResult {
        Timeline timeline;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Construct timeline reconstructor
     *
     * @param dbPath Path to Linux analysis database
     */
    explicit TimelineReconstructor(const std::string& dbPath);

    /**
     * @brief Build unified timeline from all artifacts
     *
     * Merges and sorts events chronologically from all sources.
     *
     * @return Complete timeline with events and gaps
     */
    Timeline buildTimeline();

    /**
     * @brief Merge and sort events chronologically
     *
     * @return Vector of timeline events sorted by timestamp
     */
    std::vector<LinuxTimelineEvent> mergeEvents();

    /**
     * @brief Identify timeline gaps
     *
     * Looks for suspicious gaps in the event timeline that may
     * indicate log tampering or system compromise.
     *
     * @param events Timeline events to analyze
     * @return Vector of identified gaps
     */
    std::vector<TimelineGap> identifyGaps(const std::vector<LinuxTimelineEvent>& events);

private:
    std::string dbPath_;

    // Helper methods
    LinuxTimelineEvent createTimelineEvent(const std::string& source,
                                          const std::string& type,
                                          const std::string& description,
                                          int64_t timestamp);

    bool isSuspiciousGap(int64_t gapDuration, int64_t eventCount);

    // Helper to add events from SQL query
    void addEventsFromQuery(sqlite3* db, const char* query,
                           std::vector<LinuxTimelineEvent>& events);
};

} // namespace LinuxAnalysis

#endif // TIMELINE_RECONSTRUCTOR_H
