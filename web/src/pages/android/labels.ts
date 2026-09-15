/* ---------------------------------------------------------------------------
 * Chinese display names for the loosely shaped MIUI backup field keys, so
 * tables, drawers and CSV headers speak the same language across the page.
 * Unknown keys fall back to the raw field name everywhere.
 * ------------------------------------------------------------------------- */

export const ANDROID_FIELD_LABELS: Record<string, string> = {
  app_name: '应用名',
  package_name: '包名',
  backup_type: '备份类型',
  size_bytes: '大小(字节)',
  version_name: '版本',
  version_code: '版本号',
  source_dir: '来源目录',
  db_path: '数据库路径',
  app: '所属应用',
  table_count: '表数量',
  name: '名称',
  path: '路径',
  size: '大小',
  modified: '修改时间',
  title: '标题',
  timestamp: '时间',
  key: '字段',
  value: '值',
  open_status: '主库状态',
  summary: '摘要内容',
};
