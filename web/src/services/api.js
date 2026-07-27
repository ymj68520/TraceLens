import axios from 'axios';

// Use relative path for Vite proxy
// C++ 后端 (端口 8080)
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
// Python 服务 (端口 8090)
const PYTHON_API_BASE_URL = import.meta.env.VITE_PYTHON_API_URL || 'http://localhost:8090';

// C++ 后端 API 客户端
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 seconds
});

// Python 服务 API 客户端
const pythonApi = axios.create({
  baseURL: PYTHON_API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 60000, // 60 seconds (LLM 请求可能较慢)
});

// Request interceptor
api.interceptors.request.use(
  (config) => {
    // Add auth token if available
    const token = localStorage.getItem('auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    console.log('API Request:', config.method?.toUpperCase(), config.url, config.data);
    return config;
  },
  (error) => {
    console.error('Request error:', error);
    return Promise.reject(error);
  }
);

// Response interceptor
api.interceptors.response.use(
  (response) => {
    console.log('API Response:', response.config.url, response.status, response.data);
    return response.data;
  },
  (error) => {
    console.error('Response error:', error.config?.url, error.message);
    console.error('Error details:', error.response?.data || error.response?.statusText);

    if (error.response?.status === 401) {
      // Handle unauthorized
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }

    // Create a more detailed error object
    const enhancedError = {
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: error.response?.data,
      config: error.config,
    };

    return Promise.reject(enhancedError);
  }
);

// Python API 请求拦截器
pythonApi.interceptors.request.use(
  (config) => {
    console.log('Python API Request:', config.method?.toUpperCase(), config.url, config.data);
    return config;
  },
  (error) => {
    console.error('Python API Request error:', error);
    return Promise.reject(error);
  }
);

// Python API 响应拦截器
pythonApi.interceptors.response.use(
  (response) => {
    console.log('Python API Response:', response.config.url, response.status, response.data);
    return response.data;
  },
  (error) => {
    console.error('Python API Response error:', error.config?.url, error.message);
    console.error('Error details:', error.response?.data || error.response?.statusText);

    // Create a more detailed error object
    const enhancedError = {
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: error.response?.data,
      config: error.config,
    };

    return Promise.reject(enhancedError);
  }
);

// 分布式 C/S 服务 (python_service/server) — 端口 8091.
// 不同于 pythonApi (旧版 httpserver :8090) 和 api (C++ :8080).
// baseURL 用相对路径 /csapi，经 Vite 代理转发到 :8091（与 api 客户端同模式，
// 避免 CORS）；生产环境可用 VITE_CS_API_URL 覆盖为绝对地址。
const CS_API_BASE_URL = import.meta.env.VITE_CS_API_URL || '/csapi';

const csApi = axios.create({
  baseURL: CS_API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30000, // 30 seconds
});

// 分布式服务请求拦截器（token 独立存于 cs_auth_token，与本地模式 auth_token 分离）
csApi.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('cs_auth_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    console.log('CS API Request:', config.method?.toUpperCase(), config.url, config.data);
    return config;
  },
  (error) => {
    console.error('CS API Request error:', error);
    return Promise.reject(error);
  }
);

// 分布式服务响应拦截器
csApi.interceptors.response.use(
  (response) => {
    console.log('CS API Response:', response.config.url, response.status, response.data);
    return response.data;
  },
  (error) => {
    console.error('CS API Response error:', error.config?.url, error.message);
    console.error('Error details:', error.response?.data || error.response?.statusText);

    // 401 仅清除分布式 token，不跳转 /login（分布式鉴权独立于本地模式）
    if (error.response?.status === 401) {
      localStorage.removeItem('cs_auth_token');
    }

    // Create a more detailed error object
    const enhancedError = {
      message: error.message,
      status: error.response?.status,
      statusText: error.response?.statusText,
      data: error.response?.data,
      config: error.config,
    };

    return Promise.reject(enhancedError);
  }
);

export { pythonApi, csApi };
export default api;

