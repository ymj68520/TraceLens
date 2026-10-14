import api, { pythonApi } from './api';
// 后端没有实现聚合的 /api/system/analysis-health；依赖状态由三个真实端点拼装。
export const getAnalysisHealth = async () => {
  const [graphiti, redis, llm] = await Promise.allSettled([
    pythonApi.get('/api/graphiti/status'),
    pythonApi.get('/api/system/redis/status'),
    pythonApi.get('/api/llm/status'),
  ]);
  const payload = (r) => (r.status === 'fulfilled' ? (r.value?.data ?? r.value) : undefined);
  const g = payload(graphiti);
  const r = payload(redis);
  const l = payload(llm);
  return {
    neo4j: { connected: g ? (g.neo4j_connected ?? g.status === 'connected') : false },
    redis: { connected: !!r?.connected },
    translation: { connected: l ? ['available', 'healthy'].includes(l.status) : false },
  };
};

export const getSystemHealth = async () => {
  return await api.get('/api/system/health');
};

export const getSystemInfo = async () => {
  return await api.get('/api/system/info');
};

export const getDatabases = async (params = {}) => {
  return await api.get('/api/system/databases', { params });
};

export const getDatabaseSchema = async (type) => {
  return await api.get(`/api/system/database-schema/${type}`);
};

export const getEndpoints = async () => {
  return await api.get('/api/docs/endpoints');
};

export const getDatabaseSchemaDocs = async () => {
  return await api.get('/api/docs/database-schema');
};

export const exportResults = async (taskId, format = 'json') => {
  return await api.post(`/api/export/${taskId}`, { format });
};

/** K8s-style health checks */
export const getHealthDependencies = async () => {
  return await api.get('/api/health/dependencies');
};

export const getLivenessCheck = async () => {
  return await api.get('/api/health/live');
};

/** Python service health check */
export const getPythonHealth = async () => {
  return await pythonApi.get('/health');
};

/** Redis service health check */
export const getRedisStatus = async () => {
  return await pythonApi.get('/api/system/redis/status');
};

/** TOON data export */
export const exportToon = async (taskId) => {
  // 服务端只注册了 GET（ExportRoutes.cpp），必须用 query 传 task_id。
  // 注意：api 实例的响应拦截器直接返回 response.data，这里拿到的就是 blob 本体。
  const data = await api.get('/api/forensics/export/toon', {
    params: { task_id: taskId },
    responseType: 'blob',
  });
  const blob = data instanceof Blob ? data : new Blob([data], { type: 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `task_${taskId.slice(0, 8)}.toon`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return data;
};
