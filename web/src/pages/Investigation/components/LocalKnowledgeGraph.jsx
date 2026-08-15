import { useRef, useState } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

export default function LocalKnowledgeGraph({ graph }) {
  const container = useRef(null);
  const [width] = useState(560);
  if (!graph) return <p className="text-sm text-slate-500">尚未加载局部图谱。</p>;
  if (!graph.nodes?.length) {
    return <div className="rounded-xl bg-slate-50 dark:bg-slate-900/40 p-5 text-center text-sm text-slate-500">{graph.base_available === false ? '知识图谱服务不可用，且当前分析尚未生成 Overlay。' : '当前对象没有局部图谱关系。'}</div>;
  }
  return (
    <div ref={container} className="overflow-hidden rounded-xl border border-slate-200/60 dark:border-slate-700/60 bg-slate-50/70 dark:bg-slate-950/40">
      {graph.base_available === false && <div className="px-3 py-2 text-xs text-amber-600 bg-amber-50 dark:bg-amber-950/20">Base KG 不可用，当前仅展示 Investigation Overlay。</div>}
      <ForceGraph2D
        width={width}
        height={300}
        graphData={{ nodes: graph.nodes, links: graph.links || [] }}
        nodeLabel={(node) => `${node.label} (${node.source_kind})`}
        nodeCanvasObject={(node, ctx, scale) => {
          const label = node.label || node.id;
          ctx.fillStyle = node.source_kind === 'base' ? '#64748b' : node.status === 'accepted' ? '#059669' : '#7c3aed';
          ctx.beginPath(); ctx.arc(node.x, node.y, 5, 0, 2 * Math.PI); ctx.fill();
          ctx.font = `${11 / scale}px Sans-Serif`; ctx.fillStyle = '#94a3b8'; ctx.fillText(label, node.x + 7, node.y + 3);
        }}
        linkColor={(link) => link.source_kind === 'base' ? '#64748b' : link.status === 'accepted' ? '#059669' : '#8b5cf6'}
        linkLineDash={(link) => link.source_kind === 'investigation' && link.status !== 'accepted' ? [4, 3] : null}
        linkDirectionalArrowLength={3}
      />
    </div>
  );
}
