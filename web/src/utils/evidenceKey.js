// Evidence key 前端侧最小镜像工具。
//
// 后端冻结契约（python_service/httpserver/services/evidence/keys.py 与
// httpserver/path_utils.py）：
//   evidence key = file:<normalized_path> | cluster:v1:<unix_minute>:<encoded_event_type>
//   normalized_path 规则：反斜杠→斜杠、折叠重复分隔符、去尾部分隔符（根 "/" 保留），
//   不做小写化、不做点段解析。
// 此处只服务展示与深链跳转，绝不改写任何持久化身份。

export const FILE_KEY_PREFIX = 'file:';

// 解析可能带设备作用域的证据引用 (FQER: [scope:]type:path_or_id)
export const parseEvidenceReference = (evidenceKey) => {
    if (typeof evidenceKey !== 'string') return { scope: null, localKey: evidenceKey, path: null };
    let scope = null;
    let localKey = evidenceKey;
    const match = evidenceKey.match(/^([a-zA-Z0-9_\-]+):((?:file|cluster|android_artifact):.*)$/);
    if (match) {
        scope = match[1];
        localKey = match[2];
    }
    const path = localKey.startsWith('file:') ? localKey.slice(5) : null;
    return { scope, localKey, path };
};

// file: 前缀证据键 → 裸路径；支持 FQER (src_pc:file:/path)。非 file: 键返回 null。
export const stripFileKeyPrefix = (evidenceKey) => {
    if (typeof evidenceKey !== 'string') return null;
    if (evidenceKey.startsWith(FILE_KEY_PREFIX)) {
        return evidenceKey.slice(FILE_KEY_PREFIX.length);
    }
    const { path } = parseEvidenceReference(evidenceKey);
    return path;
};

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
    if (reportId) url += `&report_id=${encodeURIComponent(reportId)}`;
    if (citationId) url += `&citation_id=${encodeURIComponent(citationId)}`;
    return url;
};

// Only the exact frozen Android key can be linked: never replace it with a
// current-row ID or a file timeline path. Supports FQER scoped links.
export const investigationEvidenceUrl = (taskId, evidenceKey, options = {}) => {
    if (!evidenceKey || typeof evidenceKey !== 'string') return null;
    const { scope, localKey, path } = parseEvidenceReference(evidenceKey);
    if (path) {
        let url = `/investigation?task_id=${encodeURIComponent(taskId)}&file=${encodeURIComponent(path)}`;
        if (scope) url += `&source_scope=${encodeURIComponent(scope)}`;
        if (options.reportId) url += `&report_id=${encodeURIComponent(options.reportId)}`;
        if (options.citationId) url += `&citation_id=${encodeURIComponent(options.citationId)}`;
        return url;
    }
    if (!taskId) return null;
    if (localKey.startsWith(`android_artifact:v1:${taskId}:`) || localKey.startsWith('android_artifact:')) {
        let url = `/investigation?task_id=${encodeURIComponent(taskId)}&evidence_key=${encodeURIComponent(evidenceKey)}`;
        if (options.reportId) url += `&report_id=${encodeURIComponent(options.reportId)}`;
        if (options.citationId) url += `&citation_id=${encodeURIComponent(options.citationId)}`;
        return url;
    }
    return null;
};

export const reportCitationUrl = (taskId, reportId, citationId) => {
    if (!taskId || !reportId || !citationId) return null;
    return `/case-intelligence?task_id=${encodeURIComponent(taskId)}&tab=forensic&report_id=${encodeURIComponent(reportId)}&citation_id=${encodeURIComponent(citationId)}`;
};
