#include "TOONExporter.h"
#include <sstream>
#include <algorithm>
#include <regex>

namespace forensics {

// ============================================================================
// Static Helper Functions
// ============================================================================

std::vector<std::string> TOONExporter::getAllFieldNames() {
    return {
        "inode", "name", "path", "size", "extension", "category", "type",
        "mtime", "ctime", "is_deleted", "md5",
        "llm_summary", "llm_description", "llm_keywords", 
        "llm_analyzed_at", "llm_model_used"
    };
}

std::string TOONExporter::escapeValue(const std::string& value) {
    if (value.empty()) {
        return "\"\"";
    }
    
    // Check if value needs quoting (contains delimiter, quotes, or newlines)
    bool needsQuoting = false;
    for (char c : value) {
        if (c == '|' || c == '"' || c == '\n' || c == '\r' || c == ',') {
            needsQuoting = true;
            break;
        }
    }
    
    if (!needsQuoting) {
        // Check for leading/trailing whitespace
        if (!value.empty() && (std::isspace(value.front()) || std::isspace(value.back()))) {
            needsQuoting = true;
        }
    }
    
    if (!needsQuoting) {
        return value;
    }
    
    // Escape internal quotes by doubling them
    std::string escaped;
    escaped.reserve(value.size() + 10);
    escaped += '"';
    
    for (char c : value) {
        if (c == '"') {
            escaped += "\"\"";
        } else if (c == '\n') {
            escaped += "\\n";
        } else if (c == '\r') {
            escaped += "\\r";
        } else {
            escaped += c;
        }
    }
    
    escaped += '"';
    return escaped;
}

// ============================================================================
// Query Files from Database
// ============================================================================

std::vector<FileRecordWithLLM> TOONExporter::queryFiles(sqlite3* db, 
                                                         const std::string& whereClause) {
    std::vector<FileRecordWithLLM> records;
    
    if (!db) {
        return records;
    }
    
    std::string sql = R"(
        SELECT inode, name, path, size, extension, category, type,
               mtime, ctime, is_deleted, md5,
               llm_summary, llm_description, llm_keywords, 
               llm_analyzed_at, llm_model_used
        FROM files
    )";
    
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }
    
    sql += " ORDER BY path";
    
    sqlite3_stmt* stmt = nullptr;
    int rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
    
    if (rc != SQLITE_OK) {
        return records;
    }
    
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecordWithLLM record;
        
        record.inode = sqlite3_column_int64(stmt, 0);
        
        const char* text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.name = text ? text : "";
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.path = text ? text : "";
        
        record.size = sqlite3_column_int64(stmt, 3);
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        record.extension = text ? text : "";
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        record.category = text ? text : "";
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        record.type = text ? text : "";
        
        record.mtime = sqlite3_column_int64(stmt, 7);
        record.ctime = sqlite3_column_int64(stmt, 8);
        record.isDeleted = sqlite3_column_int(stmt, 9);
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
        record.md5 = text ? text : "";
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        record.llm_summary = text ? text : "";
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
        record.llm_description = text ? text : "";
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 13));
        record.llm_keywords = text ? text : "";
        
        record.llm_analyzed_at = sqlite3_column_int64(stmt, 14);
        
        text = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 15));
        record.llm_model_used = text ? text : "";
        
        records.push_back(std::move(record));
    }
    
    sqlite3_finalize(stmt);
    return records;
}

// ============================================================================
// Get Field Value
// ============================================================================

std::string TOONExporter::getFieldValue(const FileRecordWithLLM& record,
                                         const std::string& fieldName) const {
    if (fieldName == "inode") {
        return std::to_string(record.inode);
    } else if (fieldName == "name") {
        return record.name;
    } else if (fieldName == "path") {
        return record.path;
    } else if (fieldName == "size") {
        return std::to_string(record.size);
    } else if (fieldName == "extension") {
        return record.extension;
    } else if (fieldName == "category") {
        return record.category;
    } else if (fieldName == "type") {
        return record.type;
    } else if (fieldName == "mtime") {
        return std::to_string(record.mtime);
    } else if (fieldName == "ctime") {
        return std::to_string(record.ctime);
    } else if (fieldName == "is_deleted") {
        return std::to_string(record.isDeleted);
    } else if (fieldName == "md5") {
        return record.md5;
    } else if (fieldName == "llm_summary") {
        return record.llm_summary;
    } else if (fieldName == "llm_description") {
        return record.llm_description;
    } else if (fieldName == "llm_keywords") {
        return record.llm_keywords;
    } else if (fieldName == "llm_analyzed_at") {
        return std::to_string(record.llm_analyzed_at);
    } else if (fieldName == "llm_model_used") {
        return record.llm_model_used;
    }
    return "";
}

// ============================================================================
// Format Single Record
// ============================================================================

std::string TOONExporter::formatRecord(const FileRecordWithLLM& record,
                                        const std::vector<std::string>& fields,
                                        const std::string& delimiter) const {
    std::ostringstream oss;
    bool first = true;
    
    for (const auto& field : fields) {
        if (!first) {
            oss << delimiter;
        }
        first = false;
        
        std::string value = getFieldValue(record, field);
        oss << escapeValue(value);
    }
    
    return oss.str();
}

// ============================================================================
// Export to TOON (from database)
// ============================================================================

std::string TOONExporter::exportToTOON(sqlite3* db, const TOONExportConfig& config) {
    std::vector<FileRecordWithLLM> records = queryFiles(db, config.whereClause);
    return exportToTOON(records, config);
}

// ============================================================================
// Export to TOON (from records)
// ============================================================================

std::string TOONExporter::exportToTOON(const std::vector<FileRecordWithLLM>& records,
                                        const TOONExportConfig& config) {
    std::ostringstream oss;
    
    // Determine fields to export
    std::vector<std::string> fields = config.fields;
    if (fields.empty()) {
        // Default: export commonly useful fields for LLM
        fields = {"name", "path", "size", "category", 
                  "llm_summary", "llm_description", "llm_keywords"};
    }
    
    const std::string& delimiter = config.delimiter;
    
    // Write schema header
    if (config.includeSchema) {
        oss << "TOON.schema: ";
        bool first = true;
        for (const auto& field : fields) {
            if (!first) {
                oss << delimiter;
            }
            first = false;
            oss << field;
        }
        oss << "\n";
    }
    
    // Write record count (helps LLM understand data size)
    oss << "# records[" << records.size() << "]\n";
    
    // Write data rows
    for (const auto& record : records) {
        oss << formatRecord(record, fields, delimiter) << "\n";
    }
    
    return oss.str();
}

} // namespace forensics
