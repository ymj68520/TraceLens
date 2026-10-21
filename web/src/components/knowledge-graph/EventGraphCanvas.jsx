import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { edgeLabel, eventKinds } from './eventGraphConstants';
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export default function EventGraphCanvas({ nodes, links, onSelect }) {
  const container = useRef(null), graph = useRef(null);
  const [width, setWidth] = useState(600);
  const data = useMemo(() => ({ nodes: nodes.map(n => ({ ...n })), links: links.map(e => ({ ...e })) }), [nodes, links]);
  useEffect(() => {
    const measure = () => setWidth(Math.max(220, container.current?.clientWidth || 600));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  return <div ref={container} className="overflow-hidden rounded-xl bg-slate-950" data-testid="event-graph-canvas">
    <ForceGraph2D ref={graph} width={width} height={450} graphData={data} backgroundColor="#0f172a"
      nodeLabel={n => `${escape(n.name)} · ${eventKinds[n.kind] || '节点'}`}
      linkLabel={e => `${escape(edgeLabel(e))} · 点击回查`}
      linkColor={e => e.status === 'machine_suggestion' ? '#a78bfa' : '#94a3b8'}
      linkLineDash={e => e.status === 'machine_suggestion' || e.kind === 'mentioned_in' ? [4, 3] : null}
      linkDirectionalArrowLength={e => ['shared_evidence', 'related_candidate', 'inconsistent_candidate'].includes(e.kind) ? 0 : 4}
      nodeCanvasObject={(n, ctx, scale) => {
        if (!Number.isFinite(n.x) || !Number.isFinite(n.y)) return;
        ctx.beginPath();
        if (n.kind === 'event') { ctx.moveTo(n.x, n.y - 9); ctx.lineTo(n.x + 9, n.y); ctx.lineTo(n.x, n.y + 9); ctx.lineTo(n.x - 9, n.y); ctx.closePath(); }
        else if (n.kind === 'evidence') ctx.rect(n.x - 6, n.y - 6, 12, 12);
        else ctx.arc(n.x, n.y, n.kind === 'person' ? 8 : 5, 0, 2 * Math.PI);
        const a = n.assessment;
        ctx.fillStyle = a?.core ? '#a855f7' : ({ P1: '#c2410c', P2: '#2563eb', P3: '#64748b' }[a?.priority] || '#334155');
        ctx.fill(); ctx.strokeStyle = '#cbd5e1'; ctx.lineWidth = 1 / scale; ctx.stroke();
        if (a?.core) { ctx.beginPath(); ctx.arc(n.x, n.y, 12, 0, 2 * Math.PI); ctx.strokeStyle = '#a855f7'; ctx.stroke(); }
        if (scale > 0.6 || nodes.length < 30) {
          ctx.font = `${11 / scale}px sans-serif`; ctx.fillStyle = '#f8fafc'; ctx.textAlign = 'center';
          ctx.fillText(n.name.length > 24 ? `${n.name.slice(0, 23)}…` : n.name, n.x, n.y + 10 + 12 / scale);
        }
      }}
      nodePointerAreaPaint={(n, color, ctx) => { ctx.beginPath(); ctx.arc(n.x, n.y, 12, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill(); }}
      onNodeClick={n => onSelect(n.id)} onLinkClick={e => onSelect(e.id)} cooldownTicks={80}
      onEngineStop={() => graph.current?.zoomToFit(250, 40)} />
  </div>;
}
