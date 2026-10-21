import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import { peopleStyle } from './peopleGraphStyles';

const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export default function PeopleGraphCanvas({ nodes = [], links = [], selectedId, onNode, onLink }) {
  const container = useRef(null);
  const graph = useRef(null);
  const [width, setWidth] = useState(600);
  // ForceGraph mutates endpoints and positions; never mutate the stored API projection.
  const data = useMemo(() => ({ nodes: nodes.map(n => ({ ...n })), links: links.map(l => ({ ...l })) }), [nodes, links]);
  useEffect(() => {
    if (!container.current) return undefined;
    const resize = () => setWidth(Math.max(220, container.current?.clientWidth || 600));
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(container.current);
    return () => observer.disconnect();
  }, []);
  return <div ref={container} className="min-w-0 overflow-hidden rounded-xl bg-slate-950" data-testid="people-graph-canvas">
    <ForceGraph2D ref={graph} width={width} height={480} graphData={data} backgroundColor="#0f172a"
      nodeLabel={node => `${escape(node.name)} · ${escape(peopleStyle(node.assessment).label)}${node.context_only ? ' · 上下文' : ''}`}
      linkLabel={link => `${escape(link.label)} · ${link.context_only ? '上下文关系' : escape(peopleStyle(link.assessment).label)} · 点击回查`}
      linkColor={link => link.context_only ? 'rgba(148,163,184,0.3)' : peopleStyle(link.assessment).color}
      linkWidth={link => link.context_only ? 0.7 : link.assessment?.priority === 'P1' ? 2.5 : 1}
      linkLineDash={link => link.context_only || link.assessment?.priority === 'unassessed' ? [4, 3] : []}
      linkDirectionalArrowLength={4} linkDirectionalArrowRelPos={1}
      nodeCanvasObject={(node, ctx, scale) => {
        const style = peopleStyle(node.assessment);
        const radius = node.context_only ? 4 : style.radius;
        ctx.globalAlpha = node.context_only ? 0.45 : 1;
        ctx.beginPath(); ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = style.color;
        if (node.assessment?.priority === 'unassessed') { ctx.strokeStyle = style.color; ctx.lineWidth = 1.5; ctx.stroke(); }
        else ctx.fill();
        if (node.assessment?.core || selectedId === node.id) {
          ctx.beginPath(); ctx.arc(node.x, node.y, radius + 4, 0, 2 * Math.PI);
          ctx.strokeStyle = selectedId === node.id ? '#fff' : style.color; ctx.lineWidth = 1.5; ctx.stroke();
        }
        if (scale > 1 || node.assessment?.core || selectedId === node.id) {
          ctx.fillStyle = '#f8fafc'; ctx.textAlign = 'center'; ctx.font = `${Math.max(10 / scale, 3)}px sans-serif`;
          ctx.fillText(`${node.assessment?.core ? '核心 · ' : ''}${node.name}`, node.x, node.y + radius + 12 / scale);
        }
        ctx.globalAlpha = 1;
      }}
      nodePointerAreaPaint={(node, color, ctx) => { ctx.beginPath(); ctx.arc(node.x, node.y, 12, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill(); }}
      onNodeClick={onNode} onLinkClick={onLink} cooldownTicks={80}
      onEngineStop={() => graph.current?.zoomToFit(250, 35)} />
  </div>;
}
