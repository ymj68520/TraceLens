import api from './api';

export const searchFulltext = (query: string, index: string, params: Record<string, unknown> = {}) =>
  api.get('/api/search/fulltext', { params: { q: query, index, ...params } });

export const createSearchIndex = (sourcePath: string, indexPath: string, recursive = true) =>
  api.post('/api/search/index', { source_path: sourcePath, index_path: indexPath, recursive });
