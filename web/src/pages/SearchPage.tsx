import { useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Search as SearchIcon, Database } from 'lucide-react';
import { searchFulltext, createSearchIndex } from '../services/searchService';
import { useAppSelector } from '../store';
import Card, { CardHeader } from '../components/ui/Card';
import Button from '../components/ui/Button';
import EmptyState from '../components/ui/EmptyState';
import { LoadingBlock } from '../components/ui/Spinner';
import { useToast } from '../components/ui/Toast';
import { errorMessage, formatBytes } from '../lib/utils';

interface SearchHit {
  file_path?: string;
  path?: string;
  snippet?: string;
  score?: number;
  size?: number;
  [key: string]: unknown;
}

interface SearchResults {
  hits?: SearchHit[];
  results?: SearchHit[];
  total?: number;
  [key: string]: unknown;
}

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useAppSelector((state) => state.tasks);
  const toast = useToast();

  const currentTask = tasks.find((t) => t.id === taskId);

  const [query, setQuery] = useState('');
  const [index, setIndex] = useState('');
  const [sourcePath, setSourcePath] = useState('');
  const [results, setResults] = useState<SearchResults | null>(null);
  const [loading, setLoading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [activeTab, setActiveTab] = useState<'search' | 'index'>('search');

  useEffect(() => {
    if (taskId) {
      setIndex(`search_index_${taskId.substring(0, 8)}`);
      setSourcePath(
        (currentTask as { extraction_directory?: string })?.extraction_directory ||
          `../build/data/tasks/${taskId}/extracted_files`,
      );
    }
  }, [taskId, currentTask]);

  const handleSearch = async (e: FormEvent) => {
    e.preventDefault();
    if (!query.trim() || !index.trim()) return;
    setLoading(true);
    try {
      const data = (await searchFulltext(query, index)) as SearchResults;
      setResults(data);
    } catch (err) {
      toast.error(errorMessage(err));
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateIndex = async (e: FormEvent) => {
    e.preventDefault();
    if (!sourcePath.trim() || !index.trim()) return;
    setIndexing(true);
    try {
      await createSearchIndex(sourcePath, index, true);
      toast.success('索引创建完成，可以开始搜索');
      setActiveTab('search');
    } catch (err) {
      toast.error(`索引创建失败：${errorMessage(err)}`);
    } finally {
      setIndexing(false);
    }
  };

  const hits = results?.hits ?? results?.results ?? [];

  return (
    <div className="space-y-4 max-w-5xl">
      <div className="flex rounded-md border border-ink-200 dark:border-ink-700 overflow-hidden w-fit">
        {(
          [
            { key: 'search', label: '全文搜索', Icon: SearchIcon },
            { key: 'index', label: '索引管理', Icon: Database },
          ] as const
        ).map(({ key, label, Icon }) => (
          <button
            key={key}
            type="button"
            onClick={() => setActiveTab(key)}
            className={`px-3 py-1.5 text-xs font-medium inline-flex items-center gap-1.5 transition-colors ${
              activeTab === key
                ? 'bg-accent-600 text-white'
                : 'bg-white dark:bg-ink-900 text-ink-600 dark:text-ink-300 hover:bg-ink-50 dark:hover:bg-ink-800'
            }`}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'index' && (
        <Card>
          <CardHeader title="创建全文索引" subtitle="对提取目录建立搜索索引（首次使用前必需）" />
          <form onSubmit={handleCreateIndex} className="space-y-3">
            <div>
              <label className="field-label">源目录</label>
              <input
                type="text"
                className="input font-mono text-xs"
                value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
              />
            </div>
            <div>
              <label className="field-label">索引名称</label>
              <input
                type="text"
                className="input font-mono text-xs"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
              />
            </div>
            <Button variant="primary" type="submit" disabled={indexing}>
              {indexing ? '创建中…' : '创建索引'}
            </Button>
          </form>
        </Card>
      )}

      {activeTab === 'search' && (
        <>
          <Card>
            <form onSubmit={handleSearch} className="flex gap-2">
              <input
                type="text"
                className="input flex-1"
                placeholder="搜索关键词…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <input
                type="text"
                className="input w-48 font-mono text-xs"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                placeholder="索引名称"
              />
              <Button variant="primary" type="submit" disabled={loading || !query.trim()}>
                <SearchIcon size={14} />
                {loading ? '搜索中…' : '搜索'}
              </Button>
            </form>
          </Card>

          {loading && (
            <Card>
              <LoadingBlock text="搜索中…" />
            </Card>
          )}

          {!loading && results && (
            <Card padded={false}>
              <div className="px-5 py-3 border-b border-ink-200 dark:border-ink-800">
                <span className="text-xs text-ink-500">
                  命中 {results.total ?? hits.length} 条
                </span>
              </div>
              {hits.length === 0 ? (
                <EmptyState title="没有匹配结果" />
              ) : (
                <ul className="divide-y divide-ink-100 dark:divide-ink-800">
                  {hits.map((hit, i) => (
                    <li key={i} className="px-5 py-3">
                      <p className="text-xs font-mono text-accent-600 dark:text-accent-400 truncate">
                        {hit.file_path ?? hit.path}
                      </p>
                      {hit.snippet && (
                        <p className="mt-1 text-xs text-ink-600 dark:text-ink-300 leading-relaxed line-clamp-3">
                          {hit.snippet}
                        </p>
                      )}
                      {typeof hit.size === 'number' && (
                        <p className="mt-0.5 text-2xs text-ink-400">{formatBytes(hit.size)}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}
