"""Tests for resilient video metadata extraction."""
from types import SimpleNamespace

import pytest

from httpserver.services.extractors import get_extractor
from httpserver.services.extractors import media_metadata
from httpserver.services.extractors.media_metadata import VideoExtractor


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"not a real video")
    return path


@pytest.mark.asyncio
async def test_video_extractor_formats_ffprobe_metadata(video_file, monkeypatch):
    monkeypatch.setattr(media_metadata, "_run_ffprobe", lambda _: {
        "format": {"duration": "10.5", "bit_rate": "123456", "tags": {"title": "Evidence"}},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30000/1001",
                "bit_rate": "100000",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
                "bit_rate": "64000",
            },
        ],
    })

    result = await VideoExtractor(sample_frames=0).extract_to_markdown(str(video_file))

    assert "**Duration:** 10.5s" in result
    assert "**Bit Rate:** 123 kbps" in result
    assert "| h264 | 1920x1080 | 29.97 | 100 kbps |" in result
    assert "| aac | 48000 Hz | 2 | 64 kbps |" in result
    assert "Evidence" in result


@pytest.mark.asyncio
async def test_video_extractor_handles_unknown_ffprobe_values(video_file, monkeypatch):
    monkeypatch.setattr(media_metadata, "_run_ffprobe", lambda _: {
        "format": {"duration": "N/A", "bit_rate": "N/A"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 480,
                "r_frame_rate": "0/0",
                "bit_rate": "N/A",
            },
        ],
    })

    result = await VideoExtractor(sample_frames=0).extract_to_markdown(str(video_file))

    assert "**Duration:**" not in result
    assert "**Bit Rate:** N/A" in result
    assert "| h264 | 640x480 | N/A | N/A |" in result


@pytest.mark.asyncio
async def test_video_extractor_reports_ffmpeg_sample_failure(video_file, monkeypatch):
    monkeypatch.setattr(media_metadata, "_run_ffprobe", lambda _: {
        "format": {"duration": "10"},
        "streams": [],
    })
    monkeypatch.setattr(
        media_metadata.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="decode failed"),
    )

    result = await VideoExtractor(sample_frames=2).extract_to_markdown(str(video_file))

    assert "## Temporary Frame Samples (Up to 2)" in result
    assert "*Could not create frame samples; the video may be incomplete or ffmpeg is unavailable.*" in result


@pytest.mark.asyncio
async def test_video_extractor_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "clip.txt"
    path.write_text("not a video")

    result = await VideoExtractor().extract_to_markdown(str(path))

    assert result == "Error: .txt is not a recognized video format."


def test_video_extractor_is_registered():
    assert isinstance(get_extractor(".mp4"), VideoExtractor)
