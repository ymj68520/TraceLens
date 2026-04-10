// WindowsLLMAnalysisService_ArtifactAnalyzers.cpp
// Windows artifact LLM analysis methods

#include "WindowsLLMAnalysisService.h"
#include <iostream>
#include <sstream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeRegistryArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Windows registry artifacts.

Analyze this registry entry and provide:
1. Summary: Brief one-line description of what this registry value does
2. Description: Detailed explanation of its forensic significance
3. Keywords: 3-5 relevant keywords for search and categorization

Registry Entry:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "Registry analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeEventLogArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Windows event log entries.

Analyze this event log entry and provide:
1. Summary: Brief one-line description of the event
2. Description: Detailed explanation of its forensic significance and potential security implications
3. Keywords: 3-5 relevant keywords for categorization

Event Log Entry:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "Event log analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzePrefetchArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Windows prefetch files.

Analyze this prefetch file and provide:
1. Summary: Brief one-line description of the executable and its usage
2. Description: Detailed explanation of what this indicates about user activity
3. Keywords: 3-5 relevant keywords

Prefetch Data:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "Prefetch analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeLnkArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Windows LNK (shortcut) files.

Analyze this LNK file and provide:
1. Summary: Brief one-line description of what this shortcut points to
2. Description: Detailed explanation of its forensic significance
3. Keywords: 3-5 relevant keywords

LNK Data:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "LNK analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeJumpListArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Windows Jump List entries.

Analyze this Jump List entry and provide:
1. Summary: Brief one-line description
2. Description: Detailed explanation of user activity indicated
3. Keywords: 3-5 relevant keywords

Jump List Data:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "Jump List analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeBrowserArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing browser artifacts.

Analyze this browser artifact and provide:
1. Summary: Brief one-line description of the user's web activity
2. Description: Detailed explanation of forensic significance
3. Keywords: 3-5 relevant keywords

Browser Artifact:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "Browser artifact analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeSystemArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Windows system artifacts (services, tasks, Amcache, SRUM).

Analyze this system artifact and provide:
1. Summary: Brief one-line description
2. Description: Detailed explanation of forensic significance
3. Keywords: 3-5 relevant keywords

System Artifact:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "System artifact analysis failed: " << e.what() << std::endl;
    }

    return result;
}

WindowsLLMAnalysisService::AnalysisResult
WindowsLLMAnalysisService::analyzeMftArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing NTFS MFT entries.

Analyze this MFT entry and provide:
1. Summary: Brief one-line description
2. Description: Detailed explanation of forensic significance
3. Keywords: 3-5 relevant keywords

MFT Entry:
)" + data.dump() + R"(

Respond in JSON format:
{
  "summary": "brief description",
  "description": "detailed forensic analysis",
  "keywords": ["keyword1", "keyword2", "keyword3"]
})";

        auto response = router_->chat(prompt);
        if (response.success) {
            auto jsonResponse = json::parse(response.content);
            result.summary = jsonResponse.value("summary", "");
            result.description = jsonResponse.value("description", "");
            if (jsonResponse.contains("keywords")) {
                for (const auto& kw : jsonResponse["keywords"]) {
                    result.keywords.push_back(kw.get<std::string>());
                }
            }
            result.modelUsed = router_->getLastUsedModel();
            result.success = true;
        }
    } catch (const std::exception& e) {
        std::cerr << "MFT analysis failed: " << e.what() << std::endl;
    }

    return result;
}

} // namespace forensics
