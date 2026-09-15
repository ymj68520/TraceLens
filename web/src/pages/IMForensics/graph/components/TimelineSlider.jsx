import {
    AreaChart,
    Area,
    XAxis,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    Brush,
} from 'recharts';

export default function TimelineSlider({ data, onRangeChange }) {
    // data can be either an array directly or an object with intervals
    const intervals = Array.isArray(data) ? data : data?.intervals || data?.timeline || [];

    if (intervals.length === 0) return null;

    return (
        <div className="h-32 bg-slate-800 rounded-xl p-3">
            <div className="text-xs text-slate-400 mb-2">消息时间线</div>
            <ResponsiveContainer width="100%" height="85%">
                <AreaChart data={intervals}>
                    <XAxis
                        dataKey="period"
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                    />
                    <YAxis
                        tick={{ fill: '#94a3b8', fontSize: 10 }}
                        width={40}
                    />
                    <Tooltip
                        contentStyle={{
                            background: '#1e293b',
                            border: '1px solid #334155',
                            borderRadius: '8px',
                        }}
                        labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Area
                        type="monotone"
                        dataKey="total_messages"
                        stroke="#3b82f6"
                        fill="#3b82f680"
                    />
                    <Brush
                        dataKey="period"
                        height={20}
                        stroke="#475569"
                        fill="#1e293b"
                        onChange={(range) => onRangeChange?.(range)}
                    />
                </AreaChart>
            </ResponsiveContainer>
        </div>
    );
}
