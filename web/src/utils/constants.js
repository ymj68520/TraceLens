// Task statuses
// interrupted / paused are the resumable stops: the task keeps its id, output
// directory and configuration, and can continue from its stage ledger.
export const TASK_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
  INTERRUPTED: 'interrupted',
  PAUSED: 'paused',
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
  // Amber/warning: not a terminal failure — work is preserved and resumable.
  interrupted: 'bg-amber-100 text-amber-800',
  paused: 'bg-sky-100 text-sky-800',
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

// Display names (zh) for task enums — values stay canonical for filtering/API.
export const TASK_STATUS_ZH = {
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断（可继续）',
  paused: '已暂停',
};

export const TASK_PRIORITY_ZH = {
  low: '低',
  normal: '普通',
  high: '高',
  critical: '紧急',
};

export const taskStatusZh = (s) => TASK_STATUS_ZH[(s || '').toLowerCase()] || s;
export const taskPriorityZh = (p) => TASK_PRIORITY_ZH[(p || '').toLowerCase()] || p;
