import { useEffect, useMemo, useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

const escapeTooltip = (value) => String(value || '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[character]));

const shortName = (node) => {
  const name = node?.name || node?.id || '';
  return name.startsWith('/') ? `${name.split('/').pop()}（路径）` : name;
};

export default function LocalKnowledgeGraph({ graph }) {
  const container = useRef(null);
  const canvas = useRef(null);
  const [width, setWidth] = useState(560);
  // ForceGraph mutates its input to attach positions and node references;
  // retain the untouched response for the exact relation list below.
  const graphData = useMemo(() => ({
    nodes: (graph?.nodes || []).map((node) => ({ ...node })),
    links: (graph?.links || []).map((link) => ({ ...link })),
  }), [graph]);
  const nodeById = useMemo(() => new Map((graph?.nodes || []).map((node) => [node.id, node])), [graph]);

  useEffect(() => {
    const element = container.current;
    if (!element) return undefined;
    const measure = () => setWidth(Math.max(280, Math.floor(element.clientWidth)));
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [graph]);

  if (!graph) return <p className="text-sm text-slate-500">尚未加载局部图谱。</p>;
  if (!graph.nodes?.length) {
    return <div className="rounded-xl bg-slate-50 dark:bg-slate-900/40 p-5 text-center text-sm text-slate-500">{graph.base_available === false ? '知识图谱服务不可用，且当前证据尚无调查关系。' : '当前证据没有可核实的局部图谱关系。'}</div>;
  }
  return (
    <div ref={container} data-testid="local-evidence-graph" className="overflow-hidden rounded-xl border border-slate-200/60 dark:border-slate-700/60 bg-slate-50/70 dark:bg-slate-950/40">
      {graph.base_available === false && <div className="px-3 py-2 text-xs text-amber-600 bg-amber-50 dark:bg-amber-950/20">Base KG 不可用，当前仅展示 Investigation Overlay。</div>}
      <div className="px-3 pt-2 text-xs text-slate-500">当前证据关联图 · {graph.nodes.length} 节点 / {(graph.links || []).length} 关系。悬停查看实体和关系详情。</div>
      <ForceGraph2D
        ref={canvas}
        width={width}
        height={340}
        graphData={graphData}
        nodeLabel={(node) => `${escapeTooltip(node.name || node.id)} · ${escapeTooltip(node.label)}${node.summary ? `<br>${escapeTooltip(node.summary.slice(0, 260))}` : ''}`}
        linkLabel={(link) => escapeTooltip(link.label || '关联')}
        nodeCanvasObject={(node, ctx, scale) => {
          if (!Number.isFinite(node.x) || !Number.isFinite(node.y)) return;
          const label = shortName(node);
          const isEvidence = node.label === 'Evidence';
          ctx.fillStyle = isEvidence ? '#2563eb' : node.source === 'base_kg' ? '#7c3aed' : node.confirmed ? '#059669' : '#0891b2';
          ctx.beginPath(); ctx.arc(node.x, node.y, isEvidence ? 7 : 5, 0, 2 * Math.PI); ctx.fill();
          ctx.font = `${12 / scale}px Sans-Serif`;
          ctx.fillStyle = '#475569';
          ctx.fillText(label.length > 28 ? `${label.slice(0, 27)}…` : label, node.x + 9, node.y + 4);
        }}
        linkColor={(link) => link.kind === 'base_relation' ? '#a78bfa' : '#38bdf8'}
        linkLineDash={(link) => link.kind !== 'base_relation' ? [4, 3] : null}
        linkDirectionalArrowLength={3}
        onEngineStop={() => canvas.current?.zoomToFit(300, 45)}
      />
      {!!graph.links?.length && <div className="border-t border-slate-200/70 px-3 py-3 dark:border-slate-700/70" data-testid="local-graph-relations">
        <div className="mb-2 text-xs font-semibold text-slate-600 dark:text-slate-300">关系明细</div>
        <ul className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
          {graph.links.slice(0, 12).map((link) => <li key={link.id} className="break-words">
            <span className="font-medium">{shortName(nodeById.get(link.source))}</span>
            <span className="mx-1 text-primary-600 dark:text-primary-300">— {link.label} →</span>
            <span className="font-medium">{shortName(nodeById.get(link.target))}</span>
          </li>)}
        </ul>
        {graph.links.length > 12 && <p className="mt-2 text-xs text-slate-500">另有 {graph.links.length - 12} 条关系；可在画布中悬停查看。</p>}
      </div>}
    </div>
  );
}
