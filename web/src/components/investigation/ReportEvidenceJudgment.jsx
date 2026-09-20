import { useState } from 'react';
import { ClipboardCheck, Paperclip, Star, Undo2, X } from 'lucide-react';
import { useToast } from '../common/useToast';
import { addReportEvidence, updateReportEvidenceStatus } from '../../services/investigationService';

export const REPORT_JUDGMENT_LABELS = {
  main: '正文证据',
  appendix: '附件证据',
  excluded: '已排除',
  unjudged: '未判定',
};

const BADGE_CLS = {
  main: 'bg-purple-100 text-purple-700 border-purple-200',
  appendix: 'bg-blue-100 text-blue-700 border-blue-200',
  excluded: 'bg-slate-100 text-slate-500 border-slate-200',
  unjudged: 'bg-amber-50 text-amber-600 border-amber-200',
};

const BADGE_ICON = {
  main: <Star size={10} className="mr-0.5 -mt-0.5 inline" />,
  appendix: <Paperclip size={10} className="mr-0.5 -mt-0.5 inline" />,
  excluded: <X size={10} className="mr-0.5 -mt-0.5 inline" />,
  unjudged: <ClipboardCheck size={10} className="mr-0.5 -mt-0.5 inline" />,
};

const BTN = 'text-[10px] font-bold px-2 py-1 rounded-lg transition-colors inline-flex items-center gap-1 disabled:opacity-50';

/**
 * 报告证据判定（R1 三态 main / appendix / excluded）的唯一 UI 组件。
 *
 * /analysis-center 证据判定列表、/investigation 文件工作台与证据分析面板
 * 共用本组件：判定语义与写入路径（POST/PUT /api/reports/evidence）保持单一，
 * 不做功能分叉。未判定（status=null）首次判定走 POST（file: 证据由后端
 * 自动捕获快照），其余为显式 PUT 更新。事件簇证据（cluster:）按 MVP
 * SPEC §4.2 不参与报告判定，只渲染只读提示。
 *
 * @param {string}   taskId      任务 ID
 * @param {string}   evidenceKey 规范证据键（file:<path>）
 * @param {string|null} status   当前判定；null = 未判定
 * @param {Function} onChanged   判定成功后的回调（参数为新的三态值）
 */
export default function ReportEvidenceJudgment({ taskId, evidenceKey, status = null, onChanged }) {
  const toast = useToast();
  const [saving, setSaving] = useState(false);

  if (evidenceKey?.startsWith('cluster:')) {
    return (
      <p className="text-xs text-slate-400" data-testid="report-judgment-cluster-note">
        事件簇证据不参与报告判定（报告链只吃文件证据）。
      </p>
    );
  }
  if (!evidenceKey || !taskId) return null;

  const current = status || 'unjudged';
  const judge = async (next) => {
    if (saving) return;
    setSaving(true);
    try {
      if (status) await updateReportEvidenceStatus(taskId, evidenceKey, next);
      else await addReportEvidence(taskId, evidenceKey, next);
      toast.success(`已判定为「${REPORT_JUDGMENT_LABELS[next]}」`);
      onChanged?.(next);
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || String(err);
      toast.error('判定失败: ' + detail);
    } finally {
      setSaving(false);
    }
  };

  const judgeButtons = [];
  if (current !== 'main') {
    judgeButtons.push(
      <button
        key="main"
        type="button"
        onClick={() => judge('main')}
        disabled={saving}
        title={current === 'excluded' ? '恢复为正文证据' : '作为报告正文证据'}
        className={`${BTN} text-purple-600 hover:text-purple-700 bg-purple-50 hover:bg-purple-100`}
      >
        {current === 'excluded' ? <Undo2 size={11} /> : <Star size={11} />}
        {current === 'excluded' ? '恢复正文' : '正文'}
      </button>
    );
  }
  if (current !== 'appendix') {
    judgeButtons.push(
      <button
        key="appendix"
        type="button"
        onClick={() => judge('appendix')}
        disabled={saving}
        title={current === 'excluded' ? '恢复为附件证据' : '作为报告附件证据'}
        className={`${BTN} text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100`}
      >
        {current === 'excluded' ? <Undo2 size={11} /> : <Paperclip size={11} />}
        {current === 'excluded' ? '恢复附件' : '附件'}
      </button>
    );
  }
  if (current !== 'excluded') {
    judgeButtons.push(
      <button
        key="excluded"
        type="button"
        onClick={() => judge('excluded')}
        disabled={saving}
        title="移出报告（保留判定痕迹）"
        className={`${BTN} text-slate-500 bg-slate-100 hover:bg-red-50 hover:text-red-600`}
      >
        <X size={11} />
        移出
      </button>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5" data-testid="report-evidence-judgment">
      <span className={`text-[10px] font-bold px-2 py-1 rounded-lg border ${BADGE_CLS[current]}`} title="报告证据判定">
        {BADGE_ICON[current]}
        {REPORT_JUDGMENT_LABELS[current]}
      </span>
      {judgeButtons}
    </span>
  );
}
