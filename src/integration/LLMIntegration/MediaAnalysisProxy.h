#pragma once
#ifndef MEDIA_ANALYSIS_PROXY_H
#define MEDIA_ANALYSIS_PROXY_H

#include <string>
#include <httplib.h>
#include <functional>

namespace forensics {
namespace llm {

/**
 * @brief Result of one media (video/audio) content-description request.
 */
struct MediaDescriptionResult {
    bool ok = false;                // HTTP + payload parsed fine
    bool analyzed = false;          // content analysis ran (false = metadata-only skip)
    std::string description;        // final description text (always usable)
    std::string summary;
    std::string model;              // real model name, or "metadata_only"
    std::string extraction_method;  // e.g. video_segment_vision(...)/audio_transcript(...)
    std::string error;              // human-readable failure reason when !ok
};

/**
 * @brief Proxy for the Python media content-analysis services.
 *
 * describeVideo: segment-sampled multi-image vision calls plus a synthesis
 * pass (Python side owns ffmpeg + the vision model). Replaces the previous
 * behaviour of falling through to raw-read, which fed binary video bytes to
 * the text model as replacement-character garbage (2026-09-19 design).
 *
 * describeAudio: SenseVoice STT + synthesis for standalone audio files.
 * Replaces both the markitdown metadata-only path (.mp3/.wav) and the raw
 * read hole (.m4a/.amr/...).
 *
 * Calls are synchronous and can be long (minutes to tens of minutes), so
 * the read timeout is far larger than markitdown's.
 */
class MediaAnalysisProxy {
public:
    static MediaAnalysisProxy& instance();

    using HttpPoster = std::function<httplib::Result(const std::string&, const std::string&, const std::string&)>;

    explicit MediaAnalysisProxy(std::string pythonServiceUrl, HttpPoster poster = {});

    /**
     * @brief Describe one video file via the Python segment-vision service.
     */
    MediaDescriptionResult describeVideo(const std::string& filePath);

    /**
     * @brief Transcribe + describe one audio file via the Python STT service.
     */
    MediaDescriptionResult describeAudio(const std::string& filePath);

private:
    MediaDescriptionResult describe(const std::string& endpoint, const std::string& filePath);
    std::string pythonServiceUrl_;
    HttpPoster http_poster_{};
};

} // namespace llm
} // namespace forensics

#endif // MEDIA_ANALYSIS_PROXY_H
