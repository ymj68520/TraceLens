/**
 * CreateTaskModal
 *
 * Simplified task creation form:
 *  - LLM analysis is ALWAYS enabled (no toggle)
 *  - Case description is a required top-level field
 *  - Windows / Linux type checkboxes removed (backend never had this param)
 *  - Forensic scenarios (Android/Windows/Linux/Server-Cloud) are auto-detected
 *    by the backend by default; a multi-select override lives under "Advanced"
 *  - XFS mode hidden inside collapsible "Advanced" section
 *  - Filter profile selection for scenario-based file filtering
 *  - Data source type selects the analysis backend: a disk image (TSK) or a
 *    logical Android source (dir / zip / MIUI backup). Logical sources bypass
 *    the TSK pipeline entirely.
 */
import { useState } from 'react';
import { useDispatch } from 'react-redux';
import { createTask, fetchTasks } from '../../store/taskSlice';
import { closeModal } from '../../store/uiSlice';
import Button from '../common/Button';
import { useToast } from '../common/useToast';
import FilterProfileSelector from '../filters/FilterProfileSelector';
import FilterProfileEditor from '../filters/FilterProfileEditor';

// Data source kinds. The value is sent to the backend as android_source and
// selects the AndroidAnalyzer backend / analysis pipeline branch.
const DATA_SOURCES = [
  { value: 'tsk', label: '磁盘镜像', desc: '.dd / .E01 / raw 镜像（走 TSK 文件系统解析）' },
  { value: 'dir', label: 'Android 目录', desc: '已解压的逻辑提取目录树' },
  { value: 'zip', label: 'Android ZIP', desc: '逻辑提取打包成的单个 .zip' },
  { value: 'miui-backup', label: 'MIUI 备份', desc: '小米 MIUI 离线备份目录（含 descript.xml + .bak）' },
];

const INITIAL_FORM = {
  image_path: '',
  android_source: 'tsk',
  backup_password: '',
  priority: 'normal',
  case_description: '',
  scenarios: [],
  xfs_mode: 'auto',
  filter_profile: 'general_forensics',
  // llm_analyze is always true — NOT a user setting
};

