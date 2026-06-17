// RelationshipsTab.jsx
// "关系" tab content for the Knowledge Graph page.

import Button from '../common/Button';
import Badge from '../common/Badge';

const RelationshipsTab = ({
    taskId,
    relationships,
    relationshipsTotalCount,
    relationshipsPage,
    fetchRelationships,
    PAGE_SIZE,
}) => (
    <div>
        {!taskId ? (
            <p className="text-center text-slate-500 py-8">请先选择一个任务</p>
        ) : (
            <>
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-medium">关系 ({relationshipsTotalCount})</h3>
                    <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => fetchRelationships(relationshipsPage - 1)} disabled={relationshipsPage <= 1}>上一页</Button>
                        <span className="px-3 py-1">{relationshipsPage} / {Math.ceil(relationshipsTotalCount / PAGE_SIZE) || 1}</span>
                        <Button variant="outline" size="sm" onClick={() => fetchRelationships(relationshipsPage + 1)} disabled={relationshipsPage >= Math.ceil(relationshipsTotalCount / PAGE_SIZE)}>下一页</Button>
                    </div>
                </div>
                <table className="w-full text-sm">
                    <thead className="bg-slate-50 dark:bg-slate-700">
                        <tr>
                            <th className="px-4 py-3 text-left">源实体</th>
                            <th className="px-4 py-3 text-left">关系</th>
                            <th className="px-4 py-3 text-left">目标实体</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y">
                        {relationships.map((r, i) => (
                            <tr key={r.id || i} className="hover:bg-slate-50 dark:hover:bg-slate-800">
                                <td className="px-4 py-3">{r.source_name || r.source_id?.substring(0, 8)}</td>
                                <td className="px-4 py-3"><Badge variant="purple">{r.type || 'RELATES_TO'}</Badge></td>
                                <td className="px-4 py-3">{r.target_name || r.target_id?.substring(0, 8)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {relationships.length === 0 && <p className="text-center text-slate-500 py-8">暂无关系数据</p>}
            </>
        )}
    </div>
);

export default RelationshipsTab;
