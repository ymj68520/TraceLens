// LinuxLLMAnalysisService_SystemAnalyzers.cpp
// Linux artifact LLM analysis methods (Part 2: Packages, Network, Systemd, Kernel, Firewall, Audit, Browser)

#include "LinuxLLMAnalysisService.h"
#include <iostream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzePackageArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing installed Linux packages.

Analyze this package and provide:
1. Summary: Brief one-line description of the software
2. Description: Detailed explanation of forensic significance (software inventory, potential security tools, attack surface)
3. Keywords: 3-5 relevant keywords

Package:
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
        std::cerr << "Package analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeNetworkArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux network connections.

Analyze this network connection and provide:
1. Summary: Brief one-line description of the connection
2. Description: Detailed explanation of forensic significance (remote access, data exfiltration, C2 communication)
3. Keywords: 3-5 relevant keywords

Network Connection:
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
        std::cerr << "Network connection analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeSystemdArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux systemd services.

Analyze this systemd service and provide:
1. Summary: Brief one-line description of the service
2. Description: Detailed explanation of forensic significance (persistence, privilege escalation, system configuration)
3. Keywords: 3-5 relevant keywords

Systemd Service:
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
        std::cerr << "Systemd service analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeKernelModuleArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux kernel modules.

Analyze this kernel module and provide:
1. Summary: Brief one-line description of the module
2. Description: Detailed explanation of forensic significance (rootkits, system modification, kernel-level access)
3. Keywords: 3-5 relevant keywords

Kernel Module:
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
        std::cerr << "Kernel module analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeFirewallArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux firewall rules.

Analyze this firewall rule and provide:
1. Summary: Brief one-line description of the rule
2. Description: Detailed explanation of forensic significance (network access control, potential backdoors)
3. Keywords: 3-5 relevant keywords

Firewall Rule:
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
        std::cerr << "Firewall rule analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeAuditLogArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux audit logs.

Analyze this audit log entry and provide:
1. Summary: Brief one-line description of the audited event
2. Description: Detailed explanation of forensic significance (security-relevant actions, system modifications)
3. Keywords: 3-5 relevant keywords

Audit Log:
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
        std::cerr << "Audit log analysis failed: " << e.what() << std::endl;
    }

    return result;
}

LinuxLLMAnalysisService::AnalysisResult
LinuxLLMAnalysisService::analyzeBrowserProfileArtifact(const ArtifactRecord& artifact) {
    AnalysisResult result;
    result.success = false;

    try {
        auto data = json::parse(artifact.data);

        std::string prompt = R"(You are a digital forensics expert analyzing Linux browser profiles.

Analyze this browser profile and provide:
1. Summary: Brief one-line description
2. Description: Detailed explanation of forensic significance (web activity, user behavior)
3. Keywords: 3-5 relevant keywords

Browser Profile:
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
        std::cerr << "Browser profile analysis failed: " << e.what() << std::endl;
    }

    return result;
}

} // namespace forensics
