import { useEffect, useMemo, useRef, useState } from 'react';
import { Virtuoso } from 'react-virtuoso';
import { X } from 'lucide-react';
import Button from '../../components/ui/Button';
import EmptyState from '../../components/ui/EmptyState';
import Badge from '../../components/ui/Badge';
import { SkeletonBlock } from '../../components/ui/PageScaffold';
import { cx, formatDateTime } from '../../lib/utils';
import {
  buildMessageTypes,
  messageKey,
  msgTimeMs,
  type ChatMessage,
} from './wechatUtils';

interface ChatRecordsPanelProps {
  /** 当前会话标识（含 mtype 变化时会重置滚动），来自 URL。 */
  chatKey: string;
  participants: string;
  messages: ChatMessage[];
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  total: number | null;
  onLoadMore: () => void;
  mtype: string;
  onMtypeChange: (v: string) => void;
  onClear: () => void;
}

/**
 * firstItemIndex 基准：加载更早消息会在顶部插入数据，
 * Virtuoso 依据递减的 firstItemIndex 保持当前视口不跳动。
 */
const FIRST_ITEM_BASE = 100_000;

function ChatList({ items }: { items: ChatMessage[] }) {
  const [firstItemIndex, setFirstItemIndex] = useState(FIRST_ITEM_BASE);
  const prevFirstKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const prevFirst = prevFirstKeyRef.current;
    prevFirstKeyRef.current = items.length > 0 ? messageKey(items[0]) : null;
    if (prevFirst && items.length > 0) {
      const idx = items.findIndex((m) => messageKey(m) === prevFirst);
      if (idx > 0) setFirstItemIndex((f) => f - idx);
    }
  }, [items]);

  return (
    <Virtuoso
      style={{ height: '100%' }}
      data={items}
      firstItemIndex={firstItemIndex}
      initialTopMostItemIndex={Math.max(0, items.length - 1)}
      itemContent={(_, m) => {
        const t = msgTimeMs(m);
        return (
          <div className="px-4 py-2 border-b border-ink-100/70 dark:border-ink-800/40">
            <div className="flex items-center gap-2 mb-1">
              {m.sender && (
                <span className="text-2xs font-medium text-ink-600 dark:text-ink-300 truncate max-w-[160px]">
                  {m.sender}
                </span>
              )}
              <span className="text-2xs text-ink-400 font-mono tabular-nums">{formatDateTime(t)}</span>
            </div>
            <p className="text-xs bg-ink-50 dark:bg-ink-900 rounded-md px-2.5 py-1.5 text-ink-800 dark:text-ink-200 break-words whitespace-pre-wrap">
              {m.content ?? ''}
            </p>
          </div>
        );
      }}
    />
  );
}

/** 会话记录列表：类型筛选 + 虚拟滚动 + 分页加载（更早消息）。 */
export default function ChatRecordsPanel({
  chatKey,
  participants,
  messages,
  loading,
  loadingMore,
  hasMore,
  total,
  onLoadMore,
  mtype,
  onMtypeChange,
  onClear,
}: ChatRecordsPanelProps) {
  const typeInfo = useMemo(() => buildMessageTypes(messages), [messages]);

  const items = useMemo(() => {
    const withIdx = messages.map((m, i) => ({ m, i }));
    const filtered =
      typeInfo && mtype !== 'all'
        ? withIdx.filter(({ m }) => String(m[typeInfo.field]) === mtype)
        : withIdx;
    return filtered
      .sort(
        (a, b) =>
          (msgTimeMs(a.m) ?? Number.MAX_SAFE_INTEGER) - (msgTimeMs(b.m) ?? Number.MAX_SAFE_INTEGER) ||
          a.i - b.i,
      )
      .map(({ m }) => m);
  }, [messages, mtype, typeInfo]);

  if (loading) {
    return (
      <div className="flex-1 min-h-0 flex flex-col">
        <div className="p-4 space-y-2">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonBlock key={i} className={cx('h-10', i % 2 ? 'w-3/4' : 'w-5/6')} />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* 会话头 */}
      <div className="px-4 py-2.5 border-b border-ink-200 dark:border-ink-800 flex items-start justify-between gap-2 shrink-0">
        <div className="min-w-0">
          <h3 className="card-title">会话记录</h3>
          <p className="text-2xs text-ink-400 mt-0.5 font-mono truncate" title={participants}>
            {participants}
          </p>
        </div>
        <button
          type="button"
          onClick={onClear}
          className="p-1 rounded-md text-ink-400 hover:text-ink-600 dark:hover:text-ink-200 hover:bg-ink-100 dark:hover:bg-ink-800 transition-colors shrink-0"
          aria-label="关闭会话"
        >
          <X size={14} />
        </button>
      </div>

      {/* 类型筛选（消息未携带类型字段时不展示，避免误导） */}
      {typeInfo && (
        <div className="px-3 py-2 flex flex-wrap gap-1 border-b border-ink-100 dark:border-ink-800/60 shrink-0">
          <button
            type="button"
            onClick={() => onMtypeChange('all')}
            className={cx(
              'rounded-md border px-1.5 py-0.5 text-2xs font-medium transition-colors',
              mtype === 'all'
                ? 'border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-300'
                : 'border-ink-200 bg-white text-ink-500 hover:border-ink-300 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-400',
            )}
          >
            全部 <span className="font-mono tabular-nums">{messages.length}</span>
          </button>
          {typeInfo.options.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => onMtypeChange(mtype === opt.value ? 'all' : opt.value)}
              className={cx(
                'rounded-md border px-1.5 py-0.5 text-2xs font-medium transition-colors',
                mtype === opt.value
                  ? 'border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-500/30 dark:bg-accent-500/10 dark:text-accent-300'
                  : 'border-ink-200 bg-white text-ink-500 hover:border-ink-300 dark:border-ink-700 dark:bg-ink-900 dark:text-ink-400',
              )}
            >
              {opt.label} <span className="font-mono tabular-nums">{opt.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* 加载更早消息 */}
      {hasMore && (
        <div className="px-3 py-2 border-b border-ink-100 dark:border-ink-800/60 shrink-0">
          <Button size="sm" variant="ghost" className="w-full" onClick={onLoadMore} disabled={loadingMore}>
            {loadingMore ? '加载中…' : '加载更早消息'}
          </Button>
        </div>
      )}

      {/* 计数行 */}
      <div className="px-4 py-1.5 shrink-0 flex items-center gap-2">
        <span className="text-2xs text-ink-400 font-mono tabular-nums">
          已加载 {items.length}
          {total != null ? ` / ${total}` : ''} 条
        </span>
        {hasMore && <Badge tone="warning">未到尽头</Badge>}
      </div>

      {/* 虚拟滚动消息列表 */}
      {messages.length === 0 ? (
        <EmptyState className="flex-1" title="暂无聊天记录" description="该会话在数据库中没有可展示的消息。" />
      ) : items.length === 0 ? (
        <EmptyState className="flex-1" title="该类型下暂无消息" description="切换其他类型筛选试试。" />
      ) : (
        <div className="flex-1 min-h-0">
          <ChatList key={`${chatKey}::${mtype}`} items={items} />
        </div>
      )}
    </div>
  );
}
