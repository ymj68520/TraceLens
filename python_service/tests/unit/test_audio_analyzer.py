"""Tests for the audio transcription stack (2026-09-19 audio analysis design).

Covers: excerpt bands, the transcript store (append-only + latest-wins), the
duration cap → pending_backfill row, STT-unavailable degradation, complete-
transcript reuse without re-running STT, synthesis with duration-banded
excerpt caps, and the video soundtrack integration.
"""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from httpserver.services.llm import audio_analyzer
from httpserver.services.llm.audio_analyzer import (
    TranscriptionOutcome,
    analyze_audio_file,
    excerpt_cap,
    transcribe_source,
)
from httpserver.services.llm.audio_transcript_store import (
    ensure_audio_transcript_schema,
    latest_transcript,
    save_transcript,
    segments_to_timeline,
)


class _Settings:
    llm_audio_max_duration = 3600
    audio_stt_model_dir = ""


def test_excerpt_cap_bands():
    assert excerpt_cap(60) == 5
    assert excerpt_cap(300) == 5
    assert excerpt_cap(301) == 10
    assert excerpt_cap(1200) == 10
    assert excerpt_cap(1201) == 15
    assert excerpt_cap(2700) == 15
    assert excerpt_cap(2701) == 20


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

def test_store_append_only_and_latest_wins():
    db = tempfile.mktemp(suffix=".db")
    ensure_audio_transcript_schema(db)
    save_transcript(db, {"task_id": "t", "file_path": "/a.mp3", "md5": "m",
                         "status": "partial", "segments": [{"s": 0, "text": "x"}],
                         "created_at": int(time.time())})
    save_transcript(db, {"task_id": "t", "file_path": "/a.mp3", "md5": "m",
                         "status": "complete", "segments": [{"s": 0, "text": "你好"}],
                         "full_text": "你好", "created_at": int(time.time()) + 1})
    latest = latest_transcript(db, "/a.mp3", md5="m")
    assert latest["status"] == "complete"
    assert latest["segments"][0]["text"] == "你好"
    # source filter keeps audio/video-track rows apart
    assert latest_transcript(db, "/a.mp3", md5="m", source="video-track") is None


def test_timeline_timestamps_and_truncation():
    segments = [
        {"s": 0, "e": 2, "text": "第一句"},
        {"s": 75, "e": 78, "text": "第二句"},
        {"s": 3675, "e": 3680, "text": "一小时后"},
    ]
    timeline = segments_to_timeline(segments)
    assert timeline.startswith("[00:00] 第一句")
    assert "[01:15] 第二句" in timeline
    assert "[1:01:15] 一小时后" in timeline
    assert len(segments_to_timeline(segments, limit_chars=10)) <= 20


# ---------------------------------------------------------------------------
# transcribe_source policy paths (no real STT)
# ---------------------------------------------------------------------------

def _probe_payload(duration):
    return {"format": {"duration": str(duration)}, "streams": [{"codec_type": "audio"}]}


def test_over_cap_yields_pending_backfill_row(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_analyzer, "run_ffprobe", lambda p: _probe_payload(4500))
    called = {"stt": False}

    def _no_stt(_dir):
        called["stt"] = True
        raise AssertionError("STT must not run for over-cap audio")

    monkeypatch.setattr(audio_analyzer, "_get_engine", _no_stt)
    files_db = str(tmp_path / "t_files.db")

    outcome = transcribe_source(
        "/x/amr audio.mp3", settings=_Settings(), files_db_path=files_db,
        task_id="t1", trigger_source="pipeline",
    )

    assert not called["stt"]
    assert outcome.record["status"] == "pending_backfill"
    assert outcome.record["coverage"] == 0.0
    assert "待补齐" in outcome.record["note"]
    row = latest_transcript(files_db, "/x/amr audio.mp3")
    assert row["status"] == "pending_backfill"


def test_missing_model_dir_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_analyzer, "run_ffprobe", lambda p: _probe_payload(60))
    monkeypatch.setattr(audio_analyzer, "_model_dir", lambda s: None)
    outcome = transcribe_source("/x/a.mp3", settings=_Settings())
    assert outcome.record is None
    assert "模型未部署" in outcome.unavailable_reason


def test_complete_transcript_is_reused_without_stt(monkeypatch, tmp_path):
    monkeypatch.setattr(audio_analyzer, "run_ffprobe", lambda p: _probe_payload(60))
    files_db = str(tmp_path / "t_files.db")
    ensure_audio_transcript_schema(files_db)
    save_transcript(files_db, {
        "task_id": "t", "file_path": "/x/a.mp3", "md5": "", "source": "audio",
        "status": "complete", "segments": [{"s": 0, "e": 2, "text": "已存档"}],
        "created_at": int(time.time()),
    })

    def _no_stt(_dir):
        raise AssertionError("STT must not re-run when a complete row exists")

    monkeypatch.setattr(audio_analyzer, "_get_engine", _no_stt)
    outcome = transcribe_source("/x/a.mp3", settings=_Settings(), files_db_path=files_db)
    assert outcome.reused
    assert outcome.record["segments"][0]["text"] == "已存档"


# ---------------------------------------------------------------------------
# analyze_audio_file synthesis paths (fake LLM)
# ---------------------------------------------------------------------------

class FakeLLMService:
    def __init__(self, text="SUMMARY: s\nDESCRIPTION: d\nKEYWORDS: k"):
        self.text = text
        self.analyze_calls = []

    async def analyze(self, content, model_type="text", prompt=None, **kw):
        self.analyze_calls.append((content, prompt))
        return {
            "analysis": {"description": self.text, "summary": "s",
                         "keywords": ["k"], "value": ""},
            "model": "fake-text", "tokens_used": 5,
        }


