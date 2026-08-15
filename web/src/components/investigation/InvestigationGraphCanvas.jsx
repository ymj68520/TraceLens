// InvestigationGraphCanvas.jsx
// Investigation Graph 专用的轻量 ForceGraph2D wrapper（C8c）。
// 复制/改编 WeChatGraph GraphCanvas 的 renderer mechanics；不改 KnowledgeGraph.jsx。
import { useRef, useCallback } from 'react';
import ForceGraph2D from 'react-force-graph-2d';
import {
    getNodeColor,
    getLinkColor,
    isUnconfirmed,
    nodeTooltip,
    linkTooltip,
} from './investigationGraphConstants';

const NODE_RADIUS = {
    InvestigationEvent: 7,
    Evidence: 6,
    Analysis: 6,
    Claim: 4,
};

export default function InvestigationGraphCanvas({ data, onNodeClick, selectedNodeId }) {
    const graphRef = useRef(null);

    const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
        const radius = NODE_RADIUS[node.label] || 5;
        const color = getNodeColor(node);
        const isSelected = selectedNodeId && node.id === selectedNodeId;

        // Halo / glow
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius + (isSelected ? 5 : 2), 0, 2 * Math.PI);
        ctx.fillStyle = color + (isSelected ? '70' : '30');
        ctx.fill();

        // Node circle
        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
        ctx.fillStyle = color;
        ctx.fill();

        if (isSelected) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
            ctx.strokeStyle = '#f8fafc';
            ctx.lineWidth = 1.5;
            ctx.stroke();
        }

        // review_pending fallback 的 Analysis/Claim：虚线描边标注 Unconfirmed
        if (isUnconfirmed(node)) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius + 2, 0, 2 * Math.PI);
            ctx.setLineDash([3, 3]);
            ctx.strokeStyle = '#f8fafc';
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.setLineDash([]);
        }

        if (globalScale >= 1.2) {
            ctx.font = `${11 / globalScale}px Sans-Serif`;
            ctx.textAlign = 'center';
            ctx.fillStyle = '#e2e8f0';
            ctx.fillText(
                node.name || node.id,
                node.x,
                node.y + radius + 11 / globalScale
            );
        }
    }, [selectedNodeId]);

    return (
        <ForceGraph2D
            ref={graphRef}
            graphData={{ nodes: data?.nodes || [], links: data?.links || [] }}
            nodeCanvasObject={nodeCanvasObject}
            nodePointerAreaPaint={(node, color, ctx) => {
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(node.x, node.y, 9, 0, 2 * Math.PI);
                ctx.fill();
            }}
            nodeLabel={nodeTooltip}
            linkLabel={linkTooltip}
            linkColor={getLinkColor}
            linkWidth={1}
            linkDirectionalArrowLength={3}
            linkDirectionalArrowRelPos={1}
            onNodeClick={onNodeClick}
            cooldownTicks={80}
            onEngineStop={() => graphRef.current?.zoomToFit(400, 40)}
            backgroundColor="transparent"
        />
    );
}
