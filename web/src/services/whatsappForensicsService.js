/**
 * WhatsApp 取证（WhatsApp Forensics）服务
 * 与 Python FastAPI 服务 (端口 8090) 的 /api/whatsapp/forensics/* 通信。
 * 导入来源：iOS WhatsApp 备份的 ChatStorage.sqlite（明文 Core Data），
 * 同目录下的 ContactsV2.sqlite / CallHistory.sqlite 自动一并导入。
 */
import { pythonApi } from './api';

/** 创建 WhatsApp 取证导入（传入 ChatStorage.sqlite 路径或其所在目录） */
export const createWhatsAppImport = async (payload) =>
    pythonApi.post('/api/whatsapp/forensics/imports', payload);

/** 导入列表 */
export const listWhatsAppImports = async () =>
    pythonApi.get('/api/whatsapp/forensics/imports');

/** 单个导入摘要 */
export const getWhatsAppImport = async (importId) =>
    pythonApi.get(`/api/whatsapp/forensics/imports/${importId}`);

/** 删除导入 */
export const deleteWhatsAppImport = async (importId) =>
    pythonApi.delete(`/api/whatsapp/forensics/imports/${importId}`);

/** 取证概览（统计/消息类型分布/每日活跃/热门会话） */
export const getWhatsAppForensicsOverview = async (importId) =>
    pythonApi.get(`/api/whatsapp/forensics/imports/${importId}/overview`);

/** 会话列表（私聊对象与群聊，含显示名与最后消息预览） */
export const getWhatsAppSessions = async (importId) =>
    pythonApi.get(`/api/whatsapp/forensics/imports/${importId}/sessions`);

/** 消息查询（支持会话/类型/关键词/时间过滤与分页） */
export const getWhatsAppMessages = async (importId, params = {}) =>
    pythonApi.get(`/api/whatsapp/forensics/imports/${importId}/messages`, { params });

/** 联系人列表 */
export const getWhatsAppContacts = async (importId) =>
    pythonApi.get(`/api/whatsapp/forensics/imports/${importId}/contacts`);

/** 群聊列表（含群名与消息数） */
export const getWhatsAppChatrooms = async (importId) =>
    pythonApi.get(`/api/whatsapp/forensics/imports/${importId}/chatrooms`);
