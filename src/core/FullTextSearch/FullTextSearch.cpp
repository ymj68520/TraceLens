#include "LLMIntegration/ConfigManager.h"
#include "FullTextSearch.h"
#include "TextExtractor.h"
#include <iostream>
#include <filesystem>
#include <fstream>
#include <algorithm>
#include <sstream>
#include <regex>
#include <chrono>

namespace fs = std::filesystem;

namespace forensics {

// Static member definitions
std::unordered_map<std::string, ContentCacheEntry> XapianIndexer::contentCache_;
std::mutex XapianIndexer::cacheMutex_;

// --- XapianIndexer ---

XapianIndexer::XapianIndexer(const std::string& dbPath) : dbPath_(dbPath) {
    try {
        // Create or open database for writing
        db_ = std::make_unique<Xapian::WritableDatabase>(dbPath, Xapian::DB_CREATE_OR_OPEN);
        termGenerator_.set_database(*db_);  // Required for spell correction features
        termGenerator_.set_stemmer(Xapian::Stem(stemmerLanguage_));
        // Note: FLAG_SPELLING requires set_database() to be called first
        termGenerator_.set_flags(Xapian::TermGenerator::FLAG_SPELLING);
    } catch (const Xapian::Error& e) {
        std::cerr << "Xapian Indexer Error: " << e.get_msg() << std::endl;
        throw;
    }
}

XapianIndexer::~XapianIndexer() {
    try {
        if (db_) {
            db_->commit();
        }
    } catch (const Xapian::Error& e) {
        std::cerr << "Xapian Indexer Destructor Error: " << e.get_msg() << std::endl;
    }
}

void XapianIndexer::setStemmerLanguage(const std::string& language) {
    stemmerLanguage_ = language;
    try {
        termGenerator_.set_stemmer(Xapian::Stem(language));
    } catch (const Xapian::Error& e) {
        std::cerr << "Invalid stemmer language: " << language << ", using english" << std::endl;
        stemmerLanguage_ = "english";
        termGenerator_.set_stemmer(Xapian::Stem("english"));
    }
}

size_t XapianIndexer::getDocumentCount() const {
    if (!db_) return 0;
    return db_->get_doccount();
}

void XapianIndexer::cacheContent(const std::string& path, const std::string& content) {
    std::lock_guard<std::mutex> lock(cacheMutex_);
    
    // Enforce cache size limit
    if (contentCache_.size() >= static_cast<size_t>(forensics::ConfigManager::instance().getSearchMaxCacheSize())) {
        // Simple eviction: remove oldest entry
        auto oldest = contentCache_.begin();
        int64_t oldestTime = std::numeric_limits<int64_t>::max();
        for (auto it = contentCache_.begin(); it != contentCache_.end(); ++it) {
            if (it->second.indexTime < oldestTime) {
                oldestTime = it->second.indexTime;
                oldest = it;
            }
        }
        if (oldest != contentCache_.end()) {
            contentCache_.erase(oldest);
        }
    }
    
    // Cache truncated content
    ContentCacheEntry entry;
    entry.content = content.substr(0, static_cast<size_t>(forensics::ConfigManager::instance().getSearchMaxContentLength()));
    entry.indexTime = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    
    contentCache_[path] = std::move(entry);
}

void XapianIndexer::addDocument(const std::string& filePath, const std::string& content) {
    FileMetadata metadata;
    metadata.path = filePath;
    metadata.extension = fs::path(filePath).extension().string();
    
    // Try to get file stats
    try {
        if (fs::exists(filePath)) {
            metadata.size = static_cast<int64_t>(fs::file_size(filePath));
            auto ftime = fs::last_write_time(filePath);
            auto sctp = std::chrono::time_point_cast<std::chrono::seconds>(
                ftime - decltype(ftime)::clock::now() + std::chrono::system_clock::now());
            metadata.mtime = sctp.time_since_epoch().count();
        }
    } catch (...) {
        // Ignore filesystem errors
    }
    
    addDocument(filePath, content, metadata);
}

void XapianIndexer::addDocument(const std::string& filePath, const std::string& content, const FileMetadata& metadata) {
    if (!db_) return;

    try {
        Xapian::Document doc;
        termGenerator_.set_document(doc);

        // Index specific fields with prefixes
        termGenerator_.index_text(filePath, 1, "P");  // Prefix 'P' for path
        termGenerator_.index_text(content);           // General content (no prefix)
        
        // Index extension as a boolean term for filtering
        if (!metadata.extension.empty()) {
            std::string ext = metadata.extension;
            std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
            doc.add_boolean_term("E" + ext);  // E prefix for extension
            termGenerator_.index_text(ext, 1, "E");
        }

        // Store document data as JSON for retrieval
        std::ostringstream dataStream;
        dataStream << "{\"path\":\"" << filePath << "\""
                   << ",\"size\":" << metadata.size
                   << ",\"extension\":\"" << metadata.extension << "\""
                   << ",\"mtime\":" << metadata.mtime << "}";
        doc.set_data(dataStream.str());
        
        // Store values for sorting and display
        doc.add_value(0, Xapian::sortable_serialise(static_cast<double>(metadata.size)));
        doc.add_value(1, Xapian::sortable_serialise(static_cast<double>(metadata.mtime)));
        
        // Add unique ID based on path to avoid duplicates
        std::string idterm = "Q" + filePath;
        doc.add_boolean_term(idterm);
        
        db_->replace_document(idterm, doc);
        
        // Cache content for snippet generation
        cacheContent(filePath, content);
        
    } catch (const Xapian::Error& e) {
        std::cerr << "Xapian Indexer AddDocument Error: " << e.get_msg() << std::endl;
    }
}

void XapianIndexer::commit() {
    if (db_) {
        db_->commit();
    }
}

// --- XapianSearcher ---

XapianSearcher::XapianSearcher(const std::string& dbPath) : dbPath_(dbPath) {
    try {
        db_ = std::make_unique<Xapian::Database>(dbPath);
    } catch (const Xapian::Error& e) {
        std::cerr << "Xapian Searcher Error: " << e.get_msg() << std::endl;
        db_.reset();
    }
}

XapianSearcher::~XapianSearcher() = default;

void XapianSearcher::setSnippetLength(size_t length) {
    snippetLength_ = length;
}

bool XapianSearcher::isValid() const {
    return db_ != nullptr;
}

size_t XapianSearcher::getTotalDocuments() const {
    if (!db_) return 0;
    return db_->get_doccount();
}

std::string XapianSearcher::generateSnippet(const std::string& path, const Xapian::Query& query) {
    // First, try to get content from cache
    {
        std::lock_guard<std::mutex> lock(XapianIndexer::cacheMutex_);
        auto it = XapianIndexer::contentCache_.find(path);
        if (it != XapianIndexer::contentCache_.end()) {
            const std::string& content = it->second.content;
            
            // Extract query terms for highlighting
            std::vector<std::string> terms;
            for (auto termIt = query.get_terms_begin(); termIt != query.get_terms_end(); ++termIt) {
                terms.push_back(*termIt);
            }
            
            // Find the first occurrence of any query term
            size_t firstMatch = std::string::npos;
            for (const auto& term : terms) {
                size_t pos = content.find(term);
                if (pos != std::string::npos && (firstMatch == std::string::npos || pos < firstMatch)) {
                    firstMatch = pos;
                }
            }
            
            // Extract snippet around the match
            if (firstMatch != std::string::npos) {
                size_t start = (firstMatch > snippetLength_ / 2) ? firstMatch - snippetLength_ / 2 : 0;
                size_t end = std::min(start + snippetLength_, content.length());
                
                std::string snippet = content.substr(start, end - start);
                
                // Add ellipsis if truncated
                if (start > 0) snippet = "..." + snippet;
                if (end < content.length()) snippet += "...";
                
                return highlightTerms(snippet, terms);
            }
            
            // No match found, return beginning of content
            std::string snippet = content.substr(0, snippetLength_);
            if (content.length() > snippetLength_) snippet += "...";
            return snippet;
        }
    }
    
    // Try to read from file if not in cache
    try {
        if (fs::exists(path)) {
            std::string content = TextExtractor::extract(path);
            if (!content.empty()) {
                std::string snippet = content.substr(0, snippetLength_);
                if (content.length() > snippetLength_) snippet += "...";
                return snippet;
            }
        }
    } catch (...) {
        // Ignore file access errors
    }
    
    return "(File content not available for snippet)";
}

std::string XapianSearcher::highlightTerms(const std::string& text, const std::vector<std::string>& terms) {
    std::string result = text;
    
    for (const auto& term : terms) {
        if (term.empty()) continue;
        
        // Case-insensitive search and highlight with **term**
        std::string lowerResult = result;
        std::transform(lowerResult.begin(), lowerResult.end(), lowerResult.begin(), ::tolower);
        
        std::string lowerTerm = term;
        std::transform(lowerTerm.begin(), lowerTerm.end(), lowerTerm.begin(), ::tolower);
        
        size_t pos = 0;
        while ((pos = lowerResult.find(lowerTerm, pos)) != std::string::npos) {
            // Get the original case version
            std::string original = result.substr(pos, term.length());
            std::string highlighted = "**" + original + "**";
            
            result.replace(pos, term.length(), highlighted);
            lowerResult.replace(pos, term.length(), highlighted);
            
            pos += highlighted.length();
        }
    }
    
    return result;
}

std::vector<SearchResult> XapianSearcher::search(const std::string& queryStr, size_t limit, size_t offset) {
    std::vector<SearchResult> results;
    if (!db_) return results;

    try {
        Xapian::Enquire enquire(*db_);
        Xapian::QueryParser parser;
        Xapian::Stem stemmer("english");
        parser.set_stemmer(stemmer);
        parser.set_database(*db_);
        parser.set_stemming_strategy(Xapian::QueryParser::STEM_SOME);
        
        // Enable prefix matching
        parser.add_prefix("path", "P");
        parser.add_prefix("ext", "E");

        Xapian::Query query = parser.parse_query(queryStr, 
            Xapian::QueryParser::FLAG_DEFAULT | 
            Xapian::QueryParser::FLAG_WILDCARD |
            Xapian::QueryParser::FLAG_PHRASE |
            Xapian::QueryParser::FLAG_BOOLEAN);

        std::cout << "Parsed Query: " << query.get_description() << std::endl;

        enquire.set_query(query);

        Xapian::MSet mset = enquire.get_mset(offset, limit);

        for (Xapian::MSetIterator i = mset.begin(); i != mset.end(); ++i) {
            SearchResult res;
            
            // Parse stored data (JSON format)
            std::string data = i.get_document().get_data();
            
            // Simple JSON parsing for path
            size_t pathStart = data.find("\"path\":\"");
            if (pathStart != std::string::npos) {
                pathStart += 8;
                size_t pathEnd = data.find("\"", pathStart);
                if (pathEnd != std::string::npos) {
                    res.path = data.substr(pathStart, pathEnd - pathStart);
                }
            }
            
            // Parse size
            size_t sizeStart = data.find("\"size\":");
            if (sizeStart != std::string::npos) {
                sizeStart += 7;
                size_t sizeEnd = data.find_first_of(",}", sizeStart);
                if (sizeEnd != std::string::npos) {
                    try {
                        res.fileSize = std::stoll(data.substr(sizeStart, sizeEnd - sizeStart));
                    } catch (...) {}
                }
            }
            
            // Parse extension
            size_t extStart = data.find("\"extension\":\"");
            if (extStart != std::string::npos) {
                extStart += 13;
                size_t extEnd = data.find("\"", extStart);
                if (extEnd != std::string::npos) {
                    res.extension = data.substr(extStart, extEnd - extStart);
                }
            }
            
            // Fallback for old data format
            if (res.path.empty()) {
                res.path = data;
            }
            
            res.score = i.get_percent();
            
            // Generate snippet
            res.snippet = generateSnippet(res.path, query);
            
            results.push_back(res);
        }
    } catch (const Xapian::Error& e) {
        std::cerr << "Xapian Searcher Search Error: " << e.get_msg() << std::endl;
    }

    return results;
}

}
