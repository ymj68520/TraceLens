import { ArrowDownLeft, ArrowUpRight, LocateFixed } from 'lucide-react';
import Drawer, { DetailRow } from '../../components/ui/Drawer';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import {
  NODE_INTERNAL_FIELDS,
  linkType,
  nodeName,
  typeMeta,
  type KgLink,
  type KgNode,
} from './kgUtils';

export interface NodeRelationItem {
  link: KgLink;
  otherId: string;
  direction: 'out' | 'in';
}

interface NodeDrawerProps {
  node: KgNode | null;
  relations: NodeRelationItem[];
  nodeById: Map<string, KgNode>;
  degree: number;
  onClose: () => void;
  onLocate: (node: KgNode) => void;
  onOpenNode: (node: KgNode) => void;
}

const fmtValue = (v: unknown): string => {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'boolean') return v ? '是' : '否';
  if (typeof v === 'object') {
    try {
      return JSON.stringify(v);
    } catch {
      return String(v);
    }
  }
  return String(v);
};

/** 节点详情抽屉：基本信息 + 全部属性（DetailRow 枚举）+ 关联关系列表。 */
export default function NodeDrawer({
  node,
  relations,
  nodeById,
  degree,
  onClose,
  onLocate,
  onOpenNode,
}: NodeDrawerProps) {
  const meta = node ? typeMeta(node.type) : null;
  const propEntries = node
    ? Object.entries(node).filter(
        ([k, v]) => k !== 'id' && !NODE_INTERNAL_FIELDS.includes(k) && typeof v !== 'function' && v !== undefined,
      )
    : [];

  return (
    <Drawer
      open={!!node}
      onClose={onClose}
      title={node ? nodeName(node) : '节点详情'}
      description={node?.id}
      footer={
        node && (
          <div className="flex items-center gap-2.5">
            <Button size="sm" variant="secondary" onClick={() => onLocate(node)}>
              <LocateFixed size={13} /> 在图谱中定位
            </Button>
            <Badge tone="accent">{relations.length} 条关联</Badge>
          </div>
        )
      }
    >
      {node && meta && (
        <div className="space-y-5">
          <section>
            <h4 className="section-label mb-1.5">基本信息</h4>
            <DetailRow label="名称">{nodeName(node)}</DetailRow>
            <DetailRow label="ID" mono>{node.id}</DetailRow>
            <DetailRow label="实体类型">
              <Badge tone="accent">{meta.label}</Badge>
            </DetailRow>
            <DetailRow label="关系数">
              <span className="font-mono tabular-nums">{degree}</span>
            </DetailRow>
          </section>

          <section>
            <h4 className="section-label mb-1.5">全部属性</h4>
            {propEntries.length === 0 ? (
              <p className="text-2xs text-ink-400 py-1">该节点没有其他属性字段。</p>
            ) : (
              propEntries.map(([k, v]) => (
                <DetailRow key={k} label={k} mono={typeof v === 'string' && v.length > 24}>
                  {fmtValue(v)}
                </DetailRow>
              ))
            )}
          </section>

          <section>
            <h4 className="section-label mb-1.5">关联关系（{relations.length}）</h4>
            {relations.length === 0 ? (
              <p className="text-2xs text-ink-400 py-1">该节点暂无关联关系。</p>
            ) : (
              <ul className="divide-y divide-ink-100 dark:divide-ink-800/60">
                {relations.map(({ link, otherId, direction }, i) => {
                  const other = nodeById.get(otherId);
                  const out = direction === 'out';
                  return (
                    <li key={`${otherId}|${linkType(link)}|${direction}|${i}`}>
                      <button
                        type="button"
                        onClick={() => other && onOpenNode(other)}
                        disabled={!other}
                        className="w-full flex items-center gap-2 py-2 text-left group disabled:cursor-default"
                      >
                        {out ? (
                          <ArrowUpRight size={13} className="text-accent-600 dark:text-accent-400 shrink-0" />
                        ) : (
                          <ArrowDownLeft size={13} className="text-ink-400 dark:text-ink-500 shrink-0" />
                        )}
                        <span className="min-w-0 flex-1">
                          <span className="block text-xs font-medium text-ink-800 dark:text-ink-100 truncate group-hover:text-accent-700 dark:group-hover:text-accent-300 transition-colors">
                            {other ? nodeName(other) : otherId}
                          </span>
                          <span className="block text-2xs text-ink-400 dark:text-ink-500">
                            {out ? '指向' : '来自'} · {linkType(link)}
                          </span>
                        </span>
                        <Badge tone="neutral">{out ? '出边' : '入边'}</Badge>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
