// Display labels only. Never apply these mappings to evidence text or identifiers.
const labels = {
  database_sidecar: '数据库配套文件', mmkv: 'MMKV 键值存储', shared_pref: '应用偏好设置',
  xlog: '运行日志', config: '配置文件', cache: '缓存文件',
  android_sparse_super: '稀疏 super 镜像', android_sparse_userdata: '稀疏用户数据镜像',
  android_super: '动态分区镜像', can_normalize: '可以规范化',
  fbe_detected: '检测到文件级加密', fde_detected: '检测到全盘加密',
  file: '文件证据', android_artifact: '手机派生记录', event_cluster: '事件聚合',
  included: '已纳入报告', excluded: '已排除', supports: '支持', contradicts: '存在相反证据',
  main: '主要证据', appendix: '附录证据', original_only: '仅原始材料',
  pending: '待处理', queued: '排队中', running: '运行中', completed: '已完成',
  failed: '失败', cancelled: '已取消', paused: '已暂停', unknown: '未知',
  low: '低', normal: '普通', high: '高', critical: '紧急', medium: '中',
  parsed: '已解析', staged_for_parser: '已提取，待核对解析结果',
  no_candidate_path: '未找到候选文件', not_found_or_unreadable: '未找到或无法读取',
  extract_failed: '提取失败', locked_or_unsupported: '加密或格式不支持',
  locked: '加密锁定', unsupported: '暂不支持', found: '已发现',
  not_found: '未找到', not_present: '备份中未包含', partial: '部分解析',
  not_present_in_source: '来源不含用户数据分区', unsupported_filesystem: '暂不支持的文件系统',
  not_applicable: '不适用', none: '无', plaintext: '明文', unencrypted: '未加密',
  readable: '可读取', encrypted: '已加密', encrypted_locked: '已发现但未解密',
  empty_manifest: '清单为空', schema_inventory: '已登记数据库表结构',
  not_resolved_in_backup: '未能在备份中定位对应文件',
  resolved: '已定位', available: '可用', missing: '缺失', verified: '已验证',
  unverified_source: '来源未经预检验证',
  completed_with_locked_userdata: '任务已完成，用户数据仍加密锁定',
  super_normalized_no_userdata: '已完成 super 规范化，来源不含用户数据分区',
  sms: '短信', sms_messages: '短信', contacts: '联系人', apps: '应用',
  installed_apps: '已安装应用', installed_packages: '安装包信息', wifi: '无线网络', wifi_networks: '无线网络',
  call_logs: '通话记录', calls: '通话记录', mobile: '鸿蒙记录', mobile_artifacts: '鸿蒙记录',
  calendar: '日历', recording: '录音', call_recording: '通话录音', media: '媒体元数据', media_file: '媒体文件',
  note: '备忘录', note_content: '备忘录内容', todo: '待办事项', note_block: '思源内容块',
  qq_contact: 'QQ 联系人', qq_group: 'QQ 群资料', qq_recent: 'QQ 最近会话',
  wechat: '微信', wechat_messages: '微信消息', whatsapp_messages: 'WhatsApp 消息', telegram_messages: 'Telegram 消息',
  wechat_sqlite_records: '微信数据库记录', wechat_kv_records: '微信键值记录', qqnt_sqlite_records: 'QQ 数据库记录',
  system_logs: '系统日志', device_identifiers: '设备标识', miui_backup_manifest: '小米备份清单',
  userdata: '用户数据分区', database: '数据库', backup: '备份',
  fact: '事实陈述', inference: '推断', hypothesis: '待验证假设',
  accepted: '已接受', rejected: '已拒绝', review_pending: '待复核',
  grounded: '引用证据存在', valid: '引用有效', partially_grounded: '部分引用待核对',
  ungrounded: '缺少证据依据', invalid: '无效', unresolved: '未解析',
  primary: '主要证据', supporting: '辅助证据', context: '背景材料', contradicting: '相反证据',
};

export const forensicLabel = (value, fallback = '其他') => {
  if (value === null || value === undefined || value === '') return '未记录';
  return labels[String(value).toLowerCase()] || (/\p{Script=Han}/u.test(String(value)) ? String(value) : fallback);
};

const fields = {
  id: '记录编号', kind: '记录类别', body: '内容', display_name: '名称',
  package_name: '应用包名', ssid: '无线网络名称', address: '号码或地址',
  date: '原始时间', type: '类型', phone_number: '电话号码', email: '邮箱',
  version: '版本', key_mgmt: '密钥管理方式', title: '标题', summary: '摘要',
  content: '内容', source_path: '来源路径', original_path: '原始路径',
  source_table: '来源表', source_pk: '来源主键', source_database: '来源数据库',
  source_sha256: '来源 SHA-256', source_wal_sha256: '来源 WAL SHA-256',
  app_index: '应用实例编号', bundle_name: '应用包名', parser_version: '解析器版本',
  timestamp: '时间戳', timestamp_raw: '原始时间戳', timestamp_unit: '时间单位',
  time_raw: '原始时间', time_unit: '时间单位', timezone: '时区',
  related_path: '关联文件路径', related_file_status: '关联文件状态',
  related_file_path: '关联文件路径', metadata_json: '原始结构化元数据',
  llm_summary: '智能分析摘要', llm_description: '智能分析说明',
  llm_keywords: '分析关键词', llm_model_used: '分析模型', llm_analyzed_at: '分析时间',
};
export const forensicFieldLabel = key => fields[key] || `原始字段（${key}）`;

const phases = {
  initializing: '正在初始化分析环境', image_analysis: '正在分析检材结构',
  file_classification: '正在筛选和分类文件', event_extraction: '正在提取时间线事件',
  llm_analysis: '正在进行智能分析', platform_analysis: '正在解析平台记录',
  file_carving: '正在恢复文件', finalizing: '正在整理分析结果', completed: '分析已完成',
};
export const taskPhaseLabel = phase => phases[String(phase || '').toLowerCase()] || '正在处理';
