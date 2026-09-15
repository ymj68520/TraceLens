import { useEffect, useMemo, useState } from 'react';
import { LocateFixed } from 'lucide-react';
import Drawer, { DetailRow } from '../../components/ui/Drawer';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import { SkeletonBlock } from '../../components/ui/PageScaffold';
import { getWeChatPerson } from '../../services/wechatService';
import { displayName, isGroupNode, type WxNode } from './wechatUtils';

/** 图谱内部状态字段，不属于实体属性。 */
const GRAPH_INTERNAL_FIELDS = new Set(['x', 'y', 'vx', 'vy', 'index', 'fx', 'fy']);

interface ContactDrawerProps {
  taskId: string;
  node: WxNode | null;
  onClose: () => void;
  onLocate: (node: WxNode) => void;
}

const extractPerson = (res: unknown): Record<string, unknown> | null => {
  if (!res || typeof res !== 'object') return null;
  const r = res as Record<string, unknown>;
  if (r.person && typeof r.person === 'object') return r.person as Record<string, unknown>;
  return r;
};

/** 联系人 Drawer：图谱节点属性 + /person 接口详情（不可用时优雅降级）。 */
export default function ContactDrawer({ taskId, node, onClose, onLocate }: ContactDrawerProps) {
  const [person, setPerson] = useState<Record<string, unknown> | null>(null);
  const [personState, setPersonState] = useState<'loading' | 'ok' | 'missing'>('loading');

  const username = node?.id ?? null;

  useEffect(() => {
    if (!username) return;
    let cancelled = false;
    setPerson(null);
    setPersonState('loading');
    getWeChatPerson(taskId, username)
      .then((res) => {
        if (cancelled) return;
        const p = extractPerson(res);
        if (p && Object.keys(p).length > 0) {
          setPerson(p);
          setPersonState('ok');
        } else {
          setPersonState('missing');
        }
      })
      .catch(() => {
        if (!cancelled) setPersonState('missing');
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, username]);

  // /person 接口里节点未展示过的原始标量字段。
  const personExtras = useMemo(() => {
    if (!person) return [];
    const known = new Set(['nickname', 'name', 'remark', 'alias', 'id', 'username', 'message_count']);
    return Object.entries(person).filter(
      ([k, v]) =>
        !known.has(k) &&
        !GRAPH_INTERNAL_FIELDS.has(k) &&
        (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
    );
  }, [person]);

  return (
    <Drawer
      open={!!node}
      onClose={onClose}
      title={node ? displayName(node) : '联系人详情'}
      description={node?.id}
      footer={
        node && (
          <Button size="sm" variant="secondary" onClick={() => onLocate(node)}>
            <LocateFixed size={13} /> 在图谱中定位
          </Button>
        )
      }
    >
      {node && (
        <div className="space-y-5">
          <section>
            <h4 className="section-label mb-1.5">基本信息</h4>
            <DetailRow label="显示名称">{displayName(node)}</DetailRow>
            <DetailRow label="微信 ID" mono>{node.id}</DetailRow>
            {typeof node.remark === 'string' && node.remark && <DetailRow label="备注">{node.remark}</DetailRow>}
            <DetailRow label="类型">
              <Badge tone={isGroupNode(node) ? 'info' : 'accent'}>{isGroupNode(node) ? '群聊' : '联系人'}</Badge>
            </DetailRow>
            <DetailRow label="消息数">
              {typeof node.message_count === 'number' ? (
                <span className="font-mono tabular-nums">{node.message_count}</span>
              ) : (
                <span className="text-ink-400">接口未返回</span>
              )}
            </DetailRow>
          </section>

          <section>
            <h4 className="section-label mb-1.5">服务端详情</h4>
            {personState === 'loading' ? (
              <div className="space-y-2 py-1">
                <SkeletonBlock className="h-3 w-3/4" />
                <SkeletonBlock className="h-3 w-1/2" />
              </div>
            ) : personState === 'ok' && person ? (
              personExtras.length === 0 ? (
                <p className="text-2xs text-ink-400 py-1">详情接口未返回可展示的附加字段。</p>
              ) : (
                personExtras.map(([k, v]) => (
                  <DetailRow key={k} label={k} mono={typeof v === 'string' && v.length > 24}>
                    {String(v)}
                  </DetailRow>
                ))
              )
            ) : (
              <p className="text-2xs text-ink-400 py-1">人员详情接口不可用或未返回数据，以上为图谱节点属性。</p>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
