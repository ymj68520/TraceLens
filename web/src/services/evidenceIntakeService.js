import { pythonApi } from './api';
import { PYTHON_API_BASE_URL } from '../config/runtime';

const BASE = '/api/evidence-intake';

export const listEvidenceCandidates = () => pythonApi.get(`${BASE}/candidates`);
export const startEvidencePreflight = (candidateId, fullHash = false, password = '', selectedSlot = 0) =>
  pythonApi.post(`${BASE}/jobs`, {
    candidate_id: candidateId, full_hash: fullHash,
    ...(password ? { password } : {}),
    ...(selectedSlot ? { selected_slot: selectedSlot } : {}),
  });
export const getEvidencePreflight = (jobId) =>
  pythonApi.get(`${BASE}/jobs/${encodeURIComponent(jobId)}`);
export const cancelEvidencePreflight = (jobId) =>
  pythonApi.post(`${BASE}/jobs/${encodeURIComponent(jobId)}/cancel`);
export const evidenceManifestUrl = (jobId) =>
  `${PYTHON_API_BASE_URL.replace(/\/$/, '')}${BASE}/jobs/${encodeURIComponent(jobId)}/manifest`;
export const getAndroidSourceCoverage = (taskId) =>
  pythonApi.get(`${BASE}/tasks/${encodeURIComponent(taskId)}/android-coverage`);
export const getAndroidArtifacts = (taskId, kind, query = '', page = 1) =>
  pythonApi.post(`${BASE}/tasks/${encodeURIComponent(taskId)}/android-artifacts/${encodeURIComponent(kind)}/search`, { query, page });
export const getAndroidArtifact = (taskId, kind, id) =>
  pythonApi.get(`${BASE}/tasks/${encodeURIComponent(taskId)}/android-artifacts/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
export const captureAndroidArtifact = (taskId, kind, id, recordHash, sourceRevision) =>
  pythonApi.post(`${BASE}/tasks/${encodeURIComponent(taskId)}/android-artifacts/${encodeURIComponent(kind)}/${encodeURIComponent(id)}/capture`,
    { record_hash: recordHash, source_revision: sourceRevision });
export const getFrozenAndroidArtifact = (taskId, resultSetId, kind, id) =>
  pythonApi.get(`${BASE}/tasks/${encodeURIComponent(taskId)}/android-result-sets/${encodeURIComponent(resultSetId)}/${encodeURIComponent(kind)}/${encodeURIComponent(id)}`);
export const androidCoverageManifestUrl = (taskId) =>
  `${PYTHON_API_BASE_URL.replace(/\/$/, '')}${BASE}/tasks/${encodeURIComponent(taskId)}/android-coverage-manifest`;
export const androidNormalizationManifestUrl = (taskId) =>
  `${PYTHON_API_BASE_URL.replace(/\/$/, '')}${BASE}/tasks/${encodeURIComponent(taskId)}/android-normalization-manifest`;
