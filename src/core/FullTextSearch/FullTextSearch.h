#pragma once

#include <string>
#include <vector>
#include <memory>
#include <unordered_map>
#include <mutex>
#include <cstdint>
#include <xapian.h>

namespace forensics {

/**
 * @brief File metadata for enhanced indexing
 */
struct FileMetadata {
    std::string path;
    std::string extension;
    int64_t size = 0;
    int64_t mtime = 0;  // Modification time (Unix timestamp)
};

/**
 * @brief Full-text search result with snippet
 */
struct SearchResult {
    std::string path;
    double score;
    std::string snippet;
    int64_t fileSize = 0;
    std::string extension;
};

/**
 * @brief Content cache entry for snippet generation
 */
struct ContentCacheEntry {
    std::string content;
    int64_t indexTime;
};

/**
 * @brief Xapian-based full-text indexer
 * 
 * Indexes file contents for efficient search. Supports:
 * - Multi-language stemming
 * - Metadata indexing (size, extension, mtime)
 * - Content caching for snippet generation
 */
class XapianIndexer {
public:
    explicit XapianIndexer(const std::string& dbPath);
    ~XapianIndexer();

    /**
     * @brief Add a document with just path and content
     */
    void addDocument(const std::string& filePath, const std::string& content);
    
    /**
     * @brief Add a document with metadata for enhanced searching
     */
    void addDocument(const std::string& filePath, const std::string& content, const FileMetadata& metadata);
    
    /**
     * @brief Commit pending changes to the database
     */
    void commit();
    
    /**
     * @brief Set the language for stemming (default: english)
     */
    void setStemmerLanguage(const std::string& language);
    
    /**
     * @brief Get the number of documents in the index
     */
    size_t getDocumentCount() const;

private:
    std::string dbPath_;
    std::unique_ptr<Xapian::WritableDatabase> db_;
    Xapian::TermGenerator termGenerator_;
    std::string stemmerLanguage_ = "english";
    
    // Static content cache for snippet generation
    static std::unordered_map<std::string, ContentCacheEntry> contentCache_;
    static std::mutex cacheMutex_;
    
    void cacheContent(const std::string& path, const std::string& content);
    
    // Allow XapianSearcher to access the content cache for snippet generation
    friend class XapianSearcher;
};

/**
 * @brief Xapian-based full-text searcher
 * 
 * Searches indexed documents with support for:
 * - Query parsing with boolean operators
 * - Wildcard matching
 * - Path prefix search (path:...)
 * - Extension filtering (ext:...)
 * - Snippet generation
 */
class XapianSearcher {
public:
    explicit XapianSearcher(const std::string& dbPath);
    ~XapianSearcher();

    /**
     * @brief Search for documents matching the query
     * 
     * @param queryStr Search query (supports boolean operators, wildcards)
     * @param limit Maximum number of results
     * @param offset Number of results to skip (for pagination)
     * @return Vector of search results with snippets
     */
    std::vector<SearchResult> search(const std::string& queryStr, size_t limit = 10, size_t offset = 0);
    
    /**
     * @brief Set maximum snippet length in characters
     */
    void setSnippetLength(size_t length);
    
    /**
     * @brief Check if the database is valid and ready for searching
     */
    bool isValid() const;
    
    /**
     * @brief Get total number of documents in the database
     */
    size_t getTotalDocuments() const;

private:
    std::string dbPath_;
    std::unique_ptr<Xapian::Database> db_;
    size_t snippetLength_ = 150;
    
    std::string generateSnippet(const std::string& path, const Xapian::Query& query);
    std::string highlightTerms(const std::string& text, const std::vector<std::string>& terms);
};

}
