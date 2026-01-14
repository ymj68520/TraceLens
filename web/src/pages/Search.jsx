
import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { searchFulltext, createSearchIndex } from '../services/searchService';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Spinner from '../components/common/Spinner';
import Badge from '../components/common/Badge';

const Search = () => {
  const [searchParams] = useSearchParams();
  const taskId = searchParams.get('task_id');
  const { tasks } = useSelector((state) => state.tasks);

  const currentTask = tasks.find((t) => t.id === taskId);

  const [query, setQuery] = useState('');
  // Auto-populate paths based on task
  const [index, setIndex] = useState(taskId ? `search_index_${taskId.substring(0, 8)}` : 'search_index');
  const [sourcePath, setSourcePath] = useState(taskId ? `extracted_files/${taskId}` : 'extracted_files');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('search');

  // Update paths when task changes
  useEffect(() => {
    if (taskId) {
      setIndex(`search_index_${taskId.substring(0, 8)}`);
      setSourcePath(`extracted_files/${taskId}`);
    }
  }, [taskId]);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim() || !index.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const data = await searchFulltext(query, index);
      setResults(data);
    } catch (err) {
      setError(err.message || 'Search failed');
      setResults(null);
    } finally {
      setLoading(false);
    }
  };

  const handleCreateIndex = async (e) => {
    e.preventDefault();
    if (!sourcePath.trim() || !index.trim()) return;

    setIndexing(true);
    setError(null);
    try {
      const result = await createSearchIndex(sourcePath, index, true);
      alert('Index created successfully! You can now search.');
      console.log('Index created:', result);
      // Switch to search tab after indexing
      setActiveTab('search');
    } catch (err) {
      setError(err.message || 'Failed to create index');
    } finally {
      setIndexing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900 dark:text-white">Full-Text Search</h1>
        <p className="mt-2 text-gray-600 dark:text-gray-300">Search indexed file contents</p>
        {currentTask && (
          <div className="mt-2">
            <Badge variant="blue">{currentTask.status}</Badge>
            <span className="ml-2 text-sm text-gray-600 dark:text-gray-400">
              Task: {currentTask.image_path?.split('/').pop() || taskId}
            </span>
          </div>
        )}
      </div>

      {/* Task context info */}
      {taskId && (
        <Card className="bg-blue-50 dark:bg-blue-900/10 border-blue-200 dark:border-blue-800">
          <div className="flex items-center space-x-2 text-sm text-blue-800 dark:text-blue-200">
            <span className="font-medium">📋 Task Context:</span>
            <span>Searching files from task {taskId.substring(0, 8)}...</span>
          </div>
        </Card>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200 dark:border-gray-700">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          <button
            onClick={() => setActiveTab('search')}
            className={`${activeTab === 'search'
              ? 'border-blue-500 text-blue-600 dark:text-blue-400 dark:border-blue-400'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300 dark:hover:border-gray-600'
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            🔍 Search
          </button>
          <button
            onClick={() => setActiveTab('index')}
            className={`${activeTab === 'index'
              ? 'border-blue-500 text-blue-600 dark:text-blue-400 dark:border-blue-400'
              : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300 dark:hover:border-gray-600'
              } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            ⚡ Create Index
          </button>
        </nav>
      </div>

      {/* Search Tab */}
      {activeTab === 'search' && (
        <Card>
          <form onSubmit={handleSearch} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Search Query
              </label>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400"
                placeholder="Enter search terms... (e.g., 'forensics', 'password', 'error')"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Supports boolean operators: AND, OR, NOT (e.g., &apos;forensics AND password&apos;)
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Index Path
              </label>
              <input
                type="text"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400"
                placeholder="/path/to/search/index"
              />
              {taskId && (
                <p className="mt-1 text-xs text-blue-600 dark:text-blue-400">
                  ℹ️ Index path auto-populated based on current task
                </p>
              )}
            </div>
            <Button type="submit" disabled={loading}>
              {loading ? 'Searching...' : '🔍 Search'}
            </Button>
          </form>
        </Card>
      )}

      {/* Create Index Tab */}
      {activeTab === 'index' && (
        <Card title="Create Search Index">
          <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">
            Before searching, you need to create a search index from extracted files.
            {taskId && (
              <span className="text-blue-600 dark:text-blue-400 ml-1">
                Recommended: Extract files first from the Files page, then create an index here.
              </span>
            )}
          </p>
          <form onSubmit={handleCreateIndex} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Source Path (files to index)
              </label>
              <input
                type="text"
                value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400"
                placeholder="/path/to/extracted/files"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Directory containing files you want to search
              </p>
              {taskId && (
                <p className="mt-1 text-xs text-blue-600 dark:text-blue-400">
                  ℹ️ Source path auto-populated based on current task
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                Index Path (where to store the index)
              </label>
              <input
                type="text"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400"
                placeholder="/path/to/search/index"
              />
              <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                Directory where the search index will be stored
              </p>
            </div>
            <div className="flex items-center">
              <input
                type="checkbox"
                id="recursive"
                checked={true}
                disabled
                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded dark:bg-gray-700 dark:border-gray-600"
              />
              <label htmlFor="recursive" className="ml-2 block text-sm text-gray-900 dark:text-white">
                Recursive (index subdirectories)
              </label>
            </div>
            <Button type="submit" variant="success" disabled={indexing}>
              {indexing ? 'Creating Index...' : '⚡ Create Index'}
            </Button>
            {indexing && (
              <div className="flex items-center text-sm text-gray-600 dark:text-gray-300">
                <Spinner size="sm" />
                <span className="ml-2">Indexing files... This may take a while.</span>
              </div>
            )}
          </form>
        </Card>
      )}

      {error && (
        <Card>
          <div className="p-4 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 rounded-md">
            <p className="text-sm text-red-800 dark:text-red-200">{error}</p>
          </div>
        </Card>
      )}

      {results && activeTab === 'search' && (
        <Card title={`Search Results (${results.count || results.results?.length || 0} found)`}>
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <Spinner size="lg" />
            </div>
          ) : results.results && results.results.length > 0 ? (
            <div className="space-y-4">
              {results.results.map((result, idx) => (
                <div key={idx} className="p-4 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <p className="font-mono text-sm text-gray-900 dark:text-white break-all">{result.path || result.file_path}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                        Score: {result.score?.toFixed(2) || 'N/A'}
                        {result.percent && ` | Relevance: ${result.percent.toFixed(1)}%`}
                      </p>
                      {result.snippet && (
                        <div className="mt-2 p-3 bg-yellow-50 dark:bg-yellow-900/10 border-l-4 border-yellow-400 dark:border-yellow-600">
                          <p className="text-sm text-gray-700 dark:text-gray-300 font-mono">{result.snippet}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500 dark:text-gray-400">
              <p className="text-lg">No results found</p>
              <p className="text-sm mt-2">Try different search terms or create a new index</p>
            </div>
          )}
        </Card>
      )}
    </div>
  );
};

export default Search;
