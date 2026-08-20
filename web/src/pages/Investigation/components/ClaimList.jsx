import Badge from '../../../components/common/Badge';

const variants = { fact: 'green', inference: 'yellow', hypothesis: 'purple' };

export default function ClaimList({ claims = [], onTraceClaim, onTraceEvidence, onAccept, onReject, canReview = false }) {
  if (!claims.length) return <p className="text-sm text-slate-500">该版本未生成 Claims。</p>;
  return (
    <div className="space-y-2">
      {claims.map((claim) => (
        <div key={claim.id || claim.claim_text} className="rounded-xl border border-slate-200/60 dark:border-slate-700/60 p-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge size="sm" variant={variants[claim.claim_type || claim.type] || 'gray'}>{String(claim.claim_type || claim.type || '').toUpperCase()}</Badge>
            <Badge size="sm" variant={claim.status === 'accepted' ? 'green' : claim.status === 'invalid' ? 'red' : 'yellow'}>{claim.status || 'review_pending'}</Badge>
            <Badge size="sm" variant={claim.grounding_status === 'grounded' ? 'blue' : 'red'} title="Grounded 只表示 Evidence ID 真实存在，不代表该证据已充分证明断言。">{claim.grounding_status || 'unknown'}</Badge>
            {claim.origin && <span className="text-[10px] text-slate-400">{claim.origin}</span>}
          </div>
          <button type="button" className="mt-2 text-left text-sm text-slate-700 dark:text-slate-300" onClick={() => onTraceClaim?.(claim)}>{claim.claim_text}</button>
          {!!claim.grounding_warnings && <p className="mt-2 text-xs text-amber-700">{typeof claim.grounding_warnings === 'string' ? claim.grounding_warnings : claim.grounding_warnings.join(' ')}</p>}
          {!!claim.evidence_refs?.length && <div className="mt-2 flex flex-wrap gap-1">{claim.evidence_refs.map((r) => <button key={r.evidence_key} type="button" className="text-[11px] text-primary-600 underline" onClick={() => onTraceEvidence?.(r.evidence_key)}>{r.evidence_key}</button>)}</div>}
          {canReview && claim.status === 'review_pending' && <div className="mt-3 flex gap-2"><button type="button" className="rounded bg-emerald-600 px-2 py-1 text-xs text-white" onClick={() => onAccept?.(claim.id)}>接受</button><button type="button" className="rounded bg-rose-600 px-2 py-1 text-xs text-white" onClick={() => onReject?.(claim.id)}>拒绝</button></div>}
        </div>
      ))}
    </div>
  );
}
