// Evidence key 前端侧最小镜像工具。
//
// 后端冻结契约（python_service/httpserver/services/evidence/keys.py 与
// httpserver/path_utils.py）：
//   evidence key = file:<normalized_path> | cluster:v1:<unix_minute>:<encoded_event_type>
//   normalized_path 规则：反斜杠→斜杠、折叠重复分隔符、去尾部分隔符（根 "/" 保留），
//   不做小写化、不做点段解析。
// 此处只服务展示与深链跳转，绝不改写任何持久化身份。

export const FILE_KEY_PREFIX = 'file:';

// file: 前缀证据键 → 裸路径；非 file: 键返回 null（时间线没有对应文件落点）。
export const fileSourceId = (key) => /^file:v2:([0-9a-f]{64}):/.exec(key || '')?.[1] || null;
export const stripFileKeyPrefix = (key) => {
    if (typeof key !== 'string' || !key.startsWith(FILE_KEY_PREFIX)) return null;
    if (key.startsWith('file:v2:')) {
        const match = /^file:v2:([0-9a-f]{64}):(.*)$/s.exec(key);
        try { return match ? decodeURIComponent(match[2]) : null; } catch { return null; }
    }
    return key.slice(FILE_KEY_PREFIX.length);
};
const encodePath = (path) => encodeURIComponent(path).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);
export const fileEvidenceKey = (file) => file.evidence_key || (file.source_id
    ? `file:v2:${file.source_id}:${encodePath(file.path || file.file_path)}` : `file:${file.path || file.file_path}`);
export const fileSourceReference = (file) => file.source_reference || (file.source_id
    ? `source:v1:${file.source_id}:${file.path || file.file_path}` : (file.path || file.file_path));

// 与后端 normalize_evidence_path 相同的冻结规则，用于深链参数与时间线
// path 的容错匹配（时间线 path 本已是规范形，此函数主要兜底 URL 传入形）。
export const normalizeEvidencePath = (value) => {
    if (!value) return '';
    let p = String(value).replace(/\\/g, '/').replace(/\/{2,}/g, '/');
    if (p.length > 1) p = p.replace(/\/+$/, '');
    return p || '/';
};

// file: 证据键 → /investigation 文件深链。新标签页打开后由工作台 ?file=
// 深链定位时间线文件；缺 taskId 或非 file: 键返回 null，调用方渲染纯文本。
export const investigationFileUrl = (taskId, evidenceKey, { reportId, citationId } = {}) => {
    const path = stripFileKeyPrefix(evidenceKey);
    if (!taskId || !path) return null;
    let url = `/investigation?task_id=${encodeURIComponent(taskId)}&file=${encodeURIComponent(path)}`;
    if (fileSourceId(evidenceKey)) url += `&evidence_key=${encodeURIComponent(evidenceKey)}`;
    if (reportId) url += `&report_id=${encodeURIComponent(reportId)}`;
    if (citationId) url += `&citation_id=${encodeURIComponent(citationId)}`;
    return url;
};

// Only the exact frozen Android key can be linked: never replace it with a
// current-row ID or a file timeline path.
export const investigationEvidenceUrl = (taskId, evidenceKey, options = {}) => {
    if (evidenceKey?.startsWith('file:')) return investigationFileUrl(taskId, evidenceKey, options);
    if (!taskId || typeof evidenceKey !== 'string' ||
        !evidenceKey.startsWith(`android_artifact:v1:${taskId}:`) && !evidenceKey.startsWith(`windows_artifact:v1:${taskId}:`)) return null;
    let url = `/investigation?task_id=${encodeURIComponent(taskId)}&evidence_key=${encodeURIComponent(evidenceKey)}`;
    if (options.reportId) url += `&report_id=${encodeURIComponent(options.reportId)}`;
    if (options.citationId) url += `&citation_id=${encodeURIComponent(options.citationId)}`;
    return url;
};

export const reportCitationUrl = (taskId, reportId, citationId) => {
    if (!taskId || !reportId || !citationId) return null;
    return `/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic&report_id=${encodeURIComponent(reportId)}&citation_id=${encodeURIComponent(citationId)}`;
};
