import { useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';

const COMMUNITY_COLORS = [
    '#3b82f6',
    '#ef4444',
    '#22c55e',
    '#f59e0b',
    '#8b5cf6',
    '#ec4899',
    '#06b6d4',
    '#f97316',
];

export default function GraphCanvas({
    data,
    onNodeClick,
    onEdgeClick,
    onBackgroundClick,
}) {
    const graphRef = useRef(null);

    const getNodeColor = useCallback(
        (node) =>
            node.is_owner
                ? '#fbbf24'
                : COMMUNITY_COLORS[
                      ((node.community ?? node.cluster ?? -1) + COMMUNITY_COLORS.length) % COMMUNITY_COLORS.length
                  ] || '#94a3b8',
        []
    );

    const getLinkWidth = useCallback(
        (link) => Math.max(1, Math.min(8, (link.weight || 1) / 10)),
        []
    );

    const getLinkColor = useCallback(() => 'rgba(148, 163, 184, 0.6)', []);

    const nodeCanvasObject = useCallback(
        (node, ctx, globalScale) => {
            const size = node.is_owner ? 8 : 5;
            const color = getNodeColor(node);

            // Glow
            ctx.beginPath();
            ctx.arc(node.x, node.y, size + 2, 0, 2 * Math.PI);
            ctx.fillStyle = color + '40';
            ctx.fill();

            // Node circle
            ctx.beginPath();
            ctx.arc(node.x, node.y, size, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.fill();

            // Label (show when zoomed in)
            if (globalScale >= 1.2) {
                ctx.font = `${12 / globalScale}px Sans-Serif`;
                ctx.textAlign = 'center';
                ctx.fillStyle = '#e2e8f0';
                ctx.fillText(
                    node.label || node.id,
                    node.x,
                    node.y + size + 12 / globalScale
                );
            }
        },
        [getNodeColor]
    );

    return (
        <ForceGraph2D
            ref={graphRef}
            graphData={{ nodes: data?.nodes || [], links: data?.links || data?.edges || [] }}
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node, color, ctx) => {
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI);
                ctx.fill();
            }}
            linkColor={getLinkColor}
            linkWidth={getLinkWidth}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            onNodeClick={onNodeClick}
            onLinkClick={onEdgeClick}
            onBackgroundClick={onBackgroundClick}
            cooldownTicks={80}
            onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
            backgroundColor="transparent"
        />
    );
}
