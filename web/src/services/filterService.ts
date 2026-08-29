import api from './api';

/** File filter profiles — C++ backend. */

export const fetchFilterProfiles = () => api.get('/api/filter/profiles');

export const fetchFilterProfileDetail = (name: string) =>
  api.get(`/api/filter/profiles/${name}`);

export const createFilterProfile = (profileData: Record<string, unknown>) =>
  api.post('/api/filter/profiles', profileData);

export const deleteFilterProfile = (name: string) =>
  api.delete(`/api/filter/profiles/${name}`);

export const applyFilter = (taskId: string, profileName: string) =>
  api.post('/api/filter/apply', { task_id: taskId, profile_name: profileName });
