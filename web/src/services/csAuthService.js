import { csApi } from './api';

// Login uses the OAuth2 password flow -> form-encoded, NOT JSON. The endpoint
// depends on OAuth2PasswordRequestForm; a JSON body 422s. Passing URLSearchParams
// makes axios send application/x-www-form-urlencoded automatically.
export const csLogin = (username, password) => {
  const form = new URLSearchParams();
  form.append('username', username);
  form.append('password', password);
  return csApi.post('/api/auth/login', form);
};

export const csRefresh = (token) =>
  csApi.post('/api/auth/refresh', {}, { headers: { Authorization: `Bearer ${token}` } });

export const csMe = () => csApi.get('/api/auth/me');
