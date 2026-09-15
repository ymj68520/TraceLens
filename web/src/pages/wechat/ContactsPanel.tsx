import { useMemo, useState } from 'react';
import { Search, Users } from 'lucide-react';
import Badge from '../../components/ui/Badge';
import EmptyState from '../../components/ui/EmptyState';
import { SkeletonBlock } from '../../components/ui/PageScaffold';
import { cx } from '../../lib/utils';
import { displayName, isGroupNode, type WxNode } from './wechatUtils';

export type ContactsSort = 'msgs' | 'name';

interface ContactsPanelProps {
  contacts: WxNode[];
  ownerId: string | null;
  selectedId: string | null;
  sort: ContactsSort;
  onSortChange: (v: ContactsSort) => void;
  /** 点击联系人：联动图谱定位并打开 Drawer 详情。 */
  onSelect: (node: WxNode) => void;
  loading: boolean;
}

/** 左侧联系人清单：搜索过滤 + 消息数徽章 + 排序。 */
export default function ContactsPanel({
  contacts,
  ownerId,
  selectedId,
  sort,
  onSortChange,
  onSelect,
  loading,
}: ContactsPanelProps) {
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q
      ? contacts.filter(
          (n) => displayName(n).toLowerCase().includes(q) || n.id.toLowerCase().includes(q),
        )
      : contacts;
    const sorted = [...base];
    if (sort === 'msgs') {
      sorted.sort((a, b) => {
        const am = typeof a.message_count === 'number' ? a.message_count : -1;
        const bm = typeof b.message_count === 'number' ? b.message_count : -1;
        return bm - am || displayName(a).localeCompare(displayName(b), 'zh');
      });
    } else {
      sorted.sort((a, b) => displayName(a).localeCompare(displayName(b), 'zh'));
    }
    return sorted;
  }, [contacts, query, sort]);

  const initialOf = (name: string) => [...name][0] ?? '?';

  return (
    <div className="card flex flex-col min-h-0">
      <div className="px-4 py-3 border-b border-ink-200 dark:border-ink-800 flex items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-1.5 min-w-0">
          <Users size={14} className="text-ink-400 shrink-0" />
          <h3 className="card-title">联系人清单</h3>
        </div>
        <Badge tone={filtered.length === contacts.length ? 'neutral' : 'accent'}>
          {filtered.length}/{contacts.length}
        </Badge>
      </div>

      <div className="px-3 pt-3 pb-2 flex items-center gap-2 border-b border-ink-100 dark:border-ink-800/60 shrink-0">
        <div className="relative flex-1 min-w-0">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-400 pointer-events-none" />
          <input
            type="text"
            className="input py-1.5 pl-8 text-xs"
            placeholder="搜索昵称 / 微信 ID…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          className="select py-1.5 text-xs w-[92px] shrink-0"
          value={sort}
          onChange={(e) => onSortChange(e.target.value as ContactsSort)}
          aria-label="联系人排序"
        >
          <option value="msgs">按消息数</option>
          <option value="name">按昵称</option>
        </select>
      </div>

      {loading && contacts.length === 0 ? (
        <div className="p-3 space-y-2.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center gap-2.5">
              <SkeletonBlock className="h-8 w-8 rounded-full shrink-0" />
              <div className="flex-1 space-y-1.5">
                <SkeletonBlock className="h-3 w-2/3" />
                <SkeletonBlock className="h-2.5 w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          className="flex-1"
          icon={<Users size={30} />}
          title={contacts.length === 0 ? '暂无联系人' : '未匹配到联系人'}
          description={contacts.length === 0 ? '图谱数据为空或尚未导入微信聊天记录。' : '调整搜索关键词试试。'}
        />
      ) : (
        <ul className="flex-1 overflow-y-auto divide-y divide-ink-100 dark:divide-ink-800/60 min-h-0">
          {filtered.map((n) => {
            const isOwner = ownerId != null && n.id === ownerId;
            const isGroup = isGroupNode(n);
            const selected = n.id === selectedId;
            const name = displayName(n);
            return (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => onSelect(n)}
                  className={cx(
                    'w-full flex items-center gap-2.5 px-3 py-2 text-left transition-colors',
                    selected ? 'bg-accent-50 dark:bg-accent-500/10' : 'hover:bg-ink-50 dark:hover:bg-ink-900/50',
                  )}
                >
                  <span
                    className={cx(
                      'h-8 w-8 rounded-full flex items-center justify-center text-xs font-semibold shrink-0',
                      isGroup
                        ? 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300'
                        : 'bg-accent-100 text-accent-700 dark:bg-accent-500/15 dark:text-accent-300',
                      selected && 'ring-2 ring-accent-400 dark:ring-accent-500',
                    )}
                  >
                    {isGroup ? '群' : initialOf(name)}
                  </span>
                  <span className="flex-1 min-w-0">
                    <span className="flex items-center gap-1.5 min-w-0">
                      <span className="text-xs font-medium text-ink-800 dark:text-ink-100 truncate">{name}</span>
                      {isOwner && <Badge tone="accent" className="shrink-0">机主</Badge>}
                    </span>
                    <span className="block text-2xs text-ink-400 font-mono truncate" title={n.id}>
                      {n.id}
                    </span>
                  </span>
                  {typeof n.message_count === 'number' && (
                    <Badge tone={selected ? 'accent' : 'neutral'} className="shrink-0 font-mono">
                      {n.message_count}
                    </Badge>
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
