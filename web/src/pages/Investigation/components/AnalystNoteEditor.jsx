import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import Button from '../../../components/common/Button';
import { saveAnalystNote } from '../../../services/investigationService';

export default function AnalystNoteEditor({ taskId, evidenceKey, initialValue = '', onSaved, readOnly = false }) {
  const [value, setValue] = useState(initialValue);
  const [saving, setSaving] = useState(false);

  useEffect(() => setValue(initialValue || ''), [initialValue, evidenceKey]);

  const save = async () => {
    setSaving(true);
    try {
      const response = await saveAnalystNote(taskId, 'evidence', evidenceKey, value);
      onSaved?.(response.note);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div>
      <textarea value={value} readOnly={readOnly} onChange={(e) => setValue(e.target.value)} rows={5} placeholder="补充调查背景、分析思路与核对说明（备注不作为证据）。" className="w-full rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-900/50 text-sm" />
      <div className="mt-2 flex justify-end"><Button size="sm" variant="secondary" icon={Save} loading={saving} disabled={readOnly} title={readOnly ? '历史版本只读' : undefined} onClick={save}>保存备注</Button></div>
    </div>
  );
}