class _NoLLM:
    async def analyze(self, *a, **k):  # pragma: no cover
        raise AssertionError("no synthesis expected")


def test_analyze_audio_pending_backfill_returns_metadata_description(monkeypatch, tmp_path):
    record = {"file_path": "/x/long.mp3", "md5": "m", "source": "audio",
              "status": "pending_backfill", "coverage": 0.0,
              "note": "时长 01:15:00 超过上限 01:00:00,待补齐", "segments": [],
              "duration_sec": 4500}
    monkeypatch.setattr(
        audio_analyzer, "transcribe_source",
        lambda *a, **k: TranscriptionOutcome(record=record))
    monkeypatch.setattr(audio_analyzer, "run_ffprobe", lambda p: _probe_payload(4500))

    result, method = asyncio.run(analyze_audio_file(
        "/x/long.mp3", llm_service=_NoLLM(), settings=_Settings()))

    assert method == "audio_metadata_only"
    assert "待补齐" in result["analysis"]["description"]


def test_analyze_audio_synthesis_uses_duration_band(monkeypatch):
    record = {"file_path": "/x/short.mp3", "md5": "m", "source": "audio",
              "status": "complete", "coverage": 1.0, "engine": "sensevoice-small-onnx",
              "language": "zh", "duration_sec": 120,
              "segments": [{"s": 0, "e": 2, "text": "把账号发我"}],
              "full_text": "把账号发我"}
    monkeypatch.setattr(
        audio_analyzer, "transcribe_source",
        lambda *a, **k: TranscriptionOutcome(record=record, reused=True))
    monkeypatch.setattr(audio_analyzer, "run_ffprobe", lambda p: _probe_payload(120))

    llm = FakeLLMService()
    result, method = asyncio.run(analyze_audio_file(
        "/x/short.mp3", llm_service=llm, settings=_Settings(), case_context="诈骗案"))

    content, prompt = llm.analyze_calls[0]
    # 2min audio → band cap 5, reused transcript disclosed
    assert "最多 5 条" in prompt
    assert "来自已存档转写" in content
    assert "[00:00] 把账号发我" in content
    assert "audio_transcript(reused" in method
    assert result["analysis"]["description"].startswith("SUMMARY")


def test_analyze_audio_stt_unavailable_degrades(monkeypatch):
    monkeypatch.setattr(
        audio_analyzer, "transcribe_source",
        lambda *a, **k: TranscriptionOutcome(unavailable_reason="语音识别模型未部署"))
    monkeypatch.setattr(audio_analyzer, "run_ffprobe", lambda p: _probe_payload(60))

    result, method = asyncio.run(analyze_audio_file(
        "/x/a.mp3", llm_service=_NoLLM(), settings=_Settings()))
    assert method == "audio_metadata_only"
    assert "模型未部署" in result["analysis"]["description"]


# ---------------------------------------------------------------------------
# Video soundtrack integration
# ---------------------------------------------------------------------------

def test_video_synthesis_weaves_soundtrack_transcript(monkeypatch, tmp_path):
    from httpserver.services.llm import video_analyzer

    monkeypatch.setattr(video_analyzer, "run_ffprobe", lambda p: {
        "format": {"duration": "15", "bit_rate": "1"},
        "streams": [{"codec_type": "video", "codec_name": "h264",
                     "width": 320, "height": 240}],
    })
    monkeypatch.setattr(video_analyzer.shutil, "which",
                        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(video_analyzer, "_extract_segment_frames",
                        lambda fp, plan, fps, out: [])
    record = {"file_path": "/x/v.mp4", "md5": "", "source": "video-track",
              "status": "complete", "coverage": 0.98, "engine": "sensevoice-small-onnx",
              "language": "zh", "duration_sec": 15,
              "segments": [{"s": 0, "e": 3, "text": "转写句子"}]}
    monkeypatch.setattr(
        audio_analyzer, "transcribe_source",
        lambda *a, **k: TranscriptionOutcome(record=record))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"container")
    llm = FakeLLMService()
    result, method = asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=type("S", (), {
            "llm_video_fps": 1, "llm_video_segment_seconds": 15,
            "llm_video_max_duration": 1800,
        })()))

    content, prompt = llm.analyze_calls[0]
    assert "音轨转写(带时间戳)" in content
    assert "[00:00] 转写句子" in content
    assert "交叉印证" in prompt
    assert "audio_transcript(coverage=0.98)" in method
    assert method.startswith("video_segment_vision(fps=1,segs=1,frames=0)")


def test_video_without_stt_keeps_not_analyzed_note(monkeypatch, tmp_path):
    from httpserver.services.llm import video_analyzer

    monkeypatch.setattr(video_analyzer, "run_ffprobe", lambda p: {
        "format": {"duration": "15", "bit_rate": "1"},
        "streams": [{"codec_type": "video", "codec_name": "h264",
                     "width": 320, "height": 240}],
    })
    monkeypatch.setattr(video_analyzer.shutil, "which",
                        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    monkeypatch.setattr(video_analyzer, "_extract_segment_frames",
                        lambda fp, plan, fps, out: [])
    monkeypatch.setattr(
        audio_analyzer, "transcribe_source",
        lambda *a, **k: TranscriptionOutcome(unavailable_reason="模型未部署"))

    video = tmp_path / "v.mp4"
    video.write_bytes(b"container")
    llm = FakeLLMService()
    asyncio.run(video_analyzer.analyze_video_file(
        str(video), llm_service=llm, settings=type("S", (), {
            "llm_video_fps": 1, "llm_video_segment_seconds": 15,
            "llm_video_max_duration": 1800,
        })()))

    content, prompt = llm.analyze_calls[0]
    assert "音频轨道未分析" in content
    assert "不要臆造任何声音信息" in prompt
