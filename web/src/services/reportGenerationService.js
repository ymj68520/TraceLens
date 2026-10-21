/**
 * Report Generation / Narrative Viewer 服务（R2d）。
 *
 * 只消费 R2c 冻结契约：
 *  - POST /api/reports/generate 请求体只有 task_id + requested_by；
 *    evidence 集合、analysis 绑定、prompt 版本、模型、envelope 全部由
 *    服务端从 R1 Report Evidence 冻结，客户端一律不得提交。
 *  - GET /api/reports/generations/{generation_id} 按 exact generation_id
 *    轮询（query 携带 task_id 做 scope 校验），绝无 "latest" 回退。
 *  - GET /api/reports/narrative/versions/{report_id} 是已发布叙事版本的
 *    strict task-scoped 读面（含 persisted citation manifest）。
 */
import { pythonApi } from './api';

/**
 * 发起一次 frozen generation admission（202）。
 * 返回的 exact generation_id 是唯一轮询身份。
 */
export const generateReport = async (taskId, { requestedBy }) => {
    return await pythonApi.post('/api/reports/generate', {
        task_id: taskId,
        requested_by: requestedBy,
    });
};

/**
 * 发起一次案件维度的跨镜像综合报告 generation admission（202）。
 */
export const generateCaseReport = async (caseId, { requestedBy, overrideDescription }) => {
    return await pythonApi.post('/api/reports/generate/case', {
        case_id: caseId,
        requested_by: requestedBy,
        override_description: overrideDescription,
    });
};

/**
 * 按 exact generation_id 读取一个 generation 的当前状态（支持 task 或 case 作用域）。
 */
export const getReportGeneration = async (scopeId, generationId, { scopeType = 'task' } = {}) => {
    const params = scopeType === 'case' ? { case_id: scopeId } : { task_id: scopeId };
    return await pythonApi.get(
        `/api/reports/generations/${encodeURIComponent(generationId)}`,
        { params },
    );
};

/**
 * 按 exact report_id 读取一个已发布 narrative report version
 * （版本行 + persisted manifest：sections + citation manifest + audit 元数据）。
 */
export const getNarrativeReport = async (scopeId, reportId, { scopeType = 'task' } = {}) => {
    const params = scopeType === 'case' ? { case_id: scopeId } : { task_id: scopeId };
    return await pythonApi.get(
        `/api/reports/narrative/versions/${encodeURIComponent(reportId)}`,
        { params },
    );
};

export default {
    generateReport,
    generateCaseReport,
    getReportGeneration,
    getNarrativeReport,
};
