/**
 * 研判中心（AnalysisCenter）共享类型。
 * 仅类型定义；纯函数逻辑见 diff.ts / exporters.ts，状态机见 useAnalysisQueue.ts。
 */

/** /api/tasks/<id>/results 返回的 LLM 文件描述行。 */
export interface LlmDescriptionRow {
  file_path?: string;
  summary?: string;
  description?: string;
  keywords?: string[];
  is_relevant?: number | boolean;
  size?: number;
  [key: string]: unknown;
}

/** /api/forensics/timeline/clusters/analyzed 返回的事件簇行。 */
export interface ClusterRow {
  timestamp?: number;
  event_type?: string;
  parent_directory?: string;
  llm_summary?: string;
  llm_is_relevant?: number | boolean;
  file_path?: string;
  [key: string]: unknown;
}

/* ------------------------------- 队列 ---------------------------------- */

export type QueueItemStatus = 'pending' | 'running' | 'done' | 'failed';

/** 队列条目：整个任务的研判收集，或单个文件的 AI 分析。 */
export interface TaskQueueItem {
  kind: 'task';
  taskId: string;
  label: string;
  imagePath?: string;
}

export interface FileQueueItem {
  kind: 'file';
  taskId: string;
  filePath: string;
  filesDbPath?: string | null;
}

export type QueueItem = TaskQueueItem | FileQueueItem;

/** 单文件 AI 分析结果（analyzeContent 返回的 analysis 字段）。 */
export interface FileAnalysisResult {
  summary?: string;
  description?: string;
  keywords?: string[];
}

/** 一个任务研判结果的快照，用于对比与导出。 */
export interface TaskResultSnapshot {
  taskId: string;
  imagePath?: string;
  descriptions: LlmDescriptionRow[];
  clusters: ClusterRow[];
  finishedAt: number;
}

/** 队列 runner 的返回：按条目类型区分。 */
export type QueueRunResult =
  | { kind: 'task'; snapshot: TaskResultSnapshot }
  | { kind: 'file'; analysis?: FileAnalysisResult };

/** 队列条目运行时状态。 */
export interface QueueEntry {
  /** 与 key 相同：队列内唯一标识（task:<id> / file:<task>:<path>）。 */
  id: string;
  key: string;
  item: QueueItem;
  status: QueueItemStatus;
  error?: string;
  startedAt?: number;
  finishedAt?: number;
  result?: QueueRunResult;
}

/* ------------------------------- 历史 ---------------------------------- */

/** 最近研判历史（localStorage 持久化，最近 20 条）。 */
export interface AnalysisHistoryEntry {
  taskId: string;
  imagePath?: string;
  savedAt: string;
  fileCount: number;
  clusterCount: number;
  relevantCount: number;
}

/* ------------------------------- 对比 ---------------------------------- */

export type DiffRowStatus = 'same' | 'changed' | 'only-a' | 'only-b';

/** 两侧不一致的单个字段。 */
export interface FieldDiff {
  label: string;
  a: string;
  b: string;
}

export interface FileDiffRow {
  key: string;
  name: string;
  a: LlmDescriptionRow | null;
  b: LlmDescriptionRow | null;
  status: DiffRowStatus;
  fields: FieldDiff[];
}

export interface ClusterDiffRow {
  key: string;
  a: ClusterRow | null;
  b: ClusterRow | null;
  status: DiffRowStatus;
  fields: FieldDiff[];
}

export interface DiffSummary {
  same: number;
  changed: number;
  onlyA: number;
  onlyB: number;
}

/* ------------------------------ Drawer --------------------------------- */

export type DrawerTarget =
  | { kind: 'file'; taskId: string; row: LlmDescriptionRow }
  | { kind: 'cluster'; taskId: string; row: ClusterRow }
  | { kind: 'task'; snapshot: TaskResultSnapshot };
