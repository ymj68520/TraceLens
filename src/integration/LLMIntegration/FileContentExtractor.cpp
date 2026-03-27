#include "FileContentExtractor.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <algorithm>

namespace fs = std::filesystem;

namespace forensics {
namespace llm {

std::string FileContentExtractor::readFileContent(const std::string& path, size_t maxBytes) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        return "";
    }

    std::ostringstream content;
    if (maxBytes > 0) {
        std::vector<char> buffer(maxBytes);
        file.read(buffer.data(), maxBytes);
        content.write(buffer.data(), file.gcount());
    } else {
        content << file.rdbuf();
    }

    return content.str();
}

std::string FileContentExtractor::detectFileType(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);

    // Check extension map first
    const auto& typeMap = getTypeMap();
    auto it = typeMap.find(ext);
    if (it != typeMap.end()) {
        return it->second;
    }

    // Check if binary
    if (isBinaryFile(path)) {
        return "Binary";
    }

    return ext.empty() ? "Unknown" : ext.substr(1) + " File";
}

const std::map<std::string, std::string>& FileContentExtractor::getTypeMap() {
    static const std::map<std::string, std::string> typeMap = {
        // Text files
        {".txt", "Text"},
        {".md", "Markdown"},
        {".json", "JSON"},
        {".xml", "XML"},
        {".html", "HTML"},
        {".htm", "HTML"},
        {".css", "CSS"},
        {".rtf", "Rich Text"},

        // Programming languages
        {".js", "JavaScript"},
        {".jsx", "JavaScript React"},
        {".ts", "TypeScript"},
        {".tsx", "TypeScript React"},
        {".py", "Python"},
        {".cpp", "C++"},
        {".c", "C"},
        {".h", "C/C++ Header"},
        {".hpp", "C++ Header"},
        {".java", "Java"},
        {".rs", "Rust"},
        {".go", "Go"},
        {".rb", "Ruby"},
        {".php", "PHP"},
        {".cs", "C#"},
        {".swift", "Swift"},
        {".kt", "Kotlin"},
        {".scala", "Scala"},
        {".r", "R"},
        {".lua", "Lua"},
        {".pl", "Perl"},

        // Shell and scripts
        {".sh", "Shell Script"},
        {".bash", "Bash Script"},
        {".zsh", "Zsh Script"},
        {".bat", "Batch Script"},
        {".cmd", "Command Script"},
        {".ps1", "PowerShell"},

        // Data formats
        {".sql", "SQL"},
        {".log", "Log File"},
        {".csv", "CSV"},
        {".tsv", "TSV"},
        {".yaml", "YAML"},
        {".yml", "YAML"},
        {".toml", "TOML"},
        {".ini", "INI Config"},
        {".conf", "Config"},
        {".cfg", "Config"},
        {".properties", "Properties"},

        // Documents
        {".pdf", "PDF"},
        {".doc", "Word Document"},
        {".docx", "Word Document"},
        {".xls", "Excel"},
        {".xlsx", "Excel"},
        {".ppt", "PowerPoint"},
        {".pptx", "PowerPoint"},
        {".odt", "OpenDocument Text"},
        {".ods", "OpenDocument Spreadsheet"},
        {".odp", "OpenDocument Presentation"},
        {".odg", "OpenDocument Graphics"},

        // E-Books
        {".epub", "E-Book"},
        {".mobi", "Kindle E-Book"},
        {".azw", "Kindle E-Book"},
        {".azw3", "Kindle E-Book"},

        // Images
        {".jpg", "JPEG Image"},
        {".jpeg", "JPEG Image"},
        {".png", "PNG Image"},
        {".gif", "GIF Image"},
        {".bmp", "Bitmap Image"},
        {".svg", "SVG Image"},
        {".webp", "WebP Image"},
        {".ico", "Icon"},
        {".tiff", "TIFF Image"},
        {".tif", "TIFF Image"},
        {".psd", "Photoshop"},
        {".ai", "Illustrator"},
        {".raw", "RAW Image"},

        // Video
        {".mp4", "MP4 Video"},
        {".mkv", "MKV Video"},
        {".avi", "AVI Video"},
        {".mov", "QuickTime Video"},
        {".wmv", "WMV Video"},
        {".flv", "Flash Video"},
        {".webm", "WebM Video"},
        {".m4v", "M4V Video"},
        {".mpeg", "MPEG Video"},
        {".mpg", "MPEG Video"},

        // Audio
        {".mp3", "MP3 Audio"},
        {".wav", "WAV Audio"},
        {".flac", "FLAC Audio"},
        {".ogg", "OGG Audio"},
        {".aac", "AAC Audio"},
        {".wma", "WMA Audio"},
        {".m4a", "M4A Audio"},
        {".aiff", "AIFF Audio"},
        {".opus", "Opus Audio"},

        // Archives
        {".zip", "ZIP Archive"},
        {".rar", "RAR Archive"},
        {".7z", "7-Zip Archive"},
        {".tar", "TAR Archive"},
        {".gz", "GZip Archive"},
        {".bz2", "BZip2 Archive"},
        {".xz", "XZ Archive"},
        {".lz", "LZ Archive"},
        {".lzma", "LZMA Archive"},

        // Executables and libraries
        {".exe", "Windows Executable"},
        {".dll", "Windows Library"},
        {".so", "Linux Library"},
        {".dylib", "macOS Library"},
        {".app", "macOS Application"},
        {".apk", "Android Package"},
        {".deb", "Debian Package"},
        {".rpm", "RPM Package"},

        // Database
        {".db", "Database"},
        {".sqlite", "SQLite Database"},
        {".sqlite3", "SQLite Database"},
        {".mdb", "Access Database"},
        {".accdb", "Access Database"},

        // Certificates and keys
        {".pem", "PEM Certificate"},
        {".crt", "Certificate"},
        {".cer", "Certificate"},
        {".key", "Private Key"},
        {".p12", "PKCS12 Certificate"},
        {".pfx", "PFX Certificate"},
    };

    return typeMap;
}

bool FileContentExtractor::isBinaryFile(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        return false;
    }

    char buffer[512];
    file.read(buffer, sizeof(buffer));
    size_t count = file.gcount();

    // Check for null bytes (binary indicator)
    for (size_t i = 0; i < count; ++i) {
        if (buffer[i] == '\0') {
            return true;
        }
    }

    return false;
}

} // namespace llm
} // namespace forensics
