/**
 * Column definitions for the generic artifact tables.
 *
 * Maps a section_id → ordered list of { key, label, format? }.
 * `key` matches the record field from the backend; `label` is the Chinese
 * column header; `format` is an optional formatter from ./shared.
 *
 * GenericArtifactTable renders whichever of these keys are present in the
 * returned records. Unknown section_ids fall back to rendering every record
 * field with its raw key name — so adding a backend section needs no frontend
 * change to be visible.
 */
import { fmtTime, fileSize, callTypeLabel } from './reportSectionUtils';

export const ARTIFACT_COLUMNS = {
  // ── Android ──
  contacts: [
    { key: 'display_name', label: '姓名' },
    { key: 'phone_number', label: '号码' },
    { key: 'email', label: '邮箱' },
    { key: 'account_type', label: '账户类型' },
    { key: 'account_name', label: '账户名' },
  ],
  call_logs: [
    { key: 'name', label: '姓名' },
    { key: 'number', label: '号码' },
    { key: 'type', label: '呼叫类型', format: callTypeLabel },
    { key: 'date', label: '通话时间', format: fmtTime },
    { key: 'duration', label: '持续时长', format: (s) => {
      if (s === null || s === undefined || s === '') return '—';
      const n = Number(s);
      if (!Number.isFinite(n) || n < 0) return '—';
      if (n === 0) return '0秒';
      const h = Math.floor(n / 3600); const m = Math.floor((n % 3600) / 60); const sec = Math.floor(n % 60);
      const p = []; if (h) p.push(`${h}时`); if (m || h) p.push(`${m}分`); p.push(`${sec}秒`); return p.join('');
    } },
    { key: 'geocoded_location', label: '归属地' },
  ],
  locations: [
    { key: 'file_name', label: '文件名称' },
    { key: 'longitude', label: '经度' },
    { key: 'latitude', label: '纬度' },
    { key: 'ssid', label: 'SSID' },
    { key: 'file_size', label: '文件大小', format: fileSize },
    { key: 'created_time', label: '创建时间', format: fmtTime },
    { key: 'file_path', label: '文件路径' },
  ],
  apps: [
    { key: 'display_name', label: '名称' },
    { key: 'name', label: '名称' },
    { key: 'package_name', label: '包名' },
    { key: 'version', label: '版本' },
    { key: 'version_name', label: '版本' },
    { key: 'is_system_app', label: '类型', format: (v) => Number(v) === 1 ? 'system' : (v === '' || v == null ? '—' : 'user') },
    { key: 'code_path', label: '安装路径' },
    { key: 'apk_path', label: '安装路径' },
    { key: 'installer', label: '安装来源' },
    { key: 'first_install_time', label: '安装时间', format: fmtTime },
    { key: 'last_update_time', label: '更新时间', format: fmtTime },
  ],

  // ── Windows ──
  win_users: [
    { key: 'username', label: '用户名' },
    { key: 'full_name', label: '全名' },
    { key: 'rid', label: 'RID' },
    { key: 'is_admin', label: '管理员', format: (v) => Number(v) === 1 ? '是' : '否' },
    { key: 'last_login', label: '最后登录', format: fmtTime },
    { key: 'password_last_set', label: '密码最后设置', format: fmtTime },
    { key: 'account_flags', label: '账户标志' },
    { key: 'home_directory', label: '主目录' },
    { key: 'comment', label: '备注' },
  ],
  win_usb: [
    { key: 'device_description', label: '设备描述' },
    { key: 'friendly_name', label: '友好名称' },
    { key: 'serial_number', label: '序列号' },
    { key: 'vendor_id', label: 'VID' },
    { key: 'product_id', label: 'PID' },
    { key: 'first_connected', label: '首次连接', format: fmtTime },
    { key: 'last_connected', label: '最后连接', format: fmtTime },
    { key: 'last_drive_letter', label: '盘符' },
  ],
  win_browser: [
    { key: 'browser_name', label: '浏览器' },
    { key: 'profile_name', label: '配置' },
    { key: 'title', label: '标题' },
    { key: 'url', label: 'URL' },
    { key: 'visit_time', label: '访问时间', format: fmtTime },
    { key: 'visit_count', label: '访问次数' },
    { key: 'visit_type', label: '访问类型' },
    { key: 'referrer', label: '来源' },
  ],
  win_downloads: [
    { key: 'browser_name', label: '浏览器' },
    { key: 'url', label: 'URL' },
    { key: 'file_name', label: '文件名' },
    { key: 'target_path', label: '保存路径' },
    { key: 'file_size', label: '大小', format: fileSize },
    { key: 'start_time', label: '开始时间', format: fmtTime },
    { key: 'end_time', label: '完成时间', format: fmtTime },
    { key: 'state', label: '状态' },
  ],
  win_bookmarks: [
    { key: 'browser_name', label: '浏览器' },
    { key: 'title', label: '标题' },
    { key: 'url', label: 'URL' },
    { key: 'folder_path', label: '文件夹' },
    { key: 'date_added', label: '添加时间', format: fmtTime },
  ],
  win_services: [
    { key: 'service_name', label: '服务名' },
    { key: 'display_name', label: '显示名' },
    { key: 'image_path', label: '可执行路径' },
    { key: 'start_type', label: '启动类型' },
    { key: 'service_type', label: '服务类型' },
    { key: 'account_name', label: '运行账户' },
    { key: 'is_running', label: '状态', format: (v) => Number(v) === 1 ? '运行中' : '已停止' },
    { key: 'description', label: '描述' },
  ],
  win_scheduled_tasks: [
    { key: 'task_name', label: '任务名' },
    { key: 'author', label: '作者' },
    { key: 'action_type', label: '动作类型' },
    { key: 'action_path', label: '动作路径' },
    { key: 'arguments', label: '参数' },
    { key: 'trigger_type', label: '触发器' },
    { key: 'last_run_time', label: '上次运行', format: fmtTime },
    { key: 'next_run_time', label: '下次运行', format: fmtTime },
    { key: 'status', label: '状态' },
    { key: 'run_as', label: '运行身份' },
  ],
  win_prefetch: [
    { key: 'executable_name', label: '可执行文件' },
    { key: 'executable_path', label: '路径' },
    { key: 'run_count', label: '运行次数' },
    { key: 'last_run_time', label: '上次运行', format: fmtTime },
    { key: 'creation_time', label: '创建时间', format: fmtTime },
    { key: 'prefetch_hash', label: '哈希' },
  ],
  win_event_logs: [
    { key: 'event_id', label: '事件ID' },
    { key: 'level', label: '级别' },
    { key: 'log_source', label: '日志源' },
    { key: 'timestamp', label: '时间', format: fmtTime },
    { key: 'source', label: '来源' },
    { key: 'computer_name', label: '计算机' },
    { key: 'user_sid', label: '用户SID' },
    { key: 'message', label: '消息' },
  ],
  win_recycle_bin: [
    { key: 'file_name', label: '文件名' },
    { key: 'original_path', label: '原始路径' },
    { key: 'deletion_time', label: '删除时间', format: fmtTime },
    { key: 'original_size', label: '原始大小', format: fileSize },
    { key: 'user_sid', label: '用户SID' },
  ],
  win_rdp: [
    { key: 'server_address', label: '服务器地址' },
    { key: 'username_hint', label: '用户名提示' },
    { key: 'last_connection_time', label: '最后连接', format: fmtTime },
    { key: 'entry_type', label: '类型' },
  ],
  win_installed_apps: [
    { key: 'file_name', label: '文件名' },
    { key: 'product_name', label: '产品名' },
    { key: 'product_version', label: '版本' },
    { key: 'company_name', label: '公司' },
    { key: 'file_description', label: '描述' },
    { key: 'file_path', label: '路径' },
    { key: 'file_hash', label: '哈希' },
    { key: 'link_time', label: '编译时间', format: fmtTime },
  ],
  win_userassist: [
    { key: 'user_sid', label: '用户SID' },
    { key: 'decoded_path', label: '路径' },
    { key: 'run_count', label: '运行次数' },
    { key: 'focus_time', label: '焦点时长' },
    { key: 'last_run_time', label: '上次运行', format: fmtTime },
  ],
  win_logins: [
    { key: 'browser_name', label: '浏览器' },
    { key: 'url', label: 'URL' },
    { key: 'username', label: '用户名' },
    { key: 'times_used', label: '使用次数' },
    { key: 'date_last_used', label: '上次使用', format: fmtTime },
  ],

  // ── Linux ──
  linux_users: [
    { key: 'username', label: '用户名' },
    { key: 'uid', label: 'UID' },
    { key: 'gid', label: 'GID' },
    { key: 'full_name', label: '全名' },
    { key: 'home_directory', label: '主目录' },
    { key: 'shell', label: 'Shell' },
    { key: 'is_locked', label: '锁定', format: (v) => Number(v) === 1 ? '是' : '否' },
    { key: 'last_password_change', label: '密码最后修改', format: fmtTime },
  ],
  linux_login: [
    { key: 'username', label: '用户名' },
    { key: 'terminal', label: '终端' },
    { key: 'remote_host', label: '远程主机' },
    { key: 'login_time', label: '登录时间', format: fmtTime },
    { key: 'logout_time', label: '登出时间', format: fmtTime },
    { key: 'login_type', label: '登录类型' },
    { key: 'is_success', label: '成功', format: (v) => Number(v) === 1 ? '成功' : '失败' },
  ],
  linux_shell: [
    { key: 'username', label: '用户名' },
    { key: 'shell_type', label: 'Shell类型' },
    { key: 'command', label: '命令' },
    { key: 'timestamp', label: '时间', format: fmtTime },
    { key: 'history_file', label: '历史文件' },
  ],
  linux_services: [
    { key: 'service_name', label: '服务名' },
    { key: 'description', label: '描述' },
    { key: 'load_state', label: '加载状态' },
    { key: 'active_state', label: '活动状态' },
    { key: 'sub_state', label: '子状态' },
    { key: 'is_enabled', label: '开机启用', format: (v) => Number(v) === 1 ? '是' : '否' },
    { key: 'exec_start', label: '启动命令' },
    { key: 'user', label: '运行用户' },
  ],
  linux_network: [
    { key: 'protocol', label: '协议' },
    { key: 'local_address', label: '本地地址' },
    { key: 'local_port', label: '本地端口' },
    { key: 'remote_address', label: '远程地址' },
    { key: 'remote_port', label: '远程端口' },
    { key: 'state', label: '状态' },
    { key: 'process', label: '进程' },
    { key: 'pid', label: 'PID' },
  ],
  linux_cron: [
    { key: 'username', label: '用户' },
    { key: 'minute', label: '分' },
    { key: 'hour', label: '时' },
    { key: 'command', label: '命令' },
    { key: 'cron_file', label: '文件' },
    { key: 'cron_type', label: '类型' },
  ],
  linux_audit: [
    { key: 'timestamp', label: '时间', format: fmtTime },
    { key: 'event_id', label: '事件ID' },
    { key: 'syscall_name', label: '系统调用' },
    { key: 'success', label: '成功', format: (v) => Number(v) === 1 ? '成功' : '失败' },
    { key: 'uid', label: 'UID' },
    { key: 'auid', label: 'AUID' },
    { key: 'pid', label: 'PID' },
  ],
  linux_packages: [
    { key: 'name', label: '包名' },
    { key: 'version', label: '版本' },
    { key: 'architecture', label: '架构' },
    { key: 'package_manager', label: '包管理器' },
    { key: 'status', label: '状态' },
    { key: 'install_time', label: '安装时间', format: fmtTime },
    { key: 'description', label: '描述' },
  ],
  linux_anomalies: [
    { key: 'anomaly_type', label: '异常类型' },
    { key: 'anomaly_subtype', label: '子类型' },
    { key: 'severity', label: '严重度' },
    { key: 'confidence', label: '置信度' },
    { key: 'description', label: '描述' },
    { key: 'mitigation', label: '缓解措施' },
    { key: 'detected_at', label: '检测时间', format: fmtTime },
  ],
  linux_ssh_keys: [
    { key: 'key_type', label: '密钥类型' },
    { key: 'fingerprint', label: '指纹' },
    { key: 'comment', label: '注释' },
    { key: 'key_path', label: '路径' },
    { key: 'bit_length', label: '位长' },
  ],
  linux_firewall: [
    { key: 'chain', label: '链' },
    { key: 'target', label: '目标' },
    { key: 'protocol', label: '协议' },
    { key: 'source', label: '源' },
    { key: 'destination', label: '目的' },
    { key: 'port', label: '端口' },
    { key: 'interface', label: '接口' },
  ],
};

/**
 * Resolve the columns to render for a section given the actual record keys.
 * Returns a list of {key,label,format?}; falls back to raw record keys with
 * their name as label when no definition exists.
 */
export function resolveColumns(sectionId, records) {
  const defined = ARTIFACT_COLUMNS[sectionId] || [];
  const present = defined.filter((c) => records.some((r) => c.key in r));
  if (present.length) return present;
  // fallback: derive columns from the union of record keys (excluding internal)
  const keys = [];
  for (const r of records) {
    for (const k of Object.keys(r)) {
      if (k !== '_category' && !keys.includes(k)) keys.push(k);
    }
  }
  return keys.map((k) => ({ key: k, label: k }));
}
