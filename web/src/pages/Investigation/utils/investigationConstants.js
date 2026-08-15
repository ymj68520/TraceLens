export const REVIEW_STATUS = {
  draft: { label: 'AI 草稿', variant: 'gray' },
  review_pending: { label: '待复核', variant: 'yellow' },
  confirmed: { label: '已确认', variant: 'green' },
  rejected: { label: '已排除', variant: 'red' },
};

export const ANALYSIS_STATUS = {
  queued: { label: '排队中', variant: 'gray' },
  running: { label: '分析中', variant: 'blue' },
  review_pending: { label: '待复核', variant: 'yellow' },
  accepted: { label: '已接受', variant: 'green' },
  rejected: { label: '已拒绝', variant: 'red' },
  failed: { label: '失败', variant: 'red' },
  invalid: { label: '无效', variant: 'red' },
};

export const ROLE_LABELS = {
  primary: '核心证据',
  supporting: '支持证据',
  context: '上下文',
  contradicting: '矛盾证据',
};

export const REPORT_LABELS = {
  main: '正文证据',
  appendix: '附件证据',
};

export const formatTimestamp = (value) => {
  if (!value) return '时间未知';
  const date = new Date(value * 1000);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN');
};

export const parseJson = (value, fallback = []) => {
  if (!value) return fallback;
  if (typeof value !== 'string') return value;
  try {
    return JSON.parse(value);
  } catch {
    return fallback;
  }
};
