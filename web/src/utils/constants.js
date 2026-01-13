// Task statuses
export const TASK_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
};

// Task priorities
export const TASK_PRIORITY = {
  LOW: 'low',
  NORMAL: 'normal',
  HIGH: 'high',
  CRITICAL: 'critical',
};

// Task phases
export const TASK_PHASE = {
  INITIALIZING: 'initializing',
  IMAGE_ANALYSIS: 'image_analysis',
  EVENT_EXTRACTION: 'event_extraction',
  FILE_CLASSIFICATION: 'file_classification',
  LLM_ANALYSIS: 'llm_analysis',
  ANDROID_ANALYSIS: 'android_analysis',
  FINALIZING: 'finalizing',
};

// Priority colors
export const PRIORITY_COLORS = {
  low: 'bg-gray-100 text-gray-800',
  normal: 'bg-blue-100 text-blue-800',
  high: 'bg-orange-100 text-orange-800',
  critical: 'bg-red-100 text-red-800',
};

// Status colors
export const STATUS_COLORS = {
  pending: 'bg-yellow-100 text-yellow-800',
  running: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-gray-100 text-gray-800',
};

// Phase labels
export const PHASE_LABELS = {
  initializing: 'Initializing',
  image_analysis: 'Image Analysis',
  event_extraction: 'Event Extraction',
  file_classification: 'File Classification',
  llm_analysis: 'LLM Analysis',
  android_analysis: 'Android Analysis',
  finalizing: 'Finalizing',
};

// Polling intervals (ms)
export const POLLING_INTERVALS = {
  fast: 2000,
  normal: 5000,
  slow: 10000,
};
