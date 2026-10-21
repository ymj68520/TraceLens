// graphConstants.js
// Shared constants for the Knowledge Graph page and its subcomponents.

// Node color palette by entity label. Keys are backend label values — do not
// rename; display text goes through NODE_LABEL_ZH.
export const NODE_COLORS = {
    Entity: '#6366f1',
    File: '#06b6d4',
    Process: '#f59e0b',
    User: '#10b981',
    Network: '#ec4899',
    Registry: '#8b5cf6',
    Event: '#ef4444',
    Directory: '#14b8a6',
    default: '#94a3b8',
};

// Display names for backend entity labels (keys stay English on purpose).
export const NODE_LABEL_ZH = {
    Entity: '实体',
    File: '文件',
    Process: '进程',
    User: '用户',
    Network: '网络',
    Registry: '注册表',
    Event: '事件',
    Directory: '目录',
};

// Resolve a node color by its label (falls back to slate).
export const getNodeColor = (label) => NODE_COLORS[label] || NODE_COLORS.default;

// Resolve the display name of a node label (falls back to the raw label, which
// may be a custom entity type name from the backend).
export const getNodeLabelZh = (label) => NODE_LABEL_ZH[label] || label;
