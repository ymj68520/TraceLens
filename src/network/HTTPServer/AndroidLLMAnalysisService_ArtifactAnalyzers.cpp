// AndroidLLMAnalysisService_ArtifactAnalyzers.cpp
// Android artifact LLM analysis methods — per-type prompt construction and
// ModelRouter::chat() invocation. Mirrors the structure of
// LinuxLLMAnalysisService_ArtifactAnalyzers.cpp, but uses a shared
// analyzeWithPrompt() helper to avoid duplicating the JSON parse/response handling.

#include "AndroidLLMAnalysisService.h"
#include <iostream>
#include <nlohmann/json.hpp>

using json = nlohmann::json;

namespace forensics {

// Shared helper: build a standard forensic-analysis prompt around the artifact
// JSON, call the router, and parse the {summary, description, keywords} reply.
AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeWithPrompt(const std::string& roleDescription,
                                             const std::string& artifactJson,
                                             const std::string& guidance) {
    AnalysisResult result;
    result.success = false;

    try {
        std::string prompt = std::string("You are a digital forensics expert analyzing ") +
            roleDescription + ".\n\n" +
            "Analyze this artifact and provide:\n"
            "1. Summary: Brief one-line description of the artifact / event\n"
            "2. Description: Detailed explanation of its forensic significance and potential security implications\n"
            "3. Keywords: 3-5 relevant keywords for categorization\n\n"
            + guidance + "\n\n" +
            "Artifact:\n" + artifactJson + "\n\n"
            "Respond in JSON format:\n"
            "{\n"
            "  \"summary\": \"brief description\",\n"
            "  \"description\": \"detailed forensic analysis\",\n"
            "  \"keywords\": [\"keyword1\", \"keyword2\", \"keyword3\"]\n"
            "}";

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
        std::cerr << "Android artifact analysis failed: " << e.what() << std::endl;
    }

    return result;
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeSmsArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "Android SMS / MMS messages",
        artifact.data,
        "Focus on the timeline (date), direction (type field: 1=received, 2=sent), "
        "sender/recipient, and any suspicious content such as phishing links, "
        "verification codes, or one-time passwords that may indicate account takeover.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeWechatMessageArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "WeChat (com.tencent.mm) chat messages",
        artifact.data,
        "WeChat is a primary communication channel. Note the sender/receiver, "
        "chatroom context (chatroom_name), message type (msg_type), direction "
        "(is_send), and timestamp. Flag transactions, shared files, sensitive "
        "topics, or coordination of interest to the investigation.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeGenericMessageArtifact(const ArtifactRecord& artifact,
                                                         const char* platformLabel) {
    std::string role = std::string(platformLabel) + " chat messages on Android";
    return analyzeWithPrompt(
        role,
        artifact.data,
        "Consider the sender, receiver, content, and timestamp. Identify any "
        "coordination, shared media, or content relevant to a forensic timeline.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeContactArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "Android address-book contacts",
        artifact.data,
        "Identify the contact's identity (display name, phone, email) and account "
        "source. Note duplicates, suspicious or burner numbers, and any linkage "
        "to messaging apps observed elsewhere in the extraction.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeCallLogArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "Android call-history records",
        artifact.data,
        "Interpret call type (1=incoming, 2=outgoing, 3=missed, 4=voicemail, 5=rejected), "
        "duration, and timestamp. Highlight frequent contacts, odd-hour calls, "
        "or calls correlating with other case events.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeMiuiManifestArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "a MIUI (Xiaomi) backup manifest describing the device and its backup snapshot",
        artifact.data,
        "This single row summarizes the whole backup. Note device model, MIUI "
        "version, backup date, total size and package count — these anchor the "
        "extraction's provenance and timeframe.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeInstalledAppArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "an installed application recorded in a MIUI backup",
        artifact.data,
        "Assess the app's forensic relevance: messaging/finance/cloud apps may "
        "carry evidence; note data_size (large caches may warrant deeper "
        "extraction) and the backup type flag.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeSqliteRecordArtifact(const ArtifactRecord& artifact,
                                                       const char* platformLabel) {
    std::string role = std::string("a recovered structured SQLite record from a ") +
                       platformLabel + " app database";
    return analyzeWithPrompt(
        role,
        artifact.data,
        "The record_json field holds the parsed row. Extract entities (accounts, "
        "chat ids, timestamps) and judge the artifact_kind. Flag sensitive "
        "records (tokens, credentials) accordingly.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeWechatKvArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "a WeChat key/value configuration record (SharedPreferences / MMKV)",
        artifact.data,
        "is_sensitive marks tokens/identifiers (uin, imei, mac, device id, "
        "authtoken). Describe what the value identifies and its forensic value "
        "(account linkage, device fingerprinting).");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeSystemLogArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "Android system log entries (logcat / dmesg)",
        artifact.data,
        "Note the log level, tag, process and timestamp. Flag security-relevant "
        "events: crashes, permission grants, SELinux denials, package installs, "
        "or app-driven activity of investigative interest.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeDeviceIdentifierArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "Android device identifiers (SSAID / Android ID per app)",
        artifact.data,
        "Each (package_name, value) pair is an app-scoped Android ID. Note "
        "identifier_type, the owning package, and the source path. These support "
        "cross-app and cross-device correlation.");
}

AndroidLLMAnalysisService::AnalysisResult
AndroidLLMAnalysisService::analyzeWifiNetworkArtifact(const ArtifactRecord& artifact) {
    return analyzeWithPrompt(
        "a saved WiFi network from the Android WiFi configuration store",
        artifact.data,
        "SSIDs reveal locations the device connected to; pre_shared_key exposure "
        "is itself evidentiary. Note key_mgmt (security type) and last_connected "
        "for geolocation / timeline correlation.");
}

} // namespace forensics
