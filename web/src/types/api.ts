/**
 * Shared backend payload types.
 *
 * The C++ and Python services return loosely-shaped JSON. These interfaces
 * capture the fields the UI actually relies on; unknown extras pass through
 * via index signatures where the backend is permissive.
 */

export type TaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
export type TaskPriority = 'low' | 'normal' | 'high' | 'critical';

export interface ForensicTask {
  id: string;
  image_path: string;
  status: TaskStatus | string;
  priority?: TaskPriority | string;
  phase?: string;
  progress?: number;
  case_description?: string;
  error_message?: string;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  llm_analyze?: boolean;
  android_analyze?: boolean;
  [key: string]: unknown;
}

export interface TaskListResponse {
  tasks: ForensicTask[];
  pagination?: { total: number; limit: number; offset: number };
}

export interface TaskStatistics {
  total?: number;
  pending?: number;
  running?: number;
  completed?: number;
  failed?: number;
  cancelled?: number;
  [key: string]: unknown;
}

export interface ForensicCase {
  id: string;
  name: string;
  description?: string;
  task_ids?: string[];
  status?: string;
  cross_analysis_job_id?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface TimelineEvent {
  id?: string | number;
  timestamp?: string;
  event_type?: string;
  file_path?: string;
  description?: string;
  source?: string;
  [key: string]: unknown;
}

export interface ClusterDescriptor {
  bucket_index: number;
  bucket_seconds: number;
  event_type: string;
  parent_directory: string;
}

export interface EventCluster {
  group_descriptor: ClusterDescriptor;
  event_count?: number;
  /** Backend alias: number of events merged into this cluster. */
  cluster_count?: number;
  sample_files?: string[];
  first_seen?: number | string;
  last_seen?: number | string;
  llm_summary?: string;
  [key: string]: unknown;
}

export interface FileRecord {
  id?: string | number;
  file_path: string;
  file_name?: string;
  file_size?: number;
  size?: number;
  file_type?: string;
  extension?: string;
  md5?: string;
  sha256?: string;
  created_time?: string;
  modified_time?: string;
  accessed_time?: string;
  deleted?: boolean | number;
  llm_description?: string;
  [key: string]: unknown;
}

export interface FilterProfile {
  name: string;
  description?: string;
  is_builtin?: boolean;
  [key: string]: unknown;
}

export interface HealthStatus {
  status: 'online' | 'offline' | 'checking';
  message?: string;
  latency?: number | null;
  data?: unknown;
}

export interface ApiError {
  message: string;
  status?: number;
  statusText?: string;
  data?: unknown;
}

export type JsonRecord = Record<string, unknown>;
