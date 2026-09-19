"""Tests for the video segment analyzer (2026-09-19 video content analysis).

Covers: segment planning, the too-long metadata-only skip, the ffmpeg-missing
skip, the serial segment loop with multi-image vision calls (fake LLM), the
empty-content retry, and the synthesis call. Real ffmpeg decoding is exercised
when ffmpeg is available (skipped otherwise).
"""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from httpserver.services.llm import video_analyzer
from httpserver.services.llm import audio_analyzer
from httpserver.services.llm.video_analyzer import plan_segments


# ---------------------------------------------------------------------------
# plan_segments (pure)
# ---------------------------------------------------------------------------

def test_plan_segments_covers_full_duration():
    plans = plan_segments(47, 15)
    assert [(p.start, p.duration) for p in plans] == [
        (0.0, 15.0), (15.0, 15.0), (30.0, 15.0), (45.0, 2.0),
    ]
    assert plans[-1].end == 47.0


def test_plan_segments_single_short_video():
    plans = plan_segments(8, 15)
    assert [(p.start, p.duration) for p in plans] == [(0.0, 8.0)]


def test_plan_segments_no_duration_no_segments():
    assert plan_segments(0, 15) == []
    assert plan_segments(-3, 15) == []


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeLLMService:
    """Records analyze_images/analyze calls with canned answers."""

    def __init__(self, segment_descriptions=None, synthesis_text="SUMMARY: s\nDESCRIPTION: d\nKEYWORDS: k"):
        self.segment_descriptions = segment_descriptions or []
        self.synthesis_text = synthesis_text
        self.images_calls = []       # list of (frame_count, prompt)
        self.analyze_calls = []      # list of (content, prompt)
        self._seg_index = 0

    async def analyze_images(self, image_data_list, prompt=None):
        self.images_calls.append((len(image_data_list), prompt))
        if self._seg_index < len(self.segment_descriptions):
            desc = self.segment_descriptions[self._seg_index]
        else:
            desc = f"segment-{self._seg_index}"
        self._seg_index += 1
        return {
            "analysis": {"description": desc, "summary": "", "keywords": [], "value": ""},
            "model": "fake-vision",
            "tokens_used": 10,
        }

    async def analyze(self, content, model_type="text", prompt=None, **kwargs):
        self.analyze_calls.append((content, prompt))
        return {
            "analysis": {
                "description": self.synthesis_text,
                "summary": "s", "keywords": ["k"], "value": "",
            },
            "model": "fake-text",
            "tokens_used": 20,
        }


class FlakyLLMService(FakeLLMService):
    """First analyze_images call returns empty content (nemotron quirk)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._first_call = True

    async def analyze_images(self, image_data_list, prompt=None):
        if self._first_call:
            self._first_call = False
            self.images_calls.append((len(image_data_list), prompt))
            return {"analysis": {"description": ""}, "model": "fake-vision", "tokens_used": 0}
        return await super().analyze_images(image_data_list, prompt)


class NoLLMService:
    def __init__(self):
        self.called = False

    async def analyze_images(self, *a, **k):  # pragma: no cover
        self.called = True
        raise AssertionError("no LLM call expected")

    async def analyze(self, *a, **k):  # pragma: no cover
        self.called = True
        raise AssertionError("no LLM call expected")


def _ffprobe_payload(duration: float) -> dict:
    return {
        "format": {"duration": str(duration), "bit_rate": "1000000"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 320, "height": 240},
            {"codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
    }


class _Settings:
    llm_video_fps = 1
    llm_video_segment_seconds = 15
    llm_video_max_duration = 1800
    llm_audio_max_duration = 3600
    audio_stt_model_dir = ""


def _no_transcript(*a, **k):
    """Stub: video tests below exercise the frames path with STT unavailable."""
    from httpserver.services.llm.audio_analyzer import TranscriptionOutcome
    return TranscriptionOutcome(unavailable_reason="stub: no STT in unit test")


@pytest.fixture
def fake_probe(monkeypatch):
    """Pin ffprobe output so tests don't need a real container file."""
    holder = {}

    def _install(duration):
        monkeypatch.setattr(video_analyzer, "run_ffprobe", lambda _p: _ffprobe_payload(duration))
        holder["duration"] = duration

    holder["install"] = _install
    yield holder


# ---------------------------------------------------------------------------
# Skip paths (no LLM, no raw bytes anywhere)
# ---------------------------------------------------------------------------

def test_too_long_video_skips_content_analysis(fake_probe, monkeypatch, tmp_path):
    fake_probe["install"](3600)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    video = tmp_path / "long.mp4"
    video.write_bytes(b"container")

    llm = NoLLMService()
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=_Settings(),
    ))

    assert not llm.called
    assert method == "video_metadata_only"
    assert "留待后续补齐" in result["analysis"]["description"]
    assert "音频轨道未分析" in result["analysis"]["description"]
    assert result["model"] == "metadata_only"


def test_missing_ffmpeg_skips_content_analysis(fake_probe, monkeypatch, tmp_path):
    fake_probe["install"](60)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"container")

    llm = NoLLMService()
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=_Settings(),
    ))

    assert not llm.called
    assert method == "video_metadata_only"
    assert "ffmpeg" in result["analysis"]["description"]


