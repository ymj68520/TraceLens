import axios, { AxiosError, type AxiosInstance, type AxiosResponse } from 'axios';

declare module 'axios' {
  // The response interceptor unwraps `response.data`, so callers receive the
  // payload directly — type the whole client surface accordingly.
  export interface AxiosInstance {
    get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T>;
    post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>;
    put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>;
    delete<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<T>;
    patch<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T>;
  }
}
import type { ApiError } from '../types/api';

/**
 * Three backends are in play:
 *  - C++ core      (:8080, same-origin via Vite proxy)
 *  - Python sidecar (:8090 — LLM, Graphiti, reports, WeChat, investigation)
 *  - C/S server    (:8091 — distributed mode, separate auth token)
 *
 * When the UI is opened from another machine, `localhost` would point at the
 * viewer's own box, so the Python/C-S base URLs are derived from the current
 * window hostname. VITE_* env vars still win when set.
 *
 * All clients unwrap `response.data` in their response interceptor, so
 * service callers receive the payload directly (typed as `unknown`).
 */

const CPP_PORT = import.meta.env.VITE_CPP_PORT || import.meta.env.HTTP_SERVER_PORT || '8080';
const PYTHON_PORT = '8090';
const CS_PORT = '8091';

function currentHost(): string {
  if (typeof window !== 'undefined' && window.location) {
    return window.location.hostname;
  }
  return 'localhost';
}

export const CPP_BASE_URL =
  import.meta.env.VITE_CPP_API_URL || `http://${currentHost()}:${CPP_PORT}`;
export const PYTHON_API_BASE_URL =
  import.meta.env.VITE_PYTHON_API_URL || `http://${currentHost()}:${PYTHON_PORT}`;
export const PYTHON_BASE_URL = PYTHON_API_BASE_URL;
export const CS_API_BASE_URL =
  import.meta.env.VITE_CS_API_URL || `http://${currentHost()}:${CS_PORT}`;

function toApiError(error: AxiosError): ApiError {
  return {
    message: error.message,
    status: error.response?.status,
    statusText: error.response?.statusText,
    data: error.response?.data,
  };
}

/** C++ backend client — same-origin, goes through the Vite proxy in dev. */
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response: AxiosResponse) => response.data as never,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('auth_token');
      window.location.href = '/login';
    }
    return Promise.reject(toApiError(error));
  },
);

/** Python sidecar client — LLM calls can be slow, hence the longer timeout. */
export const pythonApi: AxiosInstance = axios.create({
  baseURL: PYTHON_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 60_000,
});

pythonApi.interceptors.response.use(
  (response: AxiosResponse) => response.data as never,
  (error: AxiosError) => Promise.reject(toApiError(error)),
);

/**
 * Distributed C/S server client. Auth token lives under its own key —
 * a 401 here must NOT bounce the user to /login, since distributed auth is
 * independent from local mode.
 */
export const csApi: AxiosInstance = axios.create({
  baseURL: CS_API_BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
});

csApi.interceptors.request.use((config) => {
  const token = localStorage.getItem('cs_auth_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

csApi.interceptors.response.use(
  (response: AxiosResponse) => response.data as never,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('cs_auth_token');
    }
    return Promise.reject(toApiError(error));
  },
);

export default api;
