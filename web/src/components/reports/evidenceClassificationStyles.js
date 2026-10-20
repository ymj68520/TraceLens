// Shared display semantics for the frozen report annotations.
export const PRIORITIES = {
    P1: { label: 'P1 优先核查', order: 0, tone: 'border-orange-300 bg-orange-50 text-orange-900 dark:border-orange-700 dark:bg-orange-950/40 dark:text-orange-200' },
    P2: { label: 'P2 重点关注', order: 1, tone: 'border-blue-200 bg-blue-50 text-blue-800 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-200' },
    P3: { label: 'P3 一般参考', order: 2, tone: 'border-slate-200 bg-slate-100 text-slate-700 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-300' },
    unassessed: { label: '未评估／依据不足', order: 3, tone: 'border-dashed border-slate-400 bg-transparent text-slate-600 dark:border-slate-500 dark:text-slate-300' },
};
export const TOPICS = { funds: '资金活动', identity_accounts: '人员账号', communications: '通讯联系', location: '位置轨迹', network: '网络行为', tools: '工具配置' };

export function priorityStyle(value) {
    return PRIORITIES[value] || PRIORITIES.unassessed;
}