export default function CreateTaskModal() {
  const dispatch = useDispatch();
  const toast = useToast();

  const [form, setForm] = useState(INITIAL_FORM);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showProfileEditor, setShowProfileEditor] = useState(false);

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const isLogical = form.android_source !== 'tsk';
  const isMiui = form.android_source === 'miui-backup';

  // Label / placeholder for the path input changes with the data source.
  const pathLabel = isMiui
    ? 'MIUI 备份目录 *'
    : form.android_source === 'dir'
    ? 'Android 提取目录 *'
    : form.android_source === 'zip'
    ? 'Android ZIP 文件 *'
    : 'Image Path *';
  const pathPlaceholder = isMiui
    ? '/path/to/MIUI备份目录（含 descript.xml + .bak）'
    : form.android_source === 'dir'
    ? '/path/to/android_logical_extraction/'
    : form.android_source === 'zip'
    ? '/path/to/android_extraction.zip'
    : '/path/to/disk_image.dd or /path/to/image.E01';

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsCreating(true);
    try {
      // A logical Android source (dir / zip / MIUI backup) is always Android —
      // force the scenario so the backend runs the Android analyzer path and
      // skips the TSK disk-image pipeline.
      const isLogical = form.android_source !== 'tsk';
      const payload = {
        ...form,
        scenarios: isLogical ? ['android'] : form.scenarios,
        llm_analyze: true,
        llm_mode: 'smart',
      };
      // Only send backup_password when non-empty (keeps it runtime-only / sparse).
      if (!payload.backup_password) delete payload.backup_password;
      await dispatch(createTask(payload)).unwrap();
      dispatch(closeModal());
      setForm(INITIAL_FORM);
      dispatch(fetchTasks({}));
      toast.success('Task created successfully!');
    } catch (err) {
      setError(err?.message || err?.toString() || 'Failed to create task.');
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-lg">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">Create New Task</h2>
          <button onClick={() => dispatch(closeModal())} className="text-slate-400 hover:text-slate-500 dark:hover:text-slate-300">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* Data Source Type — selects the analysis backend */}
          <Field label="数据源类型 *" hint="决定分析后端：磁盘镜像走 TSK 文件系统解析；目录/ZIP/MIUI 备份直接交给 Android 分析器">
            <select
              disabled={isCreating}
              value={form.android_source}
              onChange={(e) => set('android_source', e.target.value)}
              className={inputCls}
            >
              {DATA_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}（{s.desc}）</option>
              ))}
            </select>
          </Field>

          {/* Image Path / data source path */}
          <Field label={pathLabel}>
            <input
              type="text" required disabled={isCreating}
              value={form.image_path}
              onChange={(e) => set('image_path', e.target.value)}
              className={inputCls}
              placeholder={pathPlaceholder}
            />
          </Field>

          {/* Backup password — only for encrypted MIUI backups */}
          {isMiui && (
            <Field label="备份密码（可选）" hint="若 MIUI 备份已加密（AES-256），填入密码以解密 .bak；仅本次运行使用，不会持久化">
              <input
                type="password" disabled={isCreating}
                value={form.backup_password}
                onChange={(e) => set('backup_password', e.target.value)}
                className={inputCls}
                placeholder="留空表示备份未加密"
                autoComplete="new-password"
              />
            </Field>
          )}

          {/* Case Description — always visible, required for LLM analysis */}
          <Field label="案情描述 *" hint="AI 将根据此描述筛选关键文件并生成分析报告">
            <textarea
              required disabled={isCreating}
              value={form.case_description}
              onChange={(e) => set('case_description', e.target.value)}
              rows={3}
              className={`${inputCls} resize-none`}
              placeholder="请输入案情描述，例如：一起涉嫌网络诈骗案件，嫌疑人使用 Android 手机..."
            />
          </Field>

          {/* Priority */}
          <Field label="Priority">
            <select disabled={isCreating} value={form.priority} onChange={(e) => set('priority', e.target.value)} className={inputCls}>
              {['low', 'normal', 'high', 'critical'].map((p) => (
                <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
              ))}
            </select>
          </Field>

          {/* Analysis Scenario (deterministic classifier profile) */}
          {/* The filter profile drives the TSK-pipeline FileFilter; it is not
              applicable to logical Android sources, which bypass that pipeline. */}
          {!isLogical && (
            <Field label="分析场景 *" hint="选择取证场景，决定确定性分类器选取哪些文件进行分析">
              <FilterProfileSelector
                value={form.filter_profile}
                onChange={(val) => set('filter_profile', val)}
                disabled={isCreating}
              />
              <button
                type="button"
                onClick={() => setShowProfileEditor(true)}
                className="mt-1.5 text-xs text-primary-600 dark:text-primary-400 hover:underline"
              >
                + 创建自定义场景
              </button>
            </Field>
          )}

          {/* Advanced options */}
          <div>
            <button
              type="button"
              onClick={() => setShowAdvanced((v) => !v)}
              className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300 underline"
            >
              {showAdvanced ? '▲ 收起高级选项' : '▼ 高级选项'}
            </button>
            {showAdvanced && (
              <div className="mt-2 space-y-4">
                {isLogical ? (
                  // Logical Android source → platform is fixed to Android; the
                  // TSK pipeline (and thus XFS mode / scene auto-detect) does
                  // not apply. Show an informational note instead of overrides.
                  <div className="p-2 bg-slate-50 dark:bg-slate-700/40 rounded-lg text-xs text-slate-600 dark:text-slate-300">
                    逻辑 Android 数据源固定为 Android 平台分析，跳过 TSK 文件系统解析与 XFS 模式。
                  </div>
                ) : (
                  <>
                    {/* Forensic scenario override — 默认留空=自动检测，勾选则覆盖 */}
                    <Field label="取证场景覆盖" hint="默认留空，分析器会根据镜像内容自动判断平台；如需限定，勾选覆盖自动判断">
                      <div className="space-y-2">
                        {[
                          { value: 'android', label: '📱 Android', desc: 'SMS、联系人、通话记录、应用数据' },
                          { value: 'windows', label: '🪟 Windows', desc: '注册表、事件日志、Prefetch、浏览器历史' },
                          { value: 'linux', label: '🐧 Linux', desc: '系统日志、用户账户、Shell 历史、SSH' },
                          { value: 'server_cloud', label: '☁️ 服务器/云', desc: 'Docker、Nginx/Apache、K8s、云配置' },
                        ].map((s) => (
                          <label key={s.value} className="flex items-start gap-2 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={form.scenarios.includes(s.value)}
                              disabled={isCreating}
                              onChange={(e) => {
                                set(
                                  'scenarios',
                                  e.target.checked
                                    ? [...form.scenarios, s.value]
                                    : form.scenarios.filter((v) => v !== s.value)
                                );
                              }}
                              className="mt-1 rounded border-slate-300 text-primary-600 focus:ring-primary-500 disabled:opacity-50"
                            />
                            <div>
                              <span className="text-sm text-slate-700 dark:text-slate-300">{s.label}</span>
                              <p className="text-xs text-slate-400">{s.desc}</p>
                            </div>
                          </label>
                        ))}
                      </div>
                    </Field>

                    <Field label="XFS Mode">
                      <select disabled={isCreating} value={form.xfs_mode} onChange={(e) => set('xfs_mode', e.target.value)} className={inputCls}>
                        <option value="auto">Auto（推荐）</option>
                        <option value="native">Native（仅 Linux）</option>
                        <option value="pure">Pure（跨平台）</option>
                      </select>
                    </Field>
                  </>
                )}
              </div>
            )}
          </div>

          {/* LLM always-on notice */}
          <div className="flex items-center gap-2 p-2 bg-primary-50 dark:bg-primary-900/20 rounded-lg">
            <span className="text-primary-600 dark:text-primary-400 text-sm">🤖</span>
            <span className="text-xs text-primary-700 dark:text-primary-300">
              LLM 智能分析已默认开启（Smart 模式）
            </span>
          </div>

          {/* Actions */}
          <div className="flex justify-end space-x-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => dispatch(closeModal())} disabled={isCreating}>Cancel</Button>
            <Button type="submit" disabled={isCreating}>{isCreating ? 'Creating...' : 'Create Task'}</Button>
          </div>
        </form>
      </div>

      {/* Profile Editor Modal */}
      {showProfileEditor && (
        <FilterProfileEditor
          profile={null}
          onClose={() => setShowProfileEditor(false)}
        />
      )}
    </div>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const inputCls =
  'w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:bg-slate-100 dark:disabled:bg-slate-700 dark:bg-slate-700 dark:text-white text-sm';

function Field({ label, hint, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}
