import { useState } from 'react';
import { Download, Link2, Plus, StickyNote, Trash2 } from 'lucide-react';
import Badge from '../../components/ui/Badge';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import { cn, formatRelativeTime, truncate } from '../../lib/utils';
import type { ClueNote } from './useClueNotes';

interface ClueNotesPanelProps {
  notes: ClueNote[];
  /** 当前选中的证据 key；添加笔记时可选择关联。 */
  linkedEvidenceKey: string | null;
  onAdd: (content: string, evidenceKey: string | null) => boolean;
  onRemove: (id: string) => void;
  onExport: () => boolean;
}

const MAX_NOTE_LENGTH = 2000;

/** 右侧「线索笔记」面板：为当前任务追加调查笔记，localStorage 持久化。 */
export default function ClueNotesPanel({ notes, linkedEvidenceKey, onAdd, onRemove, onExport }: ClueNotesPanelProps) {
  const [draft, setDraft] = useState('');
  const [linkEvidence, setLinkEvidence] = useState(true);

  const effectiveLink = linkEvidence && linkedEvidenceKey ? linkedEvidenceKey : null;

  const handleAdd = () => {
    if (onAdd(draft, effectiveLink)) {
      setDraft('');
    }
  };

  return (
    <div className="card flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <StickyNote size={14} className="text-ink-400 shrink-0" />
          <h3 className="card-title">线索笔记</h3>
          <Badge tone="accent">{notes.length}</Badge>
        </div>
        <Button
          size="sm"
          variant="ghost"
          className="px-1.5"
          disabled={notes.length === 0}
          title="导出全部笔记为 JSON"
          onClick={() => onExport()}
        >
          <Download size={13} />
        </Button>
      </div>

      {/* 录入区 */}
      <div className="p-3 border-b border-ink-100 dark:border-ink-800 space-y-2 shrink-0">
        <textarea
          rows={3}
          maxLength={MAX_NOTE_LENGTH}
          className="input text-xs resize-y"
          placeholder="记录调查线索、假设或待核验事项…"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) handleAdd();
          }}
        />
        <div className="flex items-center justify-between gap-2">
          {linkedEvidenceKey ? (
            <button
              type="button"
              onClick={() => setLinkEvidence((v) => !v)}
              aria-pressed={!!effectiveLink}
              title={linkedEvidenceKey}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs max-w-[190px] transition-colors',
                effectiveLink
                  ? 'border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-300'
                  : 'border-ink-200 bg-white text-ink-400 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-500',
              )}
            >
              <Link2 size={11} className="shrink-0" />
              <span className="font-mono truncate">{truncate(linkedEvidenceKey, 22)}</span>
            </button>
          ) : (
            <span className="text-2xs text-ink-400">选中证据后可关联</span>
          )}
          <span className="text-2xs text-ink-300 dark:text-ink-600 font-mono tabular-nums">
            {draft.length}/{MAX_NOTE_LENGTH}
          </span>
        </div>
        <Button
          variant="primary"
          size="sm"
          className="w-full"
          disabled={!draft.trim()}
          onClick={handleAdd}
        >
          <Plus size={13} /> 添加笔记
        </Button>
      </div>

      {/* 列表：按创建时间倒序 */}
      {notes.length === 0 ? (
        <EmptyState
          className="flex-1"
          icon={<StickyNote size={30} />}
          title="暂无线索笔记"
          description="记录会随任务保存在本地浏览器，可随时导出为 JSON 归档。"
        />
      ) : (
        <ul className="flex-1 overflow-y-auto divide-y divide-ink-100 dark:divide-ink-800/60 min-h-0">
          {notes.map((note) => (
            <li key={note.id} className="px-4 py-2.5 group hover:bg-ink-50/70 dark:hover:bg-ink-900/40 transition-colors">
              <p className="text-xs text-ink-800 dark:text-ink-200 whitespace-pre-wrap break-words leading-relaxed">
                {note.content}
              </p>
              <div className="mt-1.5 flex items-center gap-2 flex-wrap">
                <span className="text-2xs text-ink-400 font-mono tabular-nums">
                  {formatRelativeTime(note.created_at)}
                </span>
                {note.evidence_key && (
                  <span
                    className="chip bg-ink-100 text-ink-500 dark:bg-ink-800 dark:text-ink-400 font-mono max-w-[150px]"
                    title={note.evidence_key}
                  >
                    <Link2 size={10} className="shrink-0" />
                    <span className="truncate">{truncate(note.evidence_key, 16)}</span>
                  </span>
                )}
                <button
                  type="button"
                  className="ml-auto p-1 rounded text-ink-300 hover:text-rose-500 dark:text-ink-600 dark:hover:text-rose-400 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                  title="删除笔记"
                  onClick={() => onRemove(note.id)}
                >
                  <Trash2 size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
