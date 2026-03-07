#include "OfficeAnalyzer.h"
#include <duckx.hpp>
#include <iostream>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <array>
#include <memory>
#include <stdexcept>
#include <curl/curl.h>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

// Callback for libcurl to write response data
static size_t WriteCallback(void* contents, size_t size, size_t nmemb, std::string* userp) {
    userp->append((char*)contents, size * nmemb);
    return size * nmemb;
}

OfficeAnalyzer::OfficeAnalyzer() : pythonServiceUrl_("http://localhost:8090") {}

OfficeAnalyzer::~OfficeAnalyzer() {}

void OfficeAnalyzer::setPythonServiceUrl(const std::string& url) {
    pythonServiceUrl_ = url;
}

std::string OfficeAnalyzer::analyze(const std::string& filePath) {
    if (hasExtension(filePath, ".docx")) {
        return analyzeDocx(filePath);
    } else if (hasExtension(filePath, ".doc")) {
        return analyzeDoc(filePath);
    } else if (hasExtension(filePath, ".xlsx")) {
        return analyzeXlsx(filePath);
    } else if (hasExtension(filePath, ".xls")) {
        return analyzeXls(filePath);
    } else if (hasExtension(filePath, ".pptx")) {
        return analyzePptx(filePath);
    } else if (hasExtension(filePath, ".ppt")) {
        return analyzePpt(filePath);
    } else {
        return "Error: Unsupported file format. Supported formats: .docx, .doc, .xlsx, .xls, .pptx, .ppt";
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
    std::string safePath = "'" + filePath + "'"; 
    std::string command = "antiword " + safePath;
    
    try {
        std::string output = execCommand(command);
        if (output.empty()) {
            return "Warning: No content extracted from DOC file or antiword failed.";
        }
        return output;
    } catch (const std::exception& e) {
        return std::string("Error parsing DOC using antiword: ") + e.what();
    }
}

std::string OfficeAnalyzer::analyzeXlsx(const std::string& filePath) {
    return callPythonService(filePath);
}

std::string OfficeAnalyzer::analyzeXls(const std::string& filePath) {
    return callPythonService(filePath);
}

std::string OfficeAnalyzer::analyzePptx(const std::string& filePath) {
    return callPythonService(filePath);
}

std::string OfficeAnalyzer::analyzePpt(const std::string& filePath) {
    return callPythonService(filePath);
}

std::string OfficeAnalyzer::callPythonService(const std::string& filePath) {
    CURL* curl = curl_easy_init();
    if (!curl) {
        return "Error: Failed to initialize CURL";
    }

    std::string readBuffer;
    std::string url = pythonServiceUrl_ + "/api/office/parse";
    
    // Prepare JSON payload
    json payload;
    payload["file_path"] = filePath;
    std::string jsonStr = payload.dump();

    // Set headers
    struct curl_slist* headers = nullptr;
    headers = curl_slist_append(headers, "Content-Type: application/json");

    curl_easy_setopt(curl, CURLOPT_URL, url.c_str());
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, jsonStr.c_str());
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &readBuffer);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 60L);  // 60 second timeout

    CURLcode res = curl_easy_perform(curl);
    
    curl_slist_free_all(headers);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        return std::string("Error: HTTP request failed - ") + curl_easy_strerror(res);
    }

    // Parse response
    try {
        json response = json::parse(readBuffer);
        
        if (response.contains("success") && response["success"].get<bool>()) {
            return response.value("content", "");
        } else {
            std::string error = response.value("error", "Unknown error");
            return "Error from Python service: " + error;
        }
    } catch (const json::exception& e) {
        return std::string("Error parsing Python service response: ") + e.what();
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
    std::unique_ptr<FILE, int(*)(FILE*)> pipe(popen(cmd.c_str(), "r"), pclose);
    if (!pipe) {
        throw std::runtime_error("popen() failed!");
    }
    while (fgets(buffer.data(), buffer.size(), pipe.get()) != nullptr) {
        result += buffer.data();
    }
    return result;
}

std::string OfficeAnalyzer::analyzeToFile(const std::string& filePath, const std::string& outputDir) {
    // Get the content
    std::string content = analyze(filePath);
    
    // Check if there was an error
    if (content.find("Error:") == 0) {
        return "";  // Return empty string on error
    }
    
    // Get the base name and construct output path
    std::string baseName = getBaseName(filePath);
    
    // Determine output directory
    std::string outDir = outputDir;
    if (outDir.empty()) {
        // Use same directory as input file
        size_t lastSlash = filePath.find_last_of("/\\");
        if (lastSlash != std::string::npos) {
            outDir = filePath.substr(0, lastSlash);
        } else {
            outDir = ".";
        }
    }
    
    // Construct output path
    std::string outputPath = outDir + "/" + baseName + ".md";
    
    // Save to file
    if (saveToFile(content, outputPath)) {
        return outputPath;
    }
    
    return "";
}

std::string OfficeAnalyzer::getBaseName(const std::string& filePath) {
    // Find last path separator
    size_t lastSlash = filePath.find_last_of("/\\");
    std::string filename;
    
    if (lastSlash != std::string::npos) {
        filename = filePath.substr(lastSlash + 1);
    } else {
        filename = filePath;
    }
    
    // Remove extension
    size_t lastDot = filename.find_last_of('.');
    if (lastDot != std::string::npos) {
        return filename.substr(0, lastDot);
    }
    
    return filename;
}

bool OfficeAnalyzer::saveToFile(const std::string& content, const std::string& outputPath) {
    std::ofstream outFile(outputPath);
    if (!outFile.is_open()) {
        return false;
    }
    
    outFile << content;
    outFile.close();
    
    return outFile.good();
}

