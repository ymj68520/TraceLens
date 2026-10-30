import axios from 'axios';
import {
  API_BASE_URL,
  CPP_BASE_URL,
  PYTHON_API_BASE_URL,
  CS_API_BASE_URL,
  SERVICE_TIMEOUTS,
} from '../config/runtime';
import { FIELD_AUTH_ENABLED } from '../config/runtime';
import { clearFieldSession, getFieldToken } from './fieldSession';

// C++ 后端 API 客户端
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: SERVICE_TIMEOUTS.cpp,
});

// Python 服务 API 客户端
const pythonApi = axios.create({
  baseURL: PYTHON_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: SERVICE_TIMEOUTS.python,
});

api.interceptors.request.use(
  (config) => {
    const token = FIELD_AUTH_ENABLED ? getFieldToken() : localStorage.getItem('auth_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  },
  (error) => Promise.reject(error)
);

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      clearFieldSession();
      localStorage.removeItem('auth_token'); // clear pre-field mock credentials
      localStorage.removeItem('auth_user');
      window.location.href = '/login';
    }
    return Promise.reject({
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: FIELD_AUTH_ENABLED ? { detail: 'Request failed' } : error.response?.data,
    });
  }
);

pythonApi.interceptors.request.use(
  (config) => {
    if (FIELD_AUTH_ENABLED && getFieldToken()) config.headers.Authorization = `Bearer ${getFieldToken()}`;
    // 同源演示部署的证据判定新行内容 API 门禁（evidence-intake）：
    // 令牌来自服务端 .env 经构建注入；现场部署由入口代理注入，与此互补。
    const fieldToken = import.meta.env.VITE_FIELD_API_TOKEN;
    if (fieldToken) config.headers['x-tracelens-field-token'] = fieldToken;
    return config;
  },
  (error) => Promise.reject(error)
);

pythonApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (FIELD_AUTH_ENABLED && error.response?.status === 401 &&
        !error.config?.url?.includes('/api/field-auth/login')) {
      clearFieldSession();
      window.location.href = '/login';
    }
    return Promise.reject({
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: FIELD_AUTH_ENABLED ? { detail: 'Request failed' } : error.response?.data,
    });
  }
);

// Distributed C/S service (python_service/server).
const csApi = axios.create({
  baseURL: CS_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: SERVICE_TIMEOUTS.cs,
});

csApi.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('cs_auth_token');
    if (token) config.headers.Authorization = `Bearer ${token}`;
    return config;
  },
  (error) => Promise.reject(error)
);

csApi.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) localStorage.removeItem('cs_auth_token');
    return Promise.reject({
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: FIELD_AUTH_ENABLED ? { detail: 'Request failed' } : error.response?.data,
    });
  }
);

export {
  pythonApi,
  csApi,
  CPP_BASE_URL,
  PYTHON_API_BASE_URL,
  PYTHON_API_BASE_URL as PYTHON_BASE_URL,
};
export default api;
