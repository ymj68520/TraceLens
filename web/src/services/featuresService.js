import { pythonApi } from './api';

/**
 * Feature switches surfaced by the python backend (GET /api/system/features).
 *
 * Single source of truth for the MVP UI trims — hidden nav entries, removed
 * LLM actions — so the web build always follows the server's flags
 * (mvp-phase1-acceptance SPEC §2). Defaults are the MVP form: disabled until
 * the backend says otherwise, so a slow/failed fetch never flashes features in.
 */

export const FEATURE_DEFAULTS = Object.freeze({
  event_llm_analysis_enabled: false,
  combined_case_enabled: false,
  workbench_llm_enabled: false,
});

let cache = null;
let inflight = null;

export const fetchFeatures = async () => {
  if (cache) return cache;
  if (!inflight) {
    inflight = pythonApi
      .get('/api/system/features')
      .then((data) => {
        cache = { ...FEATURE_DEFAULTS, ...(data || {}) };
        return cache;
      })
      .catch(() => ({ ...FEATURE_DEFAULTS }))
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
};

export const getCachedFeatures = () => cache || { ...FEATURE_DEFAULTS };
