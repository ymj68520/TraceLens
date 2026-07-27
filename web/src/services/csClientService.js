import { csApi } from './api';

export const listClients = (params = {}) => csApi.get('/api/clients', { params });
export const getClient = (clientId) => csApi.get(`/api/clients/${clientId}`);
