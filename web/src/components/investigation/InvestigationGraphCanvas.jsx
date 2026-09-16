// InvestigationGraphCanvas.jsx
// Investigation Graph 专用的轻量 ForceGraph2D wrapper（C8c）。
// 复制/改编 WeChatGraph GraphCanvas 的 renderer mechanics；不改 KnowledgeGraph.jsx。
//
// 渲染修复说明：
//  - graphData 用 useMemo 稳定引用。内联字面量会在父组件每次重渲染时生成
//    新引用，force-graph 会反复 re-heat 仿真，布局永远收敛不了。
//  - 显式传入容器测得的 width/height。ForceGraph2D 在挂载瞬间如果读到 0
//    尺寸，画布会以错误尺寸初始化，节点散落在可视区外。
//  - 节点播种环形初始坐标：d3-force 的默认初始位置集中在原点附近，
//    少迭代次数（cooldownTicks=80）下多节点可能叠成一团。
//  - zoomToFit 不只挂在 onEngineStop（仿真被重启时可能永远不触发），
//    数据变化后按布局耗时做两次兜底适配。
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
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

const LAYOUT_COOLDOWN_MS = 80 * 16 + 200; // cooldownTicks(80) × ~16ms/tick + margin

export default function InvestigationGraphCanvas({ data, onNodeClick, selectedNodeId }) {
    const graphRef = useRef(null);
    const containerRef = useRef(null);
    const [size, setSize] = useState({ width: 0, height: 0 });

    // Measure the wrapper so the canvas gets a real pixel size even when the
    // tab/panel becomes visible after mount. jsdom (tests) has neither
    // ResizeObserver nor layout — fall back to auto-sizing via undefined.
    useEffect(() => {
        const el = containerRef.current;
        if (!el || typeof ResizeObserver === 'undefined') return undefined;
        const measure = () => setSize({
            width: Math.floor(el.clientWidth || 0),
            height: Math.floor(el.clientHeight || 0),
        });
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(el);
        return () => observer.disconnect();
    }, []);

    // Stable graphData identity across unrelated parent re-renders. Nodes get
    // a deterministic ring seed so every node starts on-canvas even if the
    // force simulation barely runs. Positions are assigned in place (the same
    // way force-graph itself writes x/y back into the node objects), keeping
    // the node array identity/shape intact for the renderer.
    const graphData = useMemo(() => {
        const nodes = data?.nodes || [];
        const count = Math.max(1, nodes.length);
        const radius = 50 + 14 * Math.sqrt(count);
        nodes.forEach((node, i) => {
            if (typeof node.x === 'number' && typeof node.y === 'number') return;
            const angle = (2 * Math.PI * i) / count;
            node.x = radius * Math.cos(angle);
            node.y = radius * Math.sin(angle);
        });
        return { nodes, links: data?.links || [] };
    }, [data]);

    const fitView = useCallback(() => {
        graphRef.current?.zoomToFit(400, 40);
    }, []);

    // Adapt the viewport once right away (ring seed is already spread out) and
    // once after the force layout settles.
    useEffect(() => {
        if (!graphData.nodes.length || !size.width) return undefined;
        const early = setTimeout(fitView, 400);
        const settled = setTimeout(fitView, LAYOUT_COOLDOWN_MS);
        return () => { clearTimeout(early); clearTimeout(settled); };
    }, [graphData, size.width, fitView]);

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
        <div ref={containerRef} className="h-full w-full">
            <ForceGraph2D
                ref={graphRef}
                width={size.width || undefined}
                height={size.height || undefined}
                graphData={graphData}
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
                onEngineStop={fitView}
                backgroundColor="transparent"
            />
        </div>
    );
}
