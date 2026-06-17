// SearchTab.jsx
// "搜索" tab content for the Knowledge Graph page.

import Card from '../common/Card';
import Button from '../common/Button';
import Badge from '../common/Badge';

const SearchTab = ({
    taskId,
    searchQuery,
    setSearchQuery,
    handleSearch,
    searching,
    searchResults,
}) => (
    <div>
        <form onSubmit={handleSearch} className="mb-6">
            <div className="flex gap-4">
                <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="搜索实体或关系..."
                    disabled={!taskId}
                    className="flex-1 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-xl bg-white dark:bg-slate-800 text-slate-900 dark:text-white disabled:opacity-50"
                />
                <Button type="submit" disabled={searching || !searchQuery.trim() || !taskId}>
                    {searching ? '搜索中...' : '搜索'}
                </Button>
            </div>
        </form>
        {!taskId ? (
            <p className="text-center text-slate-500 py-8">请先选择一个任务</p>
        ) : searchResults.length > 0 ? (
            <div className="space-y-4">
                <h3 className="text-lg font-medium text-slate-900 dark:text-white">搜索结果 ({searchResults.length})</h3>
                <div className="grid gap-4">
                    {searchResults.map((result, index) => (
                        <Card key={result.entity_id || index}>
                            <div className="flex justify-between items-start">
                                <div>
                                    <h4 className="font-medium text-slate-900 dark:text-white">{result.name || '未命名实体'}</h4>
                                    <Badge variant="blue">{result.entity_type}</Badge>
                                </div>
                                <span className="text-sm text-slate-400">相关度: {(result.score * 100).toFixed(1)}%</span>
                            </div>
                        </Card>
                    ))}
                </div>
            </div>
        ) : searchResults.length === 0 && searchQuery && !searching ? (
            <p className="text-center text-slate-500 py-8">未找到相关实体</p>
        ) : null}
    </div>
);

export default SearchTab;
