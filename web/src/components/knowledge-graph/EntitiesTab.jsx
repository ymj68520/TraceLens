// EntitiesTab.jsx
// "实体" tab content for the Knowledge Graph page.

import Button from '../common/Button';
import Badge from '../common/Badge';

const EntitiesTab = ({
    taskId,
    entities,
    entitiesTotalCount,
    entitiesPage,
    fetchEntities,
    PAGE_SIZE,
}) => (
    <div>
        {!taskId ? (
            <p className="text-center text-slate-500 py-8">请先选择一个任务</p>
        ) : (
            <>
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-medium">实体 ({entitiesTotalCount})</h3>
                    <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => fetchEntities(entitiesPage - 1)} disabled={entitiesPage <= 1}>上一页</Button>
                        <span className="px-3 py-1">{entitiesPage} / {Math.ceil(entitiesTotalCount / PAGE_SIZE) || 1}</span>
                        <Button variant="outline" size="sm" onClick={() => fetchEntities(entitiesPage + 1)} disabled={entitiesPage >= Math.ceil(entitiesTotalCount / PAGE_SIZE)}>下一页</Button>
                    </div>
                </div>
                <table className="w-full text-sm">
                    <thead className="bg-slate-50 dark:bg-slate-700">
                        <tr>
                            <th className="px-4 py-3 text-left">ID</th>
                            <th className="px-4 py-3 text-left">名称</th>
                            <th className="px-4 py-3 text-left">类型</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y">
                        {entities.map((e, i) => (
                            <tr key={e.id || i} className="hover:bg-slate-50 dark:hover:bg-slate-800">
                                <td className="px-4 py-3 font-mono text-xs">{e.id?.substring(0, 8)}...</td>
                                <td className="px-4 py-3">{e.name || '-'}</td>
                                <td className="px-4 py-3">
                                    <Badge variant="blue">
                                        {Array.isArray(e.type) ? (e.type[0] || 'Entity') : (e.type || 'Entity')}
                                    </Badge>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {entities.length === 0 && <p className="text-center text-slate-500 py-8">暂无实体数据</p>}
            </>
        )}
    </div>
);

export default EntitiesTab;
