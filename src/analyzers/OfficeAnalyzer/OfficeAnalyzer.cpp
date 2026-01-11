#include "OfficeAnalyzer.h"
#include <duckx.hpp>
#include <iostream>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <array>
#include <memory>
#include <stdexcept>

OfficeAnalyzer::OfficeAnalyzer() {}

OfficeAnalyzer::~OfficeAnalyzer() {}

std::string OfficeAnalyzer::analyze(const std::string& filePath) {
    if (hasExtension(filePath, ".docx")) {
        return analyzeDocx(filePath);
    } else if (hasExtension(filePath, ".doc")) {
        return analyzeDoc(filePath);
    } else {
        return "Error: Unsupported file format. Only .docx and .doc are supported.";
    }
}

std::string OfficeAnalyzer::analyzeDocx(const std::string& filePath) {
    try {
        duckx::Document doc(filePath);
        doc.open();

        std::stringstream ss;
        
        for (auto p : doc.paragraphs()) {
            for (auto r : p.runs()) {
                ss << r.get_text();
            }
            ss << "\n\n"; // New paragraph in Markdown
        }
        
        return ss.str();
    } catch (const std::exception& e) {
        return std::string("Error parsing DOCX: ") + e.what();
    }
}

std::string OfficeAnalyzer::analyzeDoc(const std::string& filePath) {
    // Escape the file path to avoid command injection in simple cases, 
    // although for rigorous security we should avoid system() calls with user input.
    // Here we assume basic sanitation or trusted input for this tool.
    // A simple quote wrapping
    std::string safePath = "'" + filePath + "'"; 
    
    // Using antiword to convert doc to text
    // -f: formatted output (we might want plain text or try to deduce formatting)
    // antiword default output is layout-preserved text.
    std::string command = "antiword " + safePath;
    
    try {
        std::string output = execCommand(command);
        if (output.empty()) {
            return "Warning: No content extracted from DOC file or antiword failed.";
        }
        // Wrap in a block or just return text? 
        // Returning text is usually better for markdown conversion unless it's preformatted code.
        // Antiword output is often preformatted-ish (tables drawn with characters).
        // Let's wrap it in a pre block if it looks like a table, but for now just raw text.
        return output;
    } catch (const std::exception& e) {
        return std::string("Error parsing DOC using antiword: ") + e.what();
    }
}

bool OfficeAnalyzer::hasExtension(const std::string& filePath, const std::string& ext) {
    if (filePath.length() < ext.length()) return false;
    std::string fileExt = filePath.substr(filePath.length() - ext.length());
    // Case insensitive comparison
    return std::equal(ext.begin(), ext.end(), fileExt.begin(),
                      [](char a, char b) { return tolower(a) == tolower(b); });
}

std::string OfficeAnalyzer::execCommand(const std::string& cmd) {
    std::array<char, 128> buffer;
    std::string result;
    std::unique_ptr<FILE, decltype(&pclose)> pipe(popen(cmd.c_str(), "r"), pclose);
    if (!pipe) {
        throw std::runtime_error("popen() failed!");
    }
    while (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
        result += buffer.data();
    }
    return result;
}
