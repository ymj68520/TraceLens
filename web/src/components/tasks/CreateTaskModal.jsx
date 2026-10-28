import { forensicLabel } from '../../utils/forensicLabels';
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
import { useCallback, useState } from 'react';
import { useDispatch } from 'react-redux';
import { createTask, fetchTasks } from '../../store/taskSlice';
import { closeModal } from '../../store/uiSlice';
import Button from '../common/Button';
import { useToast } from '../common/ToastContext';
import FilterProfileSelector from '../filters/FilterProfileSelector';
import FilterProfileEditor from '../filters/FilterProfileEditor';
import RaidImageSource from './RaidImageSource';
import CaseBackgroundField from './CaseBackgroundField';
import AnalysisBudgetField, {
  DEFAULT_BUDGET_CHOICE,
  budgetChoiceFromTask,
  customBudgetFromTask,
  resolveAnalysisBudget,
} from './AnalysisBudgetField';

// Data source kinds. The value is sent to the backend as android_source and
// selects the AndroidAnalyzer backend / analysis pipeline branch.
const DATA_SOURCES = [
  { value: 'tsk', label: '磁盘镜像', desc: '.dd / .E01 / raw 镜像（走 TSK 文件系统解析）' },
  { value: 'aliyun-image', label: '阿里云服务器镜像', desc: 'Linux 系统盘 .raw.tar.gz 导出包，校验解包后走原取证流程' },
  { value: 'raid', label: 'RAID 系统镜像', desc: '选择成员镜像，准备后按普通磁盘镜像分析' },
  { value: 'dir', label: 'Android 目录', desc: '已解压的逻辑提取目录树' },
  { value: 'zip', label: 'Android ZIP', desc: '逻辑提取打包成的单个 .zip' },
  { value: 'miui-backup', label: 'MIUI 备份', desc: '小米 MIUI 离线备份目录（含 descript.xml + .bak）' },
  { value: 'harmony-backup', label: '华为鸿蒙备份', desc: '已解密备份目录，含 .info.json 和 files' },
  { value: 'thunder-backup', label: '雷电快取备份', desc: '雷电手机快取提取的 tar 或工程目录（OPPO/vivo/一加等，含 PhoneData）' },
  { value: 'oppo-backup', label: 'OPPO 备份（旧）', desc: '兼容旧任务的雷电快取来源别名' },
  { value: 'tar', label: 'Android TAR', desc: '.tar / .tar.gz / .tgz / .tar.xz（需完整预检）' },
  { value: 'seven-zip', label: 'Android 7z', desc: '.7z 逻辑提取归档（需完整预检）' },
  { value: 'android-backup', label: '安卓备份', desc: '.ab（需完整预检）' },
  { value: 'filesystem-image', label: 'Android userdata 镜像', desc: 'EXT4/F2FS RAW/E01（需完整预检）' },
  { value: 'android-container', label: 'Android sparse / super', desc: '需完整预检及规范化计划' },
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
  platform_analyze: true,
  // llm_analyze (file descriptions) is always true and llm_event_analyze
  // (task-time event cluster analysis) always false — NOT user settings.
};

// Task-level analysis budget presets live in AnalysisBudgetField, shared with
// the case-creation modal so both entry points offer identical choices.

