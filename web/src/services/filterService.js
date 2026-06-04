import api from './api';

/**
 * Filter Profile API Service
 *
 * Provides methods for managing file filter profiles through the C++ backend.
 */

// GET /api/filter/profiles - List all available filter profiles
export const fetchFilterProfiles = async () => {
  return await api.get('/api/filter/profiles');
};

// GET /api/filter/profiles/:name - Get profile details
export const fetchFilterProfileDetail = async (name) => {
  return await api.get(`/api/filter/profiles/${name}`);
};

// POST /api/filter/profiles - Create or update a filter profile
export const createFilterProfile = async (profileData) => {
  return await api.post('/api/filter/profiles', profileData);
};

// DELETE /api/filter/profiles/:name - Delete a custom filter profile
export const deleteFilterProfile = async (name) => {
  return await api.delete(`/api/filter/profiles/${name}`);
};

// POST /api/filter/apply - Apply filter to a task
export const applyFilter = async (taskId, profileName) => {
  return await api.post('/api/filter/apply', {
    task_id: taskId,
    profile_name: profileName,
  });
};
