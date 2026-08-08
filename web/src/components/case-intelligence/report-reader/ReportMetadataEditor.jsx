/**
 * ReportMetadataEditor
 *
 * Modal form to edit 案件信息 + 证据信息 (case info / evidence info) for a task.
 * Backed by GET/PUT /api/llm/intelligence-report/{task_id}/metadata.
 *
 * Renders ALL whitelisted fields grouped by section. Empty fields stay as
 * editable empty inputs so the full reference-report schema is always visible.
 */
import { useEffect, useState } from 'react';
import Modal from '../../common/Modal';
import Button from '../../common/Button';
import { useToast } from '../../common/ToastContext';
import { getReportMetadata, saveReportMetadata } from '../../../services/intelligenceReportService';
import { CASE_INFO_FIELDS, EVIDENCE_INFO_FIELDS } from './sections/metadataFields';

function FieldGroup({ title, fields, values, onChange }) {
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-bold text-slate-700 dark:text-slate-200">{title}</legend>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-3">
        {fields.map((f) => (
          <label key={f.key} className="block">
            <span className="block text-xs text-slate-500 dark:text-slate-400">{f.label}</span>
            <input
              type="text"
              value={values[f.key] ?? ''}
              onChange={(e) => onChange(f.key, e.target.value)}
              className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-sm text-slate-800 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-100"
            />
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export default function ReportMetadataEditor({ taskId, isOpen, onClose, onSaved }) {
  const toast = useToast();
  const [values, setValues] = useState({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  // Load current metadata when the modal opens.
  useEffect(() => {
    if (!isOpen || !taskId) return undefined;
    setLoading(true);
    setError('');
    getReportMetadata(taskId)
      .then((data) => setValues(data.metadata || {}))
      .catch((err) => setError(err?.data?.detail || err?.message || '加载元数据失败'))
      .finally(() => setLoading(false));
    return () => {};
  }, [isOpen, taskId]);

  const set = (key, val) => setValues((v) => ({ ...v, [key]: val }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const stored = await saveReportMetadata(taskId, values);
      toast.success('案件/证据信息已保存');
      onSaved?.(stored.metadata);
      onClose();
    } catch (err) {
      setError(err?.data?.detail || err?.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="编辑案件信息 / 证据信息" size="3xl">
      <form onSubmit={handleSubmit} className="space-y-6">
        {loading ? (
          <p className="py-8 text-center text-sm text-slate-500">加载中…</p>
        ) : (
          <>
            <FieldGroup title="案件信息" fields={CASE_INFO_FIELDS} values={values} onChange={set} />
            <FieldGroup title="证据信息" fields={EVIDENCE_INFO_FIELDS} values={values} onChange={set} />
          </>
        )}
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-300">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 border-t border-slate-200 pt-4 dark:border-slate-700">
          <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>取消</Button>
          <Button type="submit" loading={saving} disabled={loading}>保存</Button>
        </div>
      </form>
    </Modal>
  );
}
