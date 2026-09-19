#pragma once
#ifndef VIDEO_ANALYSIS_PROXY_H
#define VIDEO_ANALYSIS_PROXY_H

#include <string>
#include <httplib.h>
#include <functional>

namespace forensics {
namespace llm {

/**
 * @brief Result of one video content-description request.
 */
struct VideoDescriptionResult {
    bool ok = false;                // HTTP + payload parsed fine
    bool analyzed = false;          // content analysis ran (false = metadata-only skip)
    std::string description;        // final description text (always usable)
    std::string summary;
    std::string model;              // real model name, or "metadata_only"
    std::string extraction_method;  // e.g. video_segment_vision(fps=1,segs=4,frames=52)
    std::string error;              // human-readable failure reason when !ok
};

/**
 * @brief Proxy for the Python video content-analysis service.
 *
 * Describes a video by segment-sampled multi-image vision calls plus a
 * synthesis pass (Python side owns ffmpeg + the vision model). This replaces
 * the previous behaviour of falling through to raw-read, which fed binary
 * video bytes to the text model as replacement-character garbage
 * (2026-09-19 video analysis design).
 *
 * The call is synchronous and long: a sub-30min video at 1 fps takes minutes
 * to tens of minutes, so the read timeout is far larger than markitdown's.
 *
 * Usage:
 *   auto& proxy = VideoAnalysisProxy::instance();
 *   auto result = proxy.describeVideo("/path/to/video.mp4");
 */
class VideoAnalysisProxy {
public:
    /**
     * @brief Get the singleton instance.
     */
    static VideoAnalysisProxy& instance();

    using HttpPoster = std::function<httplib::Result(const std::string&, const std::string&, const std::string&)>;

    explicit VideoAnalysisProxy(std::string pythonServiceUrl, HttpPoster poster = {});

    /**
     * @brief Describe one video file via the Python service.
     *
     * @param filePath Absolute host path to an extracted video file.
     * @return Always yields a usable ``description`` on HTTP success —
     *         oversize/unreadable videos come back as metadata-only text
         (``analyzed == false``). On transport/HTTP failure ``ok == false``
         and ``error`` carries the reason; the caller falls back to a local
         metadata-only description (never a raw byte read).
     */
    VideoDescriptionResult describeVideo(const std::string& filePath);

private:
    std::string pythonServiceUrl_;
    HttpPoster http_poster_{};
};

} // namespace llm
} // namespace forensics

#endif // VIDEO_ANALYSIS_PROXY_H
