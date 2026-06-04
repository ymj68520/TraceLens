/**
 * WeChat 微信聊天记录分析服务
 * 与 Python FastAPI 服务 (端口 8090) 通信
 */
import { pythonApi } from './api';

/**
 * 获取微信聊天关系图谱
 * @param {string} taskId - 任务 ID
 */
export const getWeChatGraph = async (taskId) => {
    return pythonApi.get('/api/wechat/graph', { params: { task_id: taskId } });
};

/**
 * 获取微信聊天时间线
 * @param {string} taskId - 任务 ID
 * @param {string} interval - 时间间隔 (day/week/month)
 */
export const getWeChatTimeline = async (taskId, interval = 'month') => {
    return pythonApi.get('/api/wechat/graph/timeline', { params: { task_id: taskId, interval } });
};

/**
 * 获取微信社交圈社区检测结果
 * @param {string} taskId - 任务 ID
 */
export const getWeChatCommunity = async (taskId) => {
    return pythonApi.get('/api/wechat/graph/community', { params: { task_id: taskId } });
};

/**
 * 获取指定联系人的详细信息
 * @param {string} taskId - 任务 ID
 * @param {string} username - 联系人用户名
 */
export const getWeChatPerson = async (taskId, username) => {
    return pythonApi.get(`/api/wechat/graph/person/${username}`, { params: { task_id: taskId } });
};

/**
 * 获取私聊聊天记录
 * @param {string} taskId - 任务 ID
 * @param {string} user1 - 用户 1
 * @param {string} user2 - 用户 2
 * @param {number} offset - 偏移量
 * @param {number} limit - 每页数量
 */
export const getWeChatChat = async (taskId, user1, user2, offset = 0, limit = 50) => {
    return pythonApi.get('/api/wechat/chat', {
        params: { task_id: taskId, user1, user2, offset, limit }
    });
};

/**
 * 获取群聊聊天记录
 * @param {string} taskId - 任务 ID
 * @param {string} chatroom - 群聊 ID
 * @param {number} offset - 偏移量
 * @param {number} limit - 每页数量
 */
export const getWeChatGroupChat = async (taskId, chatroom, offset = 0, limit = 50) => {
    return pythonApi.get('/api/wechat/chat/group', {
        params: { task_id: taskId, chatroom, offset, limit }
    });
};

/**
 * 获取微信账号主人信息
 * @param {string} taskId - 任务 ID
 */
export const getWeChatOwner = async (taskId) => {
    return pythonApi.get('/api/wechat/owner', { params: { task_id: taskId } });
};

/**
 * 获取微信联系人列表
 * @param {string} taskId - 任务 ID
 */
export const getWeChatContacts = async (taskId) => {
    return pythonApi.get('/api/wechat/contacts', { params: { task_id: taskId } });
};

/**
 * 使微信缓存失效并重新生成
 * @param {string} taskId - 任务 ID
 */
export const invalidateWeChatCache = async (taskId) => {
    return pythonApi.post('/api/wechat/graph/invalidate', null, { params: { task_id: taskId } });
};

export default {
    getWeChatGraph,
    getWeChatTimeline,
    getWeChatCommunity,
    getWeChatPerson,
    getWeChatChat,
    getWeChatGroupChat,
    getWeChatOwner,
    getWeChatContacts,
    invalidateWeChatCache,
};
