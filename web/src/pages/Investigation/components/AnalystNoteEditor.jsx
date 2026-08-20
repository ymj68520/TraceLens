import { useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import Button from '../../../components/common/Button';
import { saveAnalystNote } from '../../../services/investigationService';

export default function AnalystNoteEditor({ taskId, evidenceKey, initialValue = '', onSaved }) {
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
      <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={5} placeholder="补充案件上下文、调查假设或需要模型重点判断的问题。注意：Analyst Note 不是证据。" className="w-full rounded-xl border-slate-300 dark:border-slate-700 dark:bg-slate-900/50 text-sm" />
      <div className="mt-2 flex justify-end"><Button size="sm" variant="secondary" icon={Save} loading={saving} onClick={save}>保存 Note</Button></div>
    </div>
  );
}
