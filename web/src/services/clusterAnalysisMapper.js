/**
 * Mapping from event-cluster analysis records (append-only truth source,
 * GET /api/llm/event-cluster-analyses) to the legacy cluster-card shape the
 * AnalysisCenter evidence workspace renders (SPEC event-cluster-analysis-
 * redesign Phase D).
 *
 * Pure functions only — no API access — so the mapping is unit-testable.
 */

// Coordinate key shared by every version of one cluster grouping.
const coordinateKey = (record) =>
  [
    record.bucket_epoch_offset ?? 0,
    record.bucket_seconds,
    record.bucket_index,
    record.event_type,
    record.parent_directory,
  ].join('|');

const windowStart = (record) =>
  (record.bucket_index ?? 0) * (record.bucket_seconds ?? 60) +
  (record.bucket_epoch_offset ?? 0);

/**
 * @param {Array<Object>} records analysis rows (any order)
 * @returns {Array<Object>} card-shaped clusters with version metadata:
 *   { id, analysis_id, event_type, parent_directory, cluster_count, timestamp,
 *     llm_summary, llm_keywords, llm_analyzed_at, llm_model_used,
 *     trigger_source, ingested_at, coordinate_key, is_latest, versions }
 */
export const mapClusterAnalysisRecords = (records) => {
  const list = Array.isArray(records) ? records : [];
  const versionCounts = new Map();
  const latestIds = new Map();
  for (const record of list) {
    const key = coordinateKey(record);
    versionCounts.set(key, (versionCounts.get(key) || 0) + 1);
    const currentLatest = latestIds.get(key);
    if (!currentLatest || record.id > currentLatest) {
      latestIds.set(key, record.id);
    }
  }

  return list
    .slice()
    .sort((a, b) => (b.created_at || 0) - (a.created_at || 0))
    .map((record) => {
      const key = coordinateKey(record);
      return {
        id: record.id,
        analysis_id: record.id,
        event_type: record.event_type,
        parent_directory: record.parent_directory,
        cluster_count: record.member_count,
        bucket_seconds: record.bucket_seconds,
        bucket_index: record.bucket_index,
        timestamp: windowStart(record),
        llm_summary: record.summary,
        llm_keywords: record.keywords,
        llm_analyzed_at: record.created_at,
        llm_model_used: record.model,
        trigger_source: record.trigger_source,
        ingested_at: record.ingested_at,
        coordinate_key: key,
        is_latest: latestIds.get(key) === record.id,
        versions: versionCounts.get(key),
        // Legacy per-event relevance cache is not part of the record; the
        // card treats clusters as relevant unless a flag says otherwise.
        llm_is_relevant: 1,
        // Kept so the legacy relevance toggle keeps addressing the same
        // window when callers still pass it through.
        time_window: record.bucket_index,
      };
    });
};

/**
 * Distinct bucket windows present in the records, ascending — the bucket
 * filter options for the analyzed-clusters view.
 */
export const availableBucketSeconds = (records) => {
  const set = new Set(
    (Array.isArray(records) ? records : [])
      .map((record) => record.bucket_seconds)
      .filter((seconds) => Number.isFinite(seconds))
  );
  return [...set].sort((a, b) => a - b);
};
