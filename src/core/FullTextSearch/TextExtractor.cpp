#include "TextExtractor.h"
#include <fstream>
#include <filesystem>
#include <algorithm>
#include <cctype>
#include <iostream>
#include <chrono>

namespace fs = std::filesystem;

namespace forensics {

// Extended set of text file extensions
const std::set<std::string> TextExtractor::textExtensions = {
    // Plain text
    ".txt", ".text", ".log", ".csv", ".tsv",
    
    // Configuration files
    ".ini", ".conf", ".cfg", ".config", ".properties",
    ".yaml", ".yml", ".toml", ".env",
    
    // Web technologies
    ".json", ".xml", ".html", ".htm", ".xhtml",
    ".css", ".scss", ".sass", ".less",
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    
    // Programming languages
    ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hxx",
    ".py", ".pyw", ".pyi",
    ".java", ".kt", ".kts", ".scala", ".groovy",
    ".rb", ".rake", ".gemspec",
    ".php", ".phtml",
    ".rs", ".go", ".swift", ".m", ".mm",
    ".cs", ".fs", ".vb",
    ".lua", ".tcl", ".pl", ".pm", ".perl",
    ".r", ".R", ".rmd", ".Rmd",
    ".jl",  // Julia
    ".ex", ".exs",  // Elixir
    ".erl", ".hrl",  // Erlang
    ".clj", ".cljs", ".cljc",  // Clojure
    ".hs", ".lhs",  // Haskell
    ".ml", ".mli",  // OCaml
    
    // Shell scripts
    ".sh", ".bash", ".zsh", ".fish", ".csh", ".ksh",
    ".bat", ".cmd", ".ps1", ".psm1",
    
    // Documentation and text formats
    ".md", ".markdown", ".rst", ".asciidoc", ".adoc",
    ".tex", ".latex", ".bib",
    ".org",  // Emacs org-mode
    
    // Data and query languages
    ".sql", ".mysql", ".pgsql",
    ".graphql", ".gql",
    
    // Build and DevOps
    ".dockerfile", ".containerfile",
    ".cmake", ".make", ".mk",
    ".gradle", ".maven",
    ".tf", ".tfvars",  // Terraform
    ".rego",  // Open Policy Agent
    
    // Misc
    ".diff", ".patch",
    ".svg",  // SVG is XML
    ".plist",  // Apple property list (XML)
    ".manifest",
    ".gitignore", ".gitattributes", ".gitmodules",
    ".editorconfig", ".prettierrc", ".eslintrc"
};

std::string TextExtractor::extract(const std::string& path) {
    return extract(path, 0);  // 0 means no limit
}

std::string TextExtractor::extract(const std::string& path, size_t maxBytes) {
    if (!fs::exists(path)) {
        return "";
    }

    try {
        std::string ext = fs::path(path).extension().string();
        // Convert to lowercase for comparison
        std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c){ return std::tolower(c); });

        if (isTextFile(ext)) {
            return extractFromTextFile(path, maxBytes);
        } else {
            // Fallback to strings extraction for binary or unknown files
            return extractStrings(path, 4, maxBytes);
        }
    } catch (const std::exception& e) {
        std::cerr << "TextExtractor::extract error for " << path << ": " << e.what() << std::endl;
        return "";
    }
}

bool TextExtractor::isTextFile(const std::string& extension) {
    std::string ext = extension;
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c){ return std::tolower(c); });
    return textExtensions.find(ext) != textExtensions.end();
}

const std::set<std::string>& TextExtractor::getSupportedExtensions() {
    return textExtensions;
}

ExtractedMetadata TextExtractor::extractMetadata(const std::string& path) {
    ExtractedMetadata meta;
    meta.path = path;
    
    try {
        fs::path p(path);
        meta.filename = p.filename().string();
        meta.extension = p.extension().string();
        std::transform(meta.extension.begin(), meta.extension.end(), 
                       meta.extension.begin(), ::tolower);
        
        meta.isText = isTextFile(meta.extension);
        
        if (fs::exists(path)) {
            // Get file size
            meta.size = static_cast<int64_t>(fs::file_size(path));
            
            // Get modification time
            auto ftime = fs::last_write_time(path);
            // Convert to system_clock time_point
            auto sctp = std::chrono::time_point_cast<std::chrono::seconds>(
                ftime - decltype(ftime)::clock::now() + std::chrono::system_clock::now());
            meta.mtime = sctp.time_since_epoch().count();
            
            // Note: C++17 filesystem doesn't provide creation time directly
            // Using mtime as ctime for compatibility
            meta.ctime = meta.mtime;
        }
    } catch (const std::exception& e) {
        std::cerr << "TextExtractor::extractMetadata error for " << path << ": " << e.what() << std::endl;
    }
    
    return meta;
}

std::string TextExtractor::extractFromTextFile(const std::string& path, size_t maxBytes) {
    std::ifstream file(path);
    if (!file.is_open()) return "";

    if (maxBytes == 0) {
        // Read entire file
        return std::string((std::istreambuf_iterator<char>(file)),
                            std::istreambuf_iterator<char>());
    } else {
        // Read up to maxBytes
        std::string result;
        result.resize(maxBytes);
        file.read(&result[0], maxBytes);
        result.resize(file.gcount());
        return result;
    }
}

std::string TextExtractor::extractStrings(const std::string& path, size_t minLength, size_t maxBytes) {
    std::ifstream file(path, std::ios::binary);
    if (!file.is_open()) return "";

    std::string result;
    std::string currentSequence;
    char c;
    
    // Use provided limit or default 10MB
    size_t effectiveLimit = (maxBytes > 0) ? maxBytes : (10 * 1024 * 1024);

    // Basic 'strings' implementation:
    // Collect printable characters. If sequence len >= minLength, append to result.
    while (file.get(c)) {
        if (std::isprint(static_cast<unsigned char>(c)) || c == '\n' || c == '\t') {
            currentSequence += c;
        } else {
            if (currentSequence.length() >= minLength) {
                result += currentSequence + "\n";
            }
            currentSequence.clear();
        }
        
        // Safety limit
        if (result.length() >= effectiveLimit) {
            result += "\n[Truncated - Size limit reached]\n";
            break;
        }
    }

    if (currentSequence.length() >= minLength) {
        result += currentSequence + "\n";
    }

    return result;
}

}
