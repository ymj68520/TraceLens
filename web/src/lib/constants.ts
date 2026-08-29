export const TASK_STATUS = {
  PENDING: 'pending',
  RUNNING: 'running',
  COMPLETED: 'completed',
  FAILED: 'failed',
  CANCELLED: 'cancelled',
} as const;

export const TASK_PRIORITY = {
  LOW: 'low',
  NORMAL: 'normal',
  HIGH: 'high',
  CRITICAL: 'critical',
} as const;

export const TASK_PHASE = {
  INITIALIZING: 'initializing',
  IMAGE_ANALYSIS: 'image_analysis',
  EVENT_EXTRACTION: 'event_extraction',
  FILE_CLASSIFICATION: 'file_classification',
  LLM_ANALYSIS: 'llm_analysis',
  ANDROID_ANALYSIS: 'android_analysis',
  FINALIZING: 'finalizing',
} as const;

export const POLLING_INTERVALS = {
  fast: 2000,
  normal: 5000,
  slow: 10000,
} as const;

/** Chip color classes keyed by task status (light + dark aware). */
export const STATUS_CHIP: Record<string, string> = {
  pending: 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-500/10 dark:text-amber-300 dark:border-amber-500/20',
  running: 'bg-accent-50 text-accent-700 border border-accent-200 dark:bg-accent-500/10 dark:text-accent-300 dark:border-accent-500/20',
  completed: 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-500/10 dark:text-emerald-300 dark:border-emerald-500/20',
  failed: 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/20',
  cancelled: 'bg-ink-100 text-ink-600 border border-ink-200 dark:bg-ink-700/30 dark:text-ink-300 dark:border-ink-600/40',
};

export const PRIORITY_CHIP: Record<string, string> = {
  low: 'bg-ink-100 text-ink-600 border border-ink-200 dark:bg-ink-700/30 dark:text-ink-300 dark:border-ink-600/40',
  normal: 'bg-sky-50 text-sky-700 border border-sky-200 dark:bg-sky-500/10 dark:text-sky-300 dark:border-sky-500/20',
  high: 'bg-orange-50 text-orange-700 border border-orange-200 dark:bg-orange-500/10 dark:text-orange-300 dark:border-orange-500/20',
  critical: 'bg-rose-50 text-rose-700 border border-rose-200 dark:bg-rose-500/10 dark:text-rose-300 dark:border-rose-500/20',
};

export const PHASE_LABELS: Record<string, string> = {
  initializing: '初始化',
  image_analysis: '镜像分析',
  event_extraction: '事件提取',
  file_classification: '文件分类',
  llm_analysis: 'LLM 分析',
  android_analysis: '安卓分析',
  finalizing: '收尾',
};
