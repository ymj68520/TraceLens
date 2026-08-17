"""D4b: temporary analysis resource cleanup tests."""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import patch

import pytest

from httpserver.services.extractors.media_metadata import VideoExtractor


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "sample.mp4"
    path.write_bytes(b"placeholder-video-bytes")
    return str(path)


def _make_tmp_dir(tmp_path):
    """Point the extractor's scratch at an observable directory."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return scratch


@pytest.mark.asyncio
async def test_video_frame_samples_removed_on_success(video_file, tmp_path):
    scratch = _make_tmp_dir(tmp_path)
    captured = {}

    def fake_mkdtemp(*args, **kwargs):
        target = scratch / "samples"
        target.mkdir()
        captured["dir"] = str(target)
        (target / "frame_001.jpg").write_bytes(b"jpg")
        return str(target)

    class OkRun:
        returncode = 0

    with patch(
        "httpserver.services.extractors.media_metadata.tempfile.mkdtemp",
        side_effect=fake_mkdtemp,
    ), patch(
        "httpserver.services.extractors.media_metadata.subprocess.run",
        return_value=OkRun(),
    ), patch(
        "httpserver.services.extractors.media_metadata._run_ffprobe",
        return_value={"format": {"duration": "2.0"}},
    ):
        extractor = VideoExtractor(sample_frames=1)
        markdown = await extractor.extract_to_markdown(video_file)

    assert "temporary frame sample(s) for analysis" in markdown
    # The removed scratch path must not leak into the returned Markdown.
    assert captured["dir"] not in markdown
    assert not os.path.exists(captured["dir"])


@pytest.mark.asyncio
async def test_video_frame_samples_removed_on_ffmpeg_failure(video_file, tmp_path):
    scratch = _make_tmp_dir(tmp_path)
    captured = {}

    def fake_mkdtemp(*args, **kwargs):
        target = scratch / "samples"
        target.mkdir()
        captured["dir"] = str(target)
        return str(target)

    class FailingRun:
        returncode = 1

    with patch(
        "httpserver.services.extractors.media_metadata.tempfile.mkdtemp",
        side_effect=fake_mkdtemp,
    ), patch(
        "httpserver.services.extractors.media_metadata.subprocess.run",
        return_value=FailingRun(),
    ), patch(
        "httpserver.services.extractors.media_metadata._run_ffprobe",
        return_value={"format": {"duration": "2.0"}},
    ):
        extractor = VideoExtractor(sample_frames=1)
        markdown = await extractor.extract_to_markdown(video_file)

    assert "Could not create frame samples" in markdown
    assert not os.path.exists(captured["dir"])


@pytest.mark.asyncio
async def test_video_frame_samples_removed_on_subprocess_error(video_file, tmp_path):
    scratch = _make_tmp_dir(tmp_path)
    captured = {}

    def fake_mkdtemp(*args, **kwargs):
        target = scratch / "samples"
        target.mkdir()
        captured["dir"] = str(target)
        return str(target)

    def raising_run(*args, **kwargs):
        raise FileNotFoundError("ffmpeg missing")

    with patch(
        "httpserver.services.extractors.media_metadata.tempfile.mkdtemp",
        side_effect=fake_mkdtemp,
    ), patch(
        "httpserver.services.extractors.media_metadata.subprocess.run",
        side_effect=raising_run,
    ), patch(
        "httpserver.services.extractors.media_metadata._run_ffprobe",
        return_value={"format": {"duration": "2.0"}},
    ):
        extractor = VideoExtractor(sample_frames=1)
        markdown = await extractor.extract_to_markdown(video_file)

    assert "Frame sampling unavailable" in markdown
    assert not os.path.exists(captured["dir"])


@pytest.mark.asyncio
async def test_video_no_duration_skips_sampling_entirely(video_file):
    with patch(
        "httpserver.services.extractors.media_metadata.tempfile.mkdtemp",
    ) as fake_mkdtemp, patch(
        "httpserver.services.extractors.media_metadata._run_ffprobe",
        return_value={"format": {}},
    ):
        extractor = VideoExtractor(sample_frames=3)
        markdown = await extractor.extract_to_markdown(video_file)

    assert "Frame sampling skipped" in markdown
    fake_mkdtemp.assert_not_called()
