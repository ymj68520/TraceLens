#include "PDFAnalyzer.h"
#include <poppler-document.h>
#include <poppler-page.h>
#include <iostream>
#include <fstream>
#include <stdexcept>
#include <algorithm>
#include <sstream>
#include <filesystem>
#include <ctime>
#include <iomanip>

namespace forensics {
namespace analyzers {

std::string PDFAnalyzer::extractText(const std::string& pdfPath) {
    if (pdfPath.empty()) {
        return "";
    }

    try {
        std::unique_ptr<poppler::document> doc(poppler::document::load_from_file(pdfPath));
        if (!doc) {
            std::cerr << "Failed to load PDF document: " << pdfPath << std::endl;
            return "";
        }

        if (doc->is_locked()) {
            std::cerr << "PDF document is locked: " << pdfPath << std::endl;
            return "[Encrypted PDF - Content Locked]";
        }

        std::stringstream ss;
        int pages = doc->pages();
        
        for (int i = 0; i < pages; ++i) {
            std::unique_ptr<poppler::page> p(doc->create_page(i));
            if (p) {
                poppler::ustring ustr = p->text();
                // to_utf8() returns std::vector<char>, convert to std::string
                auto bytes = ustr.to_utf8();
                std::string pageText(bytes.begin(), bytes.end());
                
                if (!pageText.empty()) {
                    ss << "--- Page " << (i + 1) << " ---\n";
                    ss << cleanText(pageText) << "\n\n";
                }
            }
        }
        
        return ss.str();
    } catch (const std::exception& e) {
        std::cerr << "Error extracting text from PDF " << pdfPath << ": " << e.what() << std::endl;
        return "";
    }
}

PDFMetadata PDFAnalyzer::extractMetadata(const std::string& pdfPath) {
    PDFMetadata meta;
    
    if (pdfPath.empty()) {
        return meta;
    }

    try {
        std::unique_ptr<poppler::document> doc(poppler::document::load_from_file(pdfPath));
        if (!doc) {
            return meta;
        }

        meta.isEncrypted = doc->is_encrypted();
        meta.pageCount = doc->pages();
        
        // Helper to convert byte_array to string
        auto to_string = [](const std::vector<char>& bytes) -> std::string {
            if (bytes.empty()) return "";
            return std::string(bytes.begin(), bytes.end());
        };

        meta.title = to_string(doc->info_key("Title").to_utf8());
        meta.author = to_string(doc->info_key("Author").to_utf8());
        meta.subject = to_string(doc->info_key("Subject").to_utf8());
        meta.keywords = to_string(doc->info_key("Keywords").to_utf8());
        meta.creator = to_string(doc->info_key("Creator").to_utf8());
        meta.producer = to_string(doc->info_key("Producer").to_utf8());
        
        // Time metadata in PDFs is usually stored as a string like "D:YYYYMMDDHHmmSSOHH'mm'"
        // Parsing this strictly would require complex regex, for now we leave the timestamps as 0
        // unless we want to parse the ModDate and CreationDate keys.
        
        if (doc->is_locked()) {
            meta.permissions.push_back("Read Locked");
        }
        
    } catch (const std::exception& e) {
        std::cerr << "Error extracting metadata from PDF " << pdfPath << ": " << e.what() << std::endl;
    }
    
    return meta;
}

std::string PDFAnalyzer::cleanText(const std::string& text) {
    if (text.empty()) return "";

    std::string cleaned;
    cleaned.reserve(text.length());
    
    // Track newlines to preserve paragraphs
    int newlineCount = 0;
    bool lastWasSpace = false;
    
    for (char c : text) {
        if (c == '\n') {
            newlineCount++;
            lastWasSpace = false;
        } else if (std::isspace(static_cast<unsigned char>(c))) {
            // Horizontal whitespace
            if (!lastWasSpace && newlineCount == 0) {
                cleaned += ' ';
                lastWasSpace = true;
            }
        } else if (std::isprint(static_cast<unsigned char>(c)) || (static_cast<unsigned char>(c) & 0x80)) {
            // Content character
            
            // Handle pending newlines before adding content
            if (newlineCount > 0) {
                if (newlineCount >= 2) {
                    // Paragraph break (2+ newlines) -> 2 newlines
                    // But ensure we don't have trailing spaces before it
                    size_t lastNonSpace = cleaned.find_last_not_of(' ');
                    if (lastNonSpace != std::string::npos) {
                        cleaned.erase(lastNonSpace + 1);
                    }
                    cleaned += "\n\n";
                } else {
                    // Single newline -> 1 newline
                    size_t lastNonSpace = cleaned.find_last_not_of(' ');
                    if (lastNonSpace != std::string::npos) {
                        cleaned.erase(lastNonSpace + 1);
                    }
                    cleaned += '\n';
                }
                newlineCount = 0;
                lastWasSpace = false; 
            }
            
            cleaned += c;
            lastWasSpace = false;
        }
    }
    
    // Final trim
    size_t first = cleaned.find_first_not_of(" \n\r\t");
    if (std::string::npos == first) {
        return "";
    }
    size_t last = cleaned.find_last_not_of(" \n\r\t");
    return cleaned.substr(first, (last - first + 1));
}

bool PDFAnalyzer::createLLMReport(const std::string& pdfPath, const std::string& outputPath) {
    if (!std::filesystem::exists(pdfPath)) {
        return false;
    }

    try {
        PDFMetadata meta = extractMetadata(pdfPath);
        
        std::ofstream out(outputPath);
        if (!out.is_open()) {
            std::cerr << "Failed to open output file: " << outputPath << std::endl;
            return false;
        }

        // Get current time
        auto now = std::chrono::system_clock::now();
        std::time_t now_c = std::chrono::system_clock::to_time_t(now);
        
        out << "# PDF Analysis Report\n\n";
        out << "**File**: " << std::filesystem::path(pdfPath).filename().string() << "\n";
        out << "**Generated**: " << std::put_time(std::localtime(&now_c), "%Y-%m-%d %H:%M:%S") << "\n\n";
        
        out << "## Metadata\n\n";
        out << "| Field | Value |\n";
        out << "|---|---|\n";
        out << "| Title | " << (meta.title.empty() ? "-" : meta.title) << " |\n";
        out << "| Author | " << (meta.author.empty() ? "-" : meta.author) << " |\n";
        out << "| Subject | " << (meta.subject.empty() ? "-" : meta.subject) << " |\n";
        out << "| Keywords | " << (meta.keywords.empty() ? "-" : meta.keywords) << " |\n";
        out << "| Pages | " << meta.pageCount << " |\n";
        out << "| Encrypted | " << (meta.isEncrypted ? "Yes" : "No") << " |\n\n";
        
        out << "## Content\n\n";
        
        // Extract text page by page directly here to control formatting
        std::unique_ptr<poppler::document> doc(poppler::document::load_from_file(pdfPath));
        if (doc && !doc->is_locked()) {
            int pages = doc->pages();
            for (int i = 0; i < pages; ++i) {
                std::unique_ptr<poppler::page> p(doc->create_page(i));
                if (p) {
                    auto bytes = p->text().to_utf8();
                    std::string pageText(bytes.begin(), bytes.end());
                    
                    std::string cleaned = cleanText(pageText);
                    if (!cleaned.empty()) {
                        out << "### Page " << (i + 1) << "\n\n";
                        out << cleaned << "\n\n";
                        
                        // Add separator
                        if (i < pages - 1) {
                            out << "---\n\n";
                        }
                    }
                }
            }
        } else {
             out << "*Content could not be extracted (File might be locked or unreadable).*\n";
        }
        
        out.close();
        return true;
        
    } catch (const std::exception& e) {
        std::cerr << "Error creating LLM report: " << e.what() << std::endl;
        return false;
    }
}

} // namespace analyzers
} // namespace forensics
