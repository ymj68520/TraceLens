/** WeChat chat-history analysis — Python sidecar. */
import { pythonApi } from './api';

export const getWeChatGraph = (taskId: string) =>
  pythonApi.get('/api/wechat/graph', { params: { task_id: taskId } });

export const getWeChatTimeline = (taskId: string, interval: 'day' | 'week' | 'month' = 'month') =>
  pythonApi.get('/api/wechat/graph/timeline', { params: { task_id: taskId, interval } });

export const getWeChatCommunity = (taskId: string) =>
  pythonApi.get('/api/wechat/graph/community', { params: { task_id: taskId } });

export const getWeChatPerson = (taskId: string, username: string) =>
  pythonApi.get(`/api/wechat/graph/person/${encodeURIComponent(username)}`, { params: { task_id: taskId } });

export const getWeChatChat = (taskId: string, user1: string, user2: string, offset = 0, limit = 50) =>
  pythonApi.get('/api/wechat/chat', { params: { task_id: taskId, user1, user2, offset, limit } });

export const getWeChatGroupChat = (taskId: string, chatroom: string, offset = 0, limit = 50) =>
  pythonApi.get('/api/wechat/chat/group', { params: { task_id: taskId, chatroom, offset, limit } });

export const getWeChatOwner = (taskId: string) =>
  pythonApi.get('/api/wechat/owner', { params: { task_id: taskId } });

export const getWeChatContacts = (taskId: string) =>
  pythonApi.get('/api/wechat/contacts', { params: { task_id: taskId } });

export const invalidateWeChatCache = (taskId: string) =>
  pythonApi.post('/api/wechat/graph/invalidate', null, { params: { task_id: taskId } });
