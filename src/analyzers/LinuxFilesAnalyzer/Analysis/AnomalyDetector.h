// AnomalyDetector.h
// Detects anomalous behavior patterns in Linux systems

#pragma once
#ifndef ANOMALY_DETECTOR_H
#define ANOMALY_DETECTOR_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"
#include "Common/LinuxAnalyzerErrors.h"

namespace LinuxAnalysis {

/**
 * @brief Detects anomalies in Linux system behavior
 *
 * Identifies suspicious patterns indicating potential attacks:
 * - Brute force login attempts
 * - Privilege escalation
 * - Data exfiltration
 * - Persistence mechanisms
 * - Unusual login patterns
 * - Suspicious processes
 */
class AnomalyDetector {
public:
    /**
     * @brief Analysis result structure
     */
    struct DetectionResult {
        std::vector<Anomaly> anomalies;
        LinuxAnalyzerError error;
        bool success = true;
    };

    /**
     * @brief Construct anomaly detector
     *
     * @param dbPath Path to Linux analysis database
     */
    explicit AnomalyDetector(const std::string& dbPath);

    /**
     * @brief Detect all types of anomalies
     *
     * Runs all anomaly detection algorithms and returns
     * comprehensive list of suspicious activities.
     *
     * @return Vector of detected anomalies
     */
    std::vector<Anomaly> detectAnomalies();

private:
    std::string dbPath_;

    // Specific anomaly detectors
    std::vector<Anomaly> detectBruteForceAttempts();
    std::vector<Anomaly> detectPrivilegeEscalation();
    std::vector<Anomaly> detectDataExfiltration();
    std::vector<Anomaly> detectPersistenceMechanisms();
    std::vector<Anomaly> detectUnusualLoginPatterns();
    std::vector<Anomaly> detectSuspiciousProcesses();

    // Helper methods
    int calculateSeverity(const Anomaly& anomaly);
    float calculateConfidence(const Anomaly& anomaly);

    Anomaly createAnomaly(const std::string& type,
                        const std::string& description,
                        int severity,
                        float confidence,
                        const std::string& evidence);
};

} // namespace LinuxAnalysis

#endif // ANOMALY_DETECTOR_H
