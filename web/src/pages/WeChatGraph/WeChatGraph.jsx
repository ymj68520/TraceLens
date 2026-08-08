import useWeChatGraph from './hooks/useWeChatGraph';
import GraphCanvas from './components/GraphCanvas';
import ChatPanel from './components/ChatPanel';
import TimelineSlider from './components/TimelineSlider';
import CommunityLegend from './components/CommunityLegend';
import PersonDetail from './components/PersonDetail';
import SearchBar from './components/SearchBar';
import '../../styles/wechat-graph.css';

export default function WeChatGraph() {
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
    } = useWeChatGraph();

    if (loading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-slate-400">加载关系图中...</div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-red-400">{error}</div>
            </div>
        );
    }

    if (!graphData || graphData.nodes?.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="text-slate-400">未发现微信聊天记录</div>
            </div>
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
        <div className="flex flex-col h-full p-4 gap-4">
            <SearchBar
                query={searchQuery}
                onChange={setSearchQuery}
                onRefresh={refreshGraph}
            />
            <div className="flex flex-1 gap-4 min-h-0">
                <div className="flex-1 rounded-xl overflow-hidden bg-gradient-to-br from-slate-900 to-slate-800">
                    <GraphCanvas
                        data={filteredGraphData}
                        onNodeClick={handleNodeClick}
                        onEdgeClick={handleEdgeClick}
                        onBackgroundClick={handleBackgroundClick}
                    />
                </div>
                <div className="w-80 shrink-0">{sidePanelContent()}</div>
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
