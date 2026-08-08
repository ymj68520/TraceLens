#pragma once
#ifndef SCENE_DETECTOR_H
#define SCENE_DETECTOR_H

#include <map>
#include <string>
#include <vector>

#include "HTTPServerDataTypes.h"      // ForensicScenario
#include "../../core/DatabaseManager/FileClassifier/FileClassifier.h"  // SceneType

/**
 * SceneDetector
 *
 * Auto-detects which platform scenarios (Android / Windows / Linux /
 * Server-Cloud) are present in an evidence image by probing the *un-filtered*
 * raw database's `files` table for tell-tale artifact paths.
 *
 * This lets the UI drop the mandatory "取证场景" multi-select: when the user
 * does not explicitly pick scenarios, the backend infers them from the image
 * content. Detection runs after image extraction (raw DB populated) and before
 * file classification / platform-specific analysis.
 *
 * The detection is read-only (COUNT queries against `files`); it never mutates
 * the database and does not depend on any filter profile.
 */

/**
 * Result of a scene-detection pass.
 */
struct SceneDetection {
    /// Number of matching files per scenario (only keys with count > 0 are
    /// guaranteed meaningful, but every enum value is always present).
    std::map<ForensicScenario, int> counts;

    /// Scenarios whose marker count > 0, ordered by count descending. Ties are
    /// broken by a fixed priority order (android > windows > linux >
    /// server_cloud) for deterministic results.
    std::vector<ForensicScenario> detected;

    /// The single scene with the highest marker count (SceneType::NONE if
    /// nothing matched). Drives FileClassifier / LLMAnalysisService scene-aware
    /// scoring, which only consumes one scene at a time.
    SceneType dominant = SceneType::NONE;

    /// false if the raw DB could not be opened or queried; callers should treat
    /// a failed detection as "no scenarios" and leave downstream behavior as-is.
    bool ok = false;
};

/**
 * Probe the given raw database for platform artifacts.
 *
 * @param rawDbPath  Path to the *un-filtered* `<image>_raw.db`. Must NOT be the
 *                   filter output (`_filtered.db`), since filter profiles drop
 *                   system noise — exactly the marker paths we look for.
 * @return  SceneDetection with per-scenario counts, the detected list, and the
 *          dominant SceneType.
 */
SceneDetection detectScenes(const std::string& rawDbPath);

#endif  // SCENE_DETECTOR_H
