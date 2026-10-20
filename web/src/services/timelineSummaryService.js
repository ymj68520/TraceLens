import { pythonApi } from './api';

export const getTimelineSummary = (endpoint, params) => pythonApi.get(endpoint, { params });
export const getTimelineSummaryRecords = (endpoint, params) => pythonApi.get(`${endpoint}/records`, { params });
