#pragma once
#ifndef TOON_EXPORTER_H
#define TOON_EXPORTER_H

#include <string>
#include <vector>
#include <cstdint>
#include <sqlite3.h>

namespace forensics {

/**
 * @brief Configuration for TOON export
 */
struct TOONExportConfig {
    std::string delimiter = " | ";      // Delimiter between fields
    bool includeSchema = true;          // Include TOON.schema header line
    bool quoteStrings = true;           // Quote string values
    std::vector<std::string> fields;    // Fields to export (empty = all)
    std::string whereClause;            // Optional WHERE filter
};

/**
 * @brief File record with LLM analysis data
 */
struct FileRecordWithLLM {
    // Core file metadata
    int64_t inode = 0;
    std::string name;
    std::string path;
    int64_t size = 0;
    std::string extension;
    std::string category;
    std::string type;
    int64_t mtime = 0;
    int64_t ctime = 0;
    int isDeleted = 0;
    std::string md5;
    
    // LLM analysis fields
    std::string llm_summary;
    std::string llm_description;
    std::string llm_keywords;
    int64_t llm_analyzed_at = 0;
    std::string llm_model_used;
};

/**
 * @brief TOON (Token-Oriented Object Notation) Exporter
 * 
 * Converts file database records (including LLM-generated descriptions)
 * to TOON format for efficient LLM prompt integration.
 * 
 * TOON format features:
 * - 30-60% token reduction compared to JSON
 * - Tabular schema declaration: TOON.schema: field1 | field2 | field3
 * - Data rows with pipe delimiter
 * - Lossless JSON conversion capability
 */
class TOONExporter {
public:
    TOONExporter() = default;
    ~TOONExporter() = default;
    
    /**
     * @brief Export files from database to TOON format
     * @param db SQLite database handle
     * @param config Export configuration
     * @return TOON formatted string
     */
    std::string exportToTOON(sqlite3* db, const TOONExportConfig& config = {});
    
    /**
     * @brief Export records to TOON format
     * @param records Vector of file records with LLM data
     * @param config Export configuration
     * @return TOON formatted string
     */
    std::string exportToTOON(const std::vector<FileRecordWithLLM>& records,
                              const TOONExportConfig& config = {});
    
    /**
     * @brief Query files from database with LLM columns
     * @param db SQLite database handle
     * @param whereClause Optional WHERE clause filter
     * @return Vector of file records with LLM data
     */
    static std::vector<FileRecordWithLLM> queryFiles(sqlite3* db, 
                                                      const std::string& whereClause = "");
    
    /**
     * @brief Escape special characters in value for TOON format
     * @param value Value to escape
     * @return Escaped value with quotes if needed
     */
    static std::string escapeValue(const std::string& value);
    
    /**
     * @brief Get all available field names
     * @return Vector of field names
     */
    static std::vector<std::string> getAllFieldNames();

private:
    /**
     * @brief Format a single record as TOON row
     */
    std::string formatRecord(const FileRecordWithLLM& record,
                             const std::vector<std::string>& fields,
                             const std::string& delimiter) const;
    
    /**
     * @brief Get field value from record by name
     */
    std::string getFieldValue(const FileRecordWithLLM& record,
                              const std::string& fieldName) const;
};

} // namespace forensics

#endif // TOON_EXPORTER_H
