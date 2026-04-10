// LinuxLLMAnalysisService_ArtifactAnalyzers.cpp
// Linux artifact LLM analysis methods (Part 1: Logs, Users, Logins, Shell, Cron, SSH)

#include "LinuxLLMAnalysisService.h"
#include <iostream>
#include <sstream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeLogArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux system log entries.

Analyze this log entry and provide:
1. Summary: Brief one-line description of the event
2. Description: Detailed explanation of its forensic significance and potential security implications
3. Keywords: 3-5 relevant keywords for categorization

Log Entry:
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
        std::cerr << "Log analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeUserArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux user accounts.

Analyze this user account and provide:
1. Summary: Brief one-line description of the user and their privilege level
2. Description: Detailed explanation of forensic significance (system vs user, access patterns, security concerns)
3. Keywords: 3-5 relevant keywords

User Account:
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
        std::cerr << "User analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeLoginArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux login records.

Analyze this login record and provide:
1. Summary: Brief one-line description of the login activity
2. Description: Detailed explanation of forensic significance (authentication patterns, remote access, anomalies)
3. Keywords: 3-5 relevant keywords

Login Record:
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
        std::cerr << "Login analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeShellHistoryArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux shell history.

Analyze this shell command and provide:
1. Summary: Brief one-line description of what the command does
2. Description: Detailed explanation of forensic significance (system administration, potential malware, data access)
3. Keywords: 3-5 relevant keywords

Shell History Entry:
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
        std::cerr << "Shell history analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeCronArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux cron jobs.

Analyze this cron job and provide:
1. Summary: Brief one-line description of the scheduled task
2. Description: Detailed explanation of forensic significance (persistence mechanism, automated activity)
3. Keywords: 3-5 relevant keywords

Cron Job:
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
        std::cerr << "Cron job analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeSSHArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux SSH artifacts (keys or known hosts).

Analyze this SSH artifact and provide:
1. Summary: Brief one-line description
2. Description: Detailed explanation of forensic significance (remote access, authentication trails)
3. Keywords: 3-5 relevant keywords

SSH Artifact:
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
        std::cerr << "SSH artifact analysis failed: " << e.what() << std::endl;
    }

    return result;
}

} // namespace forensics
