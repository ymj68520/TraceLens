import React from 'react';

const MSG_TYPE_LABELS = {
    1: '文本',
    3: '图片',
    34: '语音',
    43: '视频',
    47: '表情',
    49: '链接',
};

export default function ChatPanel({
    edge,
    messages,
    total,
    loading,
    onLoadMore,
    onClose,
}) {
    const srcLabel =
        typeof edge.source === 'object' ? edge.source.label : edge.source;
    const tgtLabel =
        typeof edge.target === 'object' ? edge.target.label : edge.target;

    return (
        <div className="flex flex-col h-full bg-slate-800 rounded-xl overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between p-3 border-b border-slate-700">
                <div>
                    <div className="text-sm font-medium text-slate-200">
                        {srcLabel} &harr; {tgtLabel}
                    </div>
                    <div className="text-xs text-slate-400">
                        共 {edge.weight || 0} 条消息
                    </div>
                </div>
                <button
                    onClick={onClose}
                    className="text-slate-400 hover:text-slate-200"
                >
                    &#10005;
                </button>
            </div>

            {/* Messages */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3 wechat-chat-scroll">
                {messages.map((msg, i) => {
                    const isOwner = msg.is_send === 1;
                    return (
                        <div
                            key={i}
                            className={`flex ${isOwner ? 'justify-end' : 'justify-start'}`}
                        >
                            <div className="max-w-[80%]">
                                {!isOwner && (
                                    <div className="text-xs text-slate-400 mb-1">
                                        {msg.sender_nickname || msg.sender}
                                    </div>
                                )}
                                <div
                                    className={`rounded-lg px-3 py-2 text-sm ${
                                        isOwner
                                            ? 'bg-green-600 text-white chat-bubble-right'
                                            : 'bg-slate-600 text-slate-100 chat-bubble-left'
                                    }`}
                                >
                                    {msg.msg_type === 1
                                        ? msg.content
                                        : `[${MSG_TYPE_LABELS[msg.msg_type] || '消息'}]`}
                                </div>
                                <div className="text-xs text-slate-500 mt-1">
                                    {msg.timestamp
                                        ? new Date(
                                              msg.timestamp
                                          ).toLocaleString()
                                        : ''}
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Load more */}
            {messages.length < total && (
                <button
                    onClick={() => onLoadMore(messages.length)}
                    disabled={loading}
                    className="p-2 text-sm text-blue-400 hover:text-blue-300 border-t border-slate-700"
                >
                    {loading ? '加载中...' : '加载更多'}
                </button>
            )}
        </div>
    );
}
