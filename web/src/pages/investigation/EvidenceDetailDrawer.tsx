import { useEffect, useMemo, useState } from 'react';
import { Camera } from 'lucide-react';
import Drawer, { DetailRow } from '../../components/ui/Drawer';
import Button from '../../components/ui/Button';
import Badge from '../../components/ui/Badge';
import { SkeletonBlock } from '../../components/ui/PageScaffold';
import { getEvidenceDetail } from '../../services/investigationService';
import type { EvidenceRow } from './EvidenceListPanel';

const UNTYPED = '未分类';

/** 展示在 DetailRow 中的基础字段，其余原始字段在「其他属性」里兜底。 */
const BASE_FIELDS = new Set(['evidence_key', 'kind', 'file_path', 'x', 'y', 'index']);

interface EvidenceDetailDrawerProps {
  evidence: EvidenceRow | null;
  taskId: string;
  onClose: () => void;
  onCapture: (key: string) => Promise<void>;
}

/** 证据条目 Drawer：DetailRow 展示实体属性 + 工作台详情接口兜底。 */
export default function EvidenceDetailDrawer({ evidence, taskId, onClose, onCapture }: EvidenceDetailDrawerProps) {
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [detailState, setDetailState] = useState<'loading' | 'ok' | 'missing'>('loading');
  const [capturing, setCapturing] = useState(false);

  const evidenceKey = evidence?.evidence_key ?? null;

  useEffect(() => {
    if (!evidenceKey) return;
    let cancelled = false;
    setDetail(null);
    setDetailState('loading');
    getEvidenceDetail(taskId, evidenceKey)
      .then((res) => {
        if (cancelled) return;
        if (res && typeof res === 'object' && Object.keys(res as Record<string, unknown>).length > 0) {
          setDetail(res as Record<string, unknown>);
          setDetailState('ok');
        } else {
          setDetailState('missing');
        }
      })
      .catch(() => {
        if (!cancelled) setDetailState('missing');
      });
    return () => {
      cancelled = true;
    };
  }, [taskId, evidenceKey]);

  // 详情接口返回的原始标量字段（排除已展示的基础字段）。
  const extraRows = useMemo(() => {
    if (!detail) return [];
    return Object.entries(detail).filter(
      ([k, v]) =>
        !BASE_FIELDS.has(k) &&
        (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
    );
  }, [detail]);

  const kind = evidence && typeof evidence.kind === 'string' && evidence.kind.trim() ? evidence.kind.trim() : null;

  const handleCapture = async () => {
    if (!evidenceKey) return;
    setCapturing(true);
    try {
      await onCapture(evidenceKey);
    } finally {
      setCapturing(false);
    }
  };

  return (
    <Drawer
      open={!!evidence}
      onClose={onClose}
      title="证据详情"
      description={evidenceKey ?? undefined}
      footer={
        <div className="flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => void handleCapture()} disabled={capturing || !evidenceKey}>
            <Camera size={13} /> {capturing ? '捕获中…' : '捕获快照'}
          </Button>
        </div>
      }
    >
      {evidence && (
        <div className="space-y-5">
          <section>
            <h4 className="section-label mb-1.5">实体属性</h4>
            <DetailRow label="证据标识" mono>{evidence.evidence_key}</DetailRow>
            <DetailRow label="类型">
              {kind ? <Badge tone="neutral">{kind}</Badge> : <span className="text-ink-400">{UNTYPED}</span>}
            </DetailRow>
            <DetailRow label="文件路径" mono>
              {typeof evidence.file_path === 'string' && evidence.file_path ? (
                evidence.file_path
              ) : (
                <span className="text-ink-400">—</span>
              )}
            </DetailRow>
          </section>

          <section>
            <h4 className="section-label mb-1.5">工作台详情</h4>
            {detailState === 'loading' ? (
              <div className="space-y-2 py-1">
                <SkeletonBlock className="h-3 w-3/4" />
                <SkeletonBlock className="h-3 w-1/2" />
              </div>
            ) : detailState === 'ok' && detail ? (
              <>
                {extraRows.length === 0 ? (
                  <p className="text-2xs text-ink-400 py-1">详情接口未返回可展示的附加字段。</p>
                ) : (
                  extraRows.map(([k, v]) => (
                    <DetailRow key={k} label={k} mono={typeof v === 'string' && v.length > 24}>
                      {String(v)}
                    </DetailRow>
                  ))
                )}
              </>
            ) : (
              <p className="text-2xs text-ink-400 py-1">
                详情接口不可用或未返回数据。快照内容与二次分析请查看中间栏证据面板。
              </p>
            )}
          </section>

          {Object.entries(evidence).some(
            ([k, v]) => !BASE_FIELDS.has(k) && (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
          ) && (
            <section>
              <h4 className="section-label mb-1.5">其他属性</h4>
              {Object.entries(evidence)
                .filter(
                  ([k, v]) =>
                    !BASE_FIELDS.has(k) &&
                    (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean'),
                )
                .map(([k, v]) => (
                  <DetailRow key={k} label={k} mono>
                    {String(v)}
                  </DetailRow>
                ))}
            </section>
          )}
        </div>
      )}
    </Drawer>
  );
}
