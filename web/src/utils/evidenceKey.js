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
export const stripFileKeyPrefix = (evidenceKey) => (
    typeof evidenceKey === 'string' && evidenceKey.startsWith(FILE_KEY_PREFIX)
        ? evidenceKey.slice(FILE_KEY_PREFIX.length)
        : null
);

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
export const investigationFileUrl = (taskId, evidenceKey) => {
    const path = stripFileKeyPrefix(evidenceKey);
    if (!taskId || !path) return null;
    return `/investigation?task_id=${encodeURIComponent(taskId)}&file=${encodeURIComponent(path)}`;
};
