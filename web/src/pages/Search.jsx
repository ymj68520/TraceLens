import React, { useState } from 'react';
import { searchFulltext, createSearchIndex } from '../services/searchService';
import Card from '../components/common/Card';
import Button from '../components/common/Button';
import Spinner from '../components/common/Spinner';

const Search = () => {
  const [query, setQuery] = useState('');
  const [index, setIndex] = useState('search_index');
  const [sourcePath, setSourcePath] = useState('extracted_files');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('search');

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
    } catch (err) {
      setError(err.message || 'Failed to create index');
    } finally {
      setIndexing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-gray-900">Full-Text Search</h1>
        <p className="mt-2 text-gray-600">Search indexed file contents</p>
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex space-x-8" aria-label="Tabs">
          <button
            onClick={() => setActiveTab('search')}
            className={`${
              activeTab === 'search'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Search
          </button>
          <button
            onClick={() => setActiveTab('index')}
            className={`${
              activeTab === 'index'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            } whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm`}
          >
            Create Index
          </button>
        </nav>
      </div>

      {/* Search Tab */}
      {activeTab === 'search' && (
        <Card>
          <form onSubmit={handleSearch} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Search Query
              </label>
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Enter search terms... (e.g., 'forensics', 'password', 'error')"
              />
              <p className="mt-1 text-xs text-gray-500">
                Supports boolean operators: AND, OR, NOT (e.g., 'forensics AND password')
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Index Path
              </label>
              <input
                type="text"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="/path/to/search/index"
              />
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
          <p className="text-sm text-gray-600 mb-4">
            Before searching, you need to create a search index from extracted files.
          </p>
          <form onSubmit={handleCreateIndex} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Source Path (files to index)
              </label>
              <input
                type="text"
                value={sourcePath}
                onChange={(e) => setSourcePath(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="/path/to/extracted/files"
              />
              <p className="mt-1 text-xs text-gray-500">
                Directory containing files you want to search
              </p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Index Path (where to store the index)
              </label>
              <input
                type="text"
                value={index}
                onChange={(e) => setIndex(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="/path/to/search/index"
              />
              <p className="mt-1 text-xs text-gray-500">
                Directory where the search index will be stored
              </p>
            </div>
            <div className="flex items-center">
              <input
                type="checkbox"
                id="recursive"
                checked={true}
                disabled
                className="h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded"
              />
              <label htmlFor="recursive" className="ml-2 block text-sm text-gray-900">
                Recursive (index subdirectories)
              </label>
            </div>
            <Button type="submit" variant="success" disabled={indexing}>
              {indexing ? 'Creating Index...' : '⚡ Create Index'}
            </Button>
            {indexing && (
              <div className="flex items-center text-sm text-gray-600">
                <Spinner size="sm" />
                <span className="ml-2">Indexing files... This may take a while.</span>
              </div>
            )}
          </form>
        </Card>
      )}

      {error && (
        <Card>
          <div className="p-4 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-800">{error}</p>
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
                <div key={idx} className="p-4 bg-white border border-gray-200 rounded-md hover:bg-gray-50">
                  <div className="flex items-start justify-between">
                    <div className="flex-1">
                      <p className="font-mono text-sm text-gray-900 break-all">{result.path || result.file_path}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        Score: {result.score?.toFixed(2) || 'N/A'}
                        {result.percent && ` | Relevance: ${result.percent.toFixed(1)}%`}
                      </p>
                      {result.snippet && (
                        <div className="mt-2 p-3 bg-yellow-50 border-l-4 border-yellow-400">
                          <p className="text-sm text-gray-700 font-mono">{result.snippet}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-12 text-gray-500">
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
