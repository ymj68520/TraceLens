import api from './api';

export const searchFulltext = async (query, index, params = {}) => {
  return await api.get('/api/search/fulltext', {
    params: { q: query, index, ...params },
  });
};

export const createSearchIndex = async (sourcePath, indexPath, recursive = true) => {
  return await api.post('/api/search/index', {
    source_path: sourcePath,
    index_path: indexPath,
    recursive,
  });
};
