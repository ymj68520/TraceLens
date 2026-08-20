import { useEffect, useState } from 'react';
import { FileCheck2, Paperclip, Star, X } from 'lucide-react';
import Button from '../../../components/common/Button';
import { removeReportEvidence, setReportEvidence } from '../../../services/investigationService';

export default function ReportEvidenceSelector({ taskId, evidenceKey, value, onChange }) {
  const [usage, setUsage] = useState(value?.usage || 'excluded');
  const [note, setNote] = useState(value?.report_note || '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setUsage(value?.usage || 'excluded');
    setNote(value?.report_note || '');
  }, [value, evidenceKey]);

  const update = async (nextUsage) => {
    setSaving(true);
    try {
      if (nextUsage === 'excluded') {
        await removeReportEvidence(taskId, evidenceKey);
        setUsage('excluded');
        onChange?.(null);
      } else {
        const response = await setReportEvidence(taskId, {
          evidence_key: evidenceKey,
          usage: nextUsage,
          role: 'primary',
          report_note: note,
        });
        setUsage(nextUsage);
        onChange?.(response.report_evidence);
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <div className="grid grid-cols-3 gap-2">
        <Button size="sm" variant={usage === 'excluded' ? 'secondary' : 'ghost'} icon={X} disabled={saving} onClick={() => update('excluded')}>未加入</Button>
        <Button size="sm" variant={usage === 'main' ? 'primary' : 'outline'} icon={Star} disabled={saving} onClick={() => update('main')}>正文证据</Button>
        <Button size="sm" variant={usage === 'appendix' ? 'primary' : 'outline'} icon={Paperclip} disabled={saving} onClick={() => update('appendix')}>附件证据</Button>
      </div>
      <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="报告说明：该证据将在最终报告中证明什么？" className="mt-3 w-full rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-900/50 text-sm" />
      {usage !== 'excluded' && <div className="mt-2 flex items-center justify-between"><span className="text-xs text-slate-500 inline-flex items-center gap-1"><FileCheck2 size={13} />绑定分析版本：{value?.analysis_id ? value.analysis_id.slice(0, 8) : '无（使用原始证据/快照）'}</span><Button size="sm" variant="secondary" loading={saving} onClick={() => update(usage)}>保存说明</Button></div>}
    </div>
  );
}