def test_zero_cap_disables_too_long_skip(fake_probe, monkeypatch, tmp_path):
    """max_duration=0 means no cap — content analysis must run (fake ffmpeg)."""
    fake_probe["install"](3600)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(video_analyzer, "_extract_segment_frames",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no real decode in unit test")))
    video = tmp_path / "long.mp4"
    video.write_bytes(b"container")

    settings = _Settings()
    settings.llm_video_max_duration = 0

    class OneFrameLLM(FakeLLMService):
        async def analyze_images(self, image_data_list, prompt=None):
            # pretend extraction produced frames even though extraction is mocked out
            return await super().analyze_images(image_data_list or [b"x"], prompt)

    llm = OneFrameLLM()
    # frame extraction is mocked to raise; segments degrade to failure notes
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=settings,
    ))

    assert method.startswith("video_segment_vision")
    assert llm.analyze_calls  # synthesis ran


# ---------------------------------------------------------------------------
# Serial segment loop + synthesis (fake LLM)
# ---------------------------------------------------------------------------

def test_segment_loop_calls_vision_then_synthesis(fake_probe, monkeypatch, tmp_path):
    monkeypatch.setattr(audio_analyzer, "transcribe_source", _no_transcript)
    fake_probe["install"](40)  # 15+15+10s → 3 segments
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    seen_frames = {}

    def fake_extract(file_path, plan, fps, out_dir):
        # one tiny frame per planned second
        n = max(1, int(plan.duration * fps))
        paths = []
        for i in range(n):
            p = Path(out_dir) / f"frame_{i:04d}.jpg"
            p.write_bytes(b"\xff\xd8fake")
            paths.append(str(p))
        seen_frames["count"] = seen_frames.get("count", 0) + n
        return paths

    monkeypatch.setattr(video_analyzer, "_extract_segment_frames", fake_extract)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"container")

    llm = FakeLLMService(segment_descriptions=["seg1 note", "seg2 note", "seg3 note"])
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=_Settings(), case_context="电信诈骗案",
    ))

    # Serial: exactly one multi-image call per segment, in order.
    assert [c[0] for c in llm.images_calls] == [15, 15, 10]
    assert "1/3" in llm.images_calls[0][1] and "0s–15s" in llm.images_calls[0][1]
    assert "电信诈骗案" in llm.images_calls[0][1]

    # Synthesis gets metadata + all segment notes + audio disclaimer.
    assert len(llm.analyze_calls) == 1
    content, synth_prompt = llm.analyze_calls[0]
    assert "seg1 note" in content and "seg3 note" in content
    assert "音频轨道未分析" in content
    assert "SUMMARY" in synth_prompt

    assert method == "video_segment_vision(fps=1,segs=3,frames=40)"
    assert result["analysis"]["description"].startswith("SUMMARY")


def test_empty_segment_answer_is_retried(fake_probe, monkeypatch, tmp_path):
    monkeypatch.setattr(audio_analyzer, "transcribe_source", _no_transcript)
    fake_probe["install"](15)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(
        video_analyzer, "_extract_segment_frames",
        lambda fp, plan, fps, out: [str(Path(out) / "frame_0001.jpg")],
    )
    (tmp_path / "seg_001").mkdir()

    def fake_extract(fp, plan, fps, out_dir):
        p = Path(out_dir) / "frame_0001.jpg"
        p.write_bytes(b"\xff\xd8fake")
        return [str(p)]

    monkeypatch.setattr(video_analyzer, "_extract_segment_frames", fake_extract)
    video = tmp_path / "v.mp4"
    video.write_bytes(b"container")

    llm = FlakyLLMService()
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=_Settings(),
    ))

    # first call empty → retried once → success; synthesis still ran
    assert len(llm.images_calls) == 2
    assert method == "video_segment_vision(fps=1,segs=1,frames=1)"
    assert "SUMMARY" in result["analysis"]["description"]


def test_failing_segment_degrades_to_marker(fake_probe, monkeypatch, tmp_path):
    monkeypatch.setattr(audio_analyzer, "transcribe_source", _no_transcript)
    fake_probe["install"](30)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)

    def failing_extract(fp, plan, fps, out_dir):
        raise RuntimeError("moov atom not found")

    monkeypatch.setattr(video_analyzer, "_extract_segment_frames", failing_extract)
    video = tmp_path / "broken.mp4"
    video.write_bytes(b"container")

    llm = FakeLLMService()
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=_Settings(),
    ))

    # both segments failed → notes carry honest markers, synthesis still runs
    content, _ = llm.analyze_calls[0]
    assert content.count("抽帧失败") == 2
    assert method == "video_segment_vision(fps=1,segs=2,frames=0)"
    assert result["analysis"]["description"]


# ---------------------------------------------------------------------------
# Real ffmpeg decoding (integration-grade; skipped without ffmpeg)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_real_frame_extraction(tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10:duration=3",
         "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )
    out_dir = tmp_path / "frames"
    out_dir.mkdir()
    paths = video_analyzer._extract_segment_frames(
        str(src), video_analyzer.SegmentPlan(start=0.0, duration=3.0), fps=1, out_dir=str(out_dir)
    )
    assert len(paths) == 3
    assert all(Path(p).stat().st_size > 0 for p in paths)
