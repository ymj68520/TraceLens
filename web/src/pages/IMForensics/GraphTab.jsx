// IMForensics 的「关系分析」Tab。
// 自独立页 WeChatGraph.jsx 平移（2026-09-15 三页合并），数据源由页面按
// 平台前缀 + 导入 ID 拼出后经 props 传入；全局任务上下文（task_id 覆盖）时
// 顶部展示来源提示条，允许一键切回当前导入的图谱。
import { useEffect, useRef, useState } from 'react';
import { Link2Off } from 'lucide-react';
import Card from '../../components/common/Card';
import useWeChatGraph from './graph/hooks/useWeChatGraph';
import GraphCanvas from './graph/components/GraphCanvas';
import ChatPanel from './graph/components/ChatPanel';
import TimelineSlider from './graph/components/TimelineSlider';
import CommunityLegend from './graph/components/CommunityLegend';
import PersonDetail from './graph/components/PersonDetail';
import SearchBar from './graph/components/SearchBar';
import '../../styles/wechat-graph.css';

// 画布尺寸跟随容器：react-force-graph-2d 不传宽高时会取窗口尺寸，嵌在 Tab 里会溢出
const useElementSize = () => {
  const ref = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return undefined;
    const update = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    update();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
};

export default function GraphTab({ taskId, overrideTaskId, onClearOverride }) {
  const {
    graphData,
    filteredGraphData,
    timelineData,
    loading,
    error,
    selectedNode,
    selectedEdge,
    chatMessages,
    chatTotal,
    chatLoading,
    selectedCommunity,
    searchQuery,
    setSelectedCommunity,
    setSearchQuery,
    handleEdgeClick,
    handleNodeClick,
    handleBackgroundClick,
    loadChatHistory,
    loadGroupChat,
    refreshGraph,
  } = useWeChatGraph(taskId ?? null);

  const [canvasRef, canvasSize] = useElementSize();

  if (!taskId) {
    return (
      <Card animate={false}>
        <div className="flex flex-col items-center gap-2 py-12 text-center">
          <p className="text-slate-500">暂无图谱数据源</p>
          <p className="max-w-md text-sm text-slate-400">
            导入微信 / QQ 账号数据库并选中一条导入后，即可查看对应的聊天关系图谱。
          </p>
        </div>
      </Card>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-72">
        <div className="text-slate-400">加载关系图中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-72">
        <div className="text-red-400">{error}</div>
      </div>
    );
  }

  if (!graphData || graphData.nodes?.length === 0) {
    return (
      <Card animate={false}>
        <p className="py-12 text-center text-slate-400">未发现聊天记录关系数据</p>
      </Card>
    );
  }

  const sidePanelContent = () => {
    if (selectedEdge) {
      return (
        <ChatPanel
          edge={selectedEdge}
          messages={chatMessages}
          total={chatTotal}
          loading={chatLoading}
          onLoadMore={(offset) => {
            const src =
              typeof selectedEdge.source === 'object'
                ? selectedEdge.source.id
                : selectedEdge.source;
            const tgt =
              typeof selectedEdge.target === 'object'
                ? selectedEdge.target.id
                : selectedEdge.target;
            if (selectedEdge.edge_type === 'group' && selectedEdge.chatroom) {
              loadGroupChat(selectedEdge.chatroom, offset);
            } else {
              loadChatHistory(src, tgt, offset);
            }
          }}
          onClose={handleBackgroundClick}
        />
      );
    }
    if (selectedNode) {
      return (
        <PersonDetail
          node={selectedNode}
          graphData={graphData}
          onClose={handleBackgroundClick}
        />
      );
    }
    return (
      <CommunityLegend
        communities={graphData?.communities || []}
        selected={selectedCommunity}
        onSelect={setSelectedCommunity}
      />
    );
  };

  return (
    <div className="flex flex-col gap-4">
      {overrideTaskId && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-sky-50 px-3 py-2 text-xs text-sky-800 ring-1 ring-sky-100">
          图谱数据源：任务上下文 <span className="font-mono">{overrideTaskId}</span>（来自顶部任务选择器）
          <button
            type="button"
            onClick={onClearOverride}
            className="ml-auto inline-flex items-center gap-1 rounded-lg bg-white/70 px-2.5 py-1 font-medium text-sky-700 ring-1 ring-sky-200 hover:bg-sky-100"
          >
            <Link2Off size={12} /> 改用当前导入数据
          </button>
        </div>
      )}
      <SearchBar
        query={searchQuery}
        onChange={setSearchQuery}
        onRefresh={refreshGraph}
      />
      <div className="flex flex-1 gap-4 min-h-0" style={{ height: 'max(440px, calc(100vh - 26rem))' }}>
        <div ref={canvasRef} className="flex-1 rounded-xl overflow-hidden bg-gradient-to-br from-slate-900 to-slate-800">
          <GraphCanvas
            data={filteredGraphData}
            width={canvasSize.width || undefined}
            height={canvasSize.height || undefined}
            onNodeClick={handleNodeClick}
            onEdgeClick={handleEdgeClick}
            onBackgroundClick={handleBackgroundClick}
          />
        </div>
        <div className="w-80 shrink-0 overflow-y-auto">{sidePanelContent()}</div>
      </div>
      {timelineData && timelineData.length > 0 && (
        <TimelineSlider
          data={timelineData}
          onRangeChange={() => {}}
        />
      )}
    </div>
  );
}