export default function CreateTaskModal({ initialSource = null, onClose = () => {} }) {
  const dispatch = useDispatch();
  const toast = useToast();

  const [form, setForm] = useState(() => ({ ...INITIAL_FORM, ...initialSource }));
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showProfileEditor, setShowProfileEditor] = useState(false);
  const [raidSource, setRaidSource] = useState(null);
  // 'default' = inherit the server's LLM_MAX_FILES; a preset value; or
  // 'custom' with a free-form number. Kept out of `form` so that switching
  // to "custom" does not erase the picker's own state.
  const [budgetChoice, setBudgetChoice] = useState(() => budgetChoiceFromTask(initialSource));
  const [customBudget, setCustomBudget] = useState(() => customBudgetFromTask(initialSource));
  const handleRaidSource = useCallback((value) => setRaidSource(value), []);

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val,
    ...(['image_path', 'android_source'].includes(key) && f[key] !== val
      ? { preflight_job_id: undefined, preflight_source_sha256: undefined, preflight_detected_kind: undefined } : {}),
  }));

  const isRaid = form.android_source === 'raid';
  const isAliyun = form.android_source === 'aliyun-image';
  const isLogical = form.android_source !== 'tsk' && !isRaid && !isAliyun;
  const isMiui = form.android_source === 'miui-backup';
  const isArchive = ['tar', 'seven-zip', 'android-backup', 'filesystem-image', 'android-container'].includes(form.android_source);

  // 预设背景里的推荐场景/平台是可选联动：只覆盖预设明确给出的项，
  // 其余保持用户当前选择。
  const applyPresetRecommendation = (preset) => setForm((f) => ({
    ...f,
    ...(preset.filterProfiles?.length ? { filter_profile: preset.filterProfiles[0] } : {}),
    ...(preset.scenarios?.length ? { scenarios: [...preset.scenarios] } : {}),
  }));

  // Label / placeholder for the path input changes with the data source.
  const isOppo = form.android_source === 'thunder-backup' || form.android_source === 'oppo-backup';
  const pathLabel = isAliyun ? '阿里云系统盘导出包 *' : form.android_source === 'harmony-backup' ? '鸿蒙备份目录 *' : isOppo ? '雷电快取提取 tar / 工程目录 *' : isMiui
    ? 'MIUI 备份目录 *'
    : form.android_source === 'dir'
    ? 'Android 提取目录 *'
    : form.android_source === 'zip'
    ? 'Android ZIP 文件 *'
    : form.android_source === 'android-container'
    ? 'Android sparse / super 镜像 *'
    : isArchive
    ? 'Android 归档/备份文件 *'
    : '检材路径 *';
  const pathPlaceholder = isAliyun ? '/path/to/file_m-xxx_system.raw.tar.gz' : form.android_source === 'harmony-backup' ? '/path/to/已解密鸿蒙备份/' : isOppo
    ? '/path/to/20261025OPPO.tar、20261025VIVO/ 或 20261025OnePlus/'
    : isMiui
    ? '/path/to/MIUI备份目录（含 descript.xml + .bak）'
    : form.android_source === 'dir'
    ? '/path/to/android_logical_extraction/'
    : form.android_source === 'zip'
    ? '/path/to/android_extraction.zip'
    : form.android_source === 'tar'
    ? '/path/to/android_export.tar.gz'
    : form.android_source === 'seven-zip'
    ? '/path/to/android_export.7z'
    : form.android_source === 'android-backup'
    ? '/path/to/backup.ab'
    : form.android_source === 'filesystem-image'
    ? '/path/to/userdata.img 或 /path/to/disk.E01'
    : form.android_source === 'android-container'
    ? '/path/to/userdata.sparse 或 /path/to/super.img'
    : '/path/to/disk_image.dd 或 /path/to/image.E01';

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setIsCreating(true);
    try {
      // A logical Android source (dir / zip / MIUI backup) is always Android —
      // force the scenario so the backend runs the Android analyzer path and
      // skips the TSK disk-image pipeline.
      if (isRaid && !raidSource) throw new Error('请先完成 RAID 布局确认和系统镜像准备');
      const isLogical = form.android_source !== 'tsk' && !isRaid && !isAliyun;
      if (isAliyun && !form.preflight_job_id) throw new Error('请先在检材预检中完成完整 SHA-256，再按此来源创建任务');
      const budget = resolveAnalysisBudget(budgetChoice, customBudget);
      if (budget.error) throw new Error(budget.error);
      const payload = {
        ...form,
        ...(isRaid ? raidSource : {}),
        scenarios: isAliyun ? ['linux'] : isLogical ? ['android'] : form.scenarios,
        llm_analyze: true,
        llm_event_analyze: false,
        llm_mode: 'smart',
        // 平台分析任务级开关（创建时选择；默认开启）
        platform_analyze: isAliyun || isArchive || form.platform_analyze !== false,
      };
      // Omit the key entirely when inheriting: an explicit 0 would also mean
      // "inherit", but sending nothing keeps old-server compatibility.
      if (budget.value !== undefined) payload.llm_max_files = budget.value;
      else delete payload.llm_max_files;
      // Only send backup_password when non-empty (keeps it runtime-only / sparse).
      if (!payload.backup_password) delete payload.backup_password;
      await dispatch(createTask(payload)).unwrap();
      dispatch(closeModal());
      onClose();
      setForm(INITIAL_FORM);
      setBudgetChoice(DEFAULT_BUDGET_CHOICE);
      setCustomBudget('');
      dispatch(fetchTasks({}));
      toast.success('任务创建成功');
    } catch (err) {
      // rejectWithValue payloads arrive either as the raw axios data object
      // ({error: "..."} from the backend's 4xx JSON) or as a plain string.
      const msg = typeof err === 'string'
        ? err
        : err?.error || err?.message || err?.detail
          ? String(err.error || err.message || err.detail)
          : (err ? JSON.stringify(err) : '创建任务失败');
      setError(msg);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50">
      <div className="bg-white dark:bg-slate-800 rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <h2 className="text-xl font-semibold text-slate-900 dark:text-white">创建分析任务</h2>
          <button onClick={() => { dispatch(closeModal()); onClose(); }} className="text-slate-400 hover:text-slate-500 dark:hover:text-slate-300">✕</button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {error && (
            <div className="p-3 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-xl">
              <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          {/* Data Source Type — selects the analysis backend */}
          <Field label="数据源类型 *" hint="阿里云导出包及 Android 容器须先完成完整 SHA-256 预检；已解出的 RAW 可选择磁盘镜像。">
            <select
              disabled={isCreating}
              value={form.android_source}
              onChange={(e) => { setRaidSource(null); set('android_source', e.target.value); }}
              className={inputCls}
            >
              {DATA_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}（{s.desc}）</option>
              ))}
            </select>
          </Field>

          {/* Image Path / data source path */}
          {isRaid ? <Field label="RAID 成员镜像 *"><RaidImageSource onSource={handleRaidSource} disabled={isCreating} /></Field> :
          <Field label={pathLabel} hint={initialSource ? '由检材预检结果预填；分析前请确认来源未改变。' : undefined}>
            <input
              type="text" required disabled={isCreating}
              value={form.image_path}
              onChange={(e) => set('image_path', e.target.value)}
              className={inputCls}
              placeholder={pathPlaceholder}
            />
          </Field>
          }

          {/* Runtime-only password; never persisted in Task serialization. */}
          {isAliyun && <p className="rounded-lg bg-indigo-50 p-3 text-sm text-indigo-900">
            先在任务页面的“检材预检”中计算完整 SHA-256，再点击“按此来源新建阿里云分析任务”。
            任务会校验并解包 RAW，保留来源哈希，沿用文件、时间线、调查与报告流程；已解出的 RAW 可直接选“磁盘镜像”。
          </p>}
          {(isMiui || form.android_source === 'seven-zip' || form.android_source === 'android-backup') && (
            <Field label="归档/备份密码（可选）" hint="仅本次运行使用，不写入 Task 持久化或命令行；密码错误或不支持的变体会明确失败。">
              <input
                type="password" disabled={isCreating}
                value={form.backup_password}
                onChange={(e) => set('backup_password', e.target.value)}
                className={inputCls}
                placeholder="未加密时留空"
                autoComplete="new-password"
              />
            </Field>
          )}

          {/* Case Description — always visible, required for LLM analysis */}
          <CaseBackgroundField
            label="案情描述"
            required
            disabled={isCreating}
            value={form.case_description}
            onChange={(val) => set('case_description', val)}
            onApplyRecommendation={applyPresetRecommendation}
            rows={4}
            hint="AI 将根据此描述筛选关键文件并生成分析报告；可直接选用预设背景，或手动输入"
            placeholder="请输入案情描述，例如：一起涉嫌网络诈骗案件，嫌疑人使用 Android 手机..."
          />

          {/* Priority */}
          <Field label="优先级">
            <select disabled={isCreating} value={form.priority} onChange={(e) => set('priority', e.target.value)} className={inputCls}>
              {['low', 'normal', 'high', 'critical'].map((p) => (
                <option key={p} value={p}>{forensicLabel(p)}</option>
              ))}
            </select>
          </Field>

          {/* Analysis file budget: the dominant cost lever. The knowledge
              graph ingests analyzed files only, so this number also bounds
              ingestion and the report evidence scope. */}
          <AnalysisBudgetField
            choice={budgetChoice}
            onChoiceChange={setBudgetChoice}
            customValue={customBudget}
            onCustomChange={setCustomBudget}
            disabled={isCreating}
          />

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
                <label className="flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
                  <input
                    type="checkbox"
                    checked={isAliyun || isArchive || form.platform_analyze !== false}
                    disabled={isAliyun || isArchive}
                    onChange={(e) => set('platform_analyze', e.target.checked)}
                    className="w-4 h-4 rounded border-slate-300"
                  />
                  平台分析（Android / Windows / Linux 工件级分析，默认开启）
                </label>
                {isAliyun ? <p className="text-xs text-slate-600">阿里云系统盘固定执行 Linux 平台分析，继续原有磁盘取证流程。</p> : isLogical ? (
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
              LLM 智能分析已默认开启（智能筛选模式）
            </span>
          </div>

          {/* Actions */}
          <div className="flex justify-end space-x-3 pt-2">
            <Button type="button" variant="secondary" onClick={() => { dispatch(closeModal()); onClose(); }} disabled={isCreating}>取消</Button>
            <Button type="submit" disabled={isCreating || (isRaid && !raidSource)}>{isCreating ? '正在创建…' : '创建任务'}</Button>
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
