"""Audio content analysis: SenseVoice STT + timeline synthesis.

Design (2026-09-19, agreed):
- Engine: SenseVoice-small ONNX via sherpa-onnx on CPU, silero VAD chunking,
  serial decode (local batch decode keeps order).
- Duration cap: LLM_AUDIO_MAX_DURATION_SEC (default 60min). Longer audio
  gets a ``pending_backfill`` transcript row (coverage 0, note with the
  reason) plus a metadata-only description — backfill is a query later.
- Full transcripts live in the task files DB ``audio_transcripts`` table
  (append-only, latest-wins); ``llm_description`` carries the analysis plus
  duration-banded key excerpts (5/10/15/20 by length), never full text.
- A complete transcript row is reused for synthesis without re-running STT.
- The raw audio bytes are NEVER sent to any model — the transcript is text.
- Video soundtracks go through the same STT path (``source='video-track'``)
  and the transcript becomes part of the video's synthesis input.
"""

import asyncio
import hashlib
import logging
import os
import shutil
import struct
import subprocess
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

from ..extractors.media_metadata import AudioExtractor, run_ffprobe

AUDIO_EXTENSIONS = frozenset(AudioExtractor.AUDIO_EXTENSIONS)

_SAMPLE_RATE = 16000
_VAD_WINDOW = 1600                      # 0.1s feed window
_DECODE_BATCH = 8                       # local CPU batch decode (order kept)
_TIMELINE_LIMIT = 60000                 # chars of transcript fed to synthesis
_ENGINE_NAME = "sensevoice-small-onnx"

_EXCERPT_BANDS = (                      # (duration_sec upper bound, excerpt cap)
    (5 * 60, 5),
    (20 * 60, 10),
    (45 * 60, 15),
    (float("inf"), 20),
)


def excerpt_cap(duration_sec: float) -> int:
    """Key-excerpt cap in the final description, banded by duration (agreed)."""
    for upper, cap in _EXCERPT_BANDS:
        if duration_sec <= upper:
            return cap
    return 20


def _format_clock(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _file_md5(file_path: str) -> str:
    digest = hashlib.md5()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _model_dir(settings) -> Optional[str]:
    """Locate the STT model dir (SenseVoice + silero VAD), None if absent."""
    candidates = []
    if getattr(settings, "audio_stt_model_dir", ""):
        candidates.append(settings.audio_stt_model_dir)
    default_dir = Path(__file__).resolve().parents[3] / "models" / "audio"
    candidates.append(str(default_dir))
    for candidate in candidates:
        inner = Path(candidate) / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17"
        for base in (inner, Path(candidate)):
            if (base / "model.int8.onnx").is_file() and (base / "tokens.txt").is_file():
                return str(base)
    return None


class _SttEngine:
    """Lazy process-wide SenseVoice + VAD singleton."""

    def __init__(self, model_dir: str):
        import sherpa_onnx

        self.name = _ENGINE_NAME
        self.recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=os.path.join(model_dir, "model.int8.onnx"),
            tokens=os.path.join(model_dir, "tokens.txt"),
            use_itn=True,
            num_threads=4,
        )
        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = self._find_vad(model_dir)
        vad_config.silero_vad.threshold = 0.5
        vad_config.silero_vad.min_silence_duration = 0.5
        vad_config.sample_rate = _SAMPLE_RATE
        self.vad_config = vad_config

    @staticmethod
    def _find_vad(model_dir: str) -> str:
        for candidate in (
            os.path.join(model_dir, "silero_vad.onnx"),
            os.path.join(os.path.dirname(model_dir), "silero_vad.onnx"),
        ):
            if os.path.isfile(candidate):
                return candidate
        raise FileNotFoundError(f"silero_vad.onnx not found near {model_dir}")


_engine: Optional[_SttEngine] = None


def _get_engine(model_dir: str) -> _SttEngine:
    global _engine
    if _engine is None:
        _engine = _SttEngine(model_dir)
    return _engine


def extract_audio_track(video_path: str, out_wav: str) -> None:
    """Decode a video's soundtrack to 16k mono wav (video stream skipped)."""
    cmd = [
        "ffmpeg", "-v", "error", "-i", video_path,
        "-vn", "-ac", "1", "-ar", str(_SAMPLE_RATE), "-y", out_wav,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError(f"audio track extraction failed: {completed.stderr.strip()[:200]}")


def _decode_to_wav(file_path: str, out_wav: str) -> None:
    cmd = [
        "ffmpeg", "-v", "error", "-i", file_path,
        "-ac", "1", "-ar", str(_SAMPLE_RATE), "-y", out_wav,
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError(f"audio decode failed: {completed.stderr.strip()[:200]}")


def _read_wav_float32(path: str) -> List[float]:
    with wave.open(path, "rb") as handle:
        assert handle.getframerate() == _SAMPLE_RATE, "expected 16kHz wav"
        frames = handle.readframes(handle.getnframes())
    count = len(frames) // 2
    samples = struct.unpack(f"<{count}h", frames[: count * 2])
    return [sample / 32768.0 for sample in samples]


def _detect_speech_segments(engine: _SttEngine, samples: List[float]):
    """VAD segmentation; returns [(start_sec, samples), ...] (serial feed)."""
    import sherpa_onnx

    vad = sherpa_onnx.VoiceActivityDetector(engine.vad_config, buffer_size_in_seconds=120)
    found = []
    for i in range(0, len(samples), _VAD_WINDOW):
        vad.accept_waveform(samples[i : i + _VAD_WINDOW])
        while not vad.empty():
            segment = vad.front
            found.append((segment.start / _SAMPLE_RATE, segment.samples))
            vad.pop()
    vad.flush()
    while not vad.empty():
        segment = vad.front
        found.append((segment.start / _SAMPLE_RATE, segment.samples))
        vad.pop()
    return found


def _flush_decode(engine: _SttEngine, streams, metas) -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []
    try:
        engine.recognizer.decode_streams(streams)
        for (start_sec, dur), stream in zip(metas, streams):
            text = (stream.result.text or "").strip()
            entries.append({"s": round(start_sec, 2), "e": round(start_sec + dur, 2), "text": text})
    except Exception as exc:
        logger.warning(f"[AUDIO_ANALYZER] batch decode failed: {exc}")
        for start_sec, dur in metas:
            entries.append({
                "s": round(start_sec, 2), "e": round(start_sec + dur, 2),
                "text": "(本段转写失败)", "failed": True,
            })
    return entries


def _decode_segments(engine: _SttEngine, segments) -> List[Dict[str, Any]]:
    """Decode VAD segments to timeline entries; batch-decoded, order kept.

    A decoding failure degrades that one segment to an explicit marker —
    coverage accounting stays honest.
    """
    out: List[Dict[str, Any]] = []
    streams, metas = [], []
    for start_sec, chunk in segments:
        stream = engine.recognizer.create_stream()
        stream.accept_waveform(_SAMPLE_RATE, chunk)
        streams.append(stream)
        metas.append((start_sec, len(chunk) / _SAMPLE_RATE))
        if len(streams) >= _DECODE_BATCH:
            out.extend(_flush_decode(engine, streams, metas))
            streams, metas = [], []
    if streams:
        out.extend(_flush_decode(engine, streams, metas))
    return out


def transcribe_wav(
    wav_path: str, engine: _SttEngine, duration_sec: float
) -> Tuple[List[Dict[str, Any]], str, float]:
    """Transcribe one 16k mono wav. Returns (segments, language, transcribed_sec)."""
    samples = _read_wav_float32(wav_path)
    vad_segments = _detect_speech_segments(engine, samples)
    entries = _decode_segments(engine, vad_segments)

    transcribed_sec = 0.0
    for entry in entries:
        if entry.get("failed") or not entry.get("text"):
            continue
        transcribed_sec += entry["e"] - entry["s"]
    return entries, ("zh" if entries else ""), transcribed_sec


@dataclass
class TranscriptionOutcome:
    """STT result for one media file.

    ``record`` is a transcript record dict (complete/partial/pending_backfill)
    when a row exists or was produced; ``None`` means STT was unavailable
    (``unavailable_reason`` says why) and nothing was persisted.
    """

    record: Optional[Dict[str, Any]] = None
    unavailable_reason: str = ""
    reused: bool = field(default=False)


def transcribe_source(
    file_path: str,
    *,
    settings=None,
    source: str = "audio",
    files_db_path: str = "",
    task_id: str = "",
    trigger_source: str = "pipeline",
) -> TranscriptionOutcome:
    """STT pipeline for one file (standalone audio or a video's soundtrack).

    Sync (CPU-bound ffmpeg + onnx); callers wrap in ``asyncio.to_thread``.
    Persists the transcript row when ``files_db_path`` is given.
    """
    if settings is None:
        from ...config import get_settings
        settings = get_settings()

    md5 = ""
    try:
        md5 = _file_md5(file_path)
    except OSError:
        pass

    if files_db_path:
        from .audio_transcript_store import ensure_audio_transcript_schema, latest_transcript

        ensure_audio_transcript_schema(files_db_path)
        existing = latest_transcript(files_db_path, file_path, md5=md5, source=source)
        if existing and existing.get("status") == "complete" and existing.get("segments"):
            outcome = TranscriptionOutcome(reused=True)
            outcome.record = existing
            return outcome

    fmt = run_ffprobe(file_path).get("format") or {}
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0

    max_duration = settings.llm_audio_max_duration
    if max_duration and duration > max_duration:
        note = f"时长 {_format_clock(duration)} 超过上限 {_format_clock(max_duration)},待补齐"
        record = _base_record(
            file_path, md5, source, task_id, trigger_source,
            duration_sec=duration, transcribed_sec=0.0, coverage=0.0,
            status="pending_backfill", note=note,
        )
        if files_db_path:
            _persist(files_db_path, record)
        return TranscriptionOutcome(record=record)

    model_dir = _model_dir(settings)
    if model_dir is None:
        return TranscriptionOutcome(unavailable_reason="语音识别模型未部署(AUDIO_STT_MODEL_DIR)")

    tmp_dir = tempfile.mkdtemp(prefix="tracelens_audio_")
    try:
        wav_path = os.path.join(tmp_dir, "input.wav")
        try:
            if source == "video-track":
                extract_audio_track(file_path, wav_path)
            else:
                _decode_to_wav(file_path, wav_path)
        except RuntimeError as exc:
            return TranscriptionOutcome(unavailable_reason=str(exc))

        engine = _get_engine(model_dir)
        segments, language, transcribed_sec = transcribe_wav(wav_path, engine, duration)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    coverage = (transcribed_sec / duration) if duration > 0 else 0.0
    status = "complete" if duration > 0 and coverage >= 0.95 else "partial"
    failed_count = sum(1 for entry in segments if entry.get("failed"))
    note_bits = []
    if failed_count:
        note_bits.append(f"{failed_count} 段转写失败")
    if duration > 0 and coverage < 0.95:
        note_bits.append(f"未覆盖 {_format_clock(max(0.0, duration - transcribed_sec))}(可能为静音/环境音)")

    record = _base_record(
        file_path, md5, source, task_id, trigger_source,
        language=language, engine=engine.name,
        duration_sec=duration, transcribed_sec=round(transcribed_sec, 2),
        coverage=round(coverage, 4), status=status,
        note=";".join(note_bits),
        segments=segments,
        full_text="\n".join(str(entry.get("text", "")) for entry in segments if entry.get("text")),
    )
    if files_db_path:
        _persist(files_db_path, record)
    return TranscriptionOutcome(record=record)


def _base_record(
    file_path: str, md5: str, source: str, task_id: str, trigger_source: str,
    **over: Any,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "file_path": file_path,
        "md5": md5,
        "source": source,
        "trigger_source": trigger_source,
        "created_at": int(time.time()),
        **over,
    }


def _persist(db_path: str, record: Dict[str, Any]) -> None:
    from .audio_transcript_store import ensure_audio_transcript_schema, save_transcript

    try:
        ensure_audio_transcript_schema(db_path)
        save_transcript(db_path, record)
    except Exception as exc:
        logger.warning(f"[AUDIO_ANALYZER] transcript persist failed for {record.get('file_path')}: {exc}")


def _metadata_markdown(file_path: str, ffprobe_data: dict) -> str:
    fmt = (ffprobe_data or {}).get("format") or {}
    ext = os.path.splitext(file_path)[1].lower().lstrip(".").upper() or "?"
    lines = [f"文件: {os.path.basename(file_path)}", "类型: 音频", f"封装格式: {ext}"]
    try:
        lines.append(f"大小: {os.path.getsize(file_path) / 1024 / 1024:.1f} MB")
    except OSError:
        pass
    try:
        duration = float(fmt.get("duration"))
        if duration > 0:
            lines.append(f"时长: {_format_clock(duration)}")
    except (TypeError, ValueError):
        pass
    for stream in fmt.get("streams") or []:
        if stream.get("codec_type") == "audio":
            lines.append(
                f"音频流: {stream.get('codec_name', '?')} "
                f"{stream.get('sample_rate', '?')}Hz {stream.get('channels', '?')}ch"
            )
    return "\n".join(lines)


def _metadata_only_result(
    file_path: str, ffprobe_data: dict, reason: str
) -> Tuple[Dict[str, Any], str]:
    """Fallback with no STT content."""
    text = _metadata_markdown(file_path, ffprobe_data)
    text += f"\n\n{reason}\n"
    return (
        {
            "analysis": {
                "description": text,
                "summary": text.split("\n")[0],
                "keywords": [],
                "value": "",
                "model_type": "metadata_only",
            },
            "model": "metadata_only",
            "tokens_used": 0,
        },
        "audio_metadata_only",
    )


def _disclosure(record: Dict[str, Any], reuse: bool) -> str:
    status = record.get("status", "complete")
    coverage_pct = f"{float(record.get('coverage', 0.0)) * 100:.0f}%"
    base = (
        f"[转写存档:segments={len(record.get('segments', []))},"
        f"语言={record.get('language') or 'unknown'},"
        f"覆盖 {coverage_pct},引擎 {record.get('engine') or 'unknown'}"
    )
    if status == "pending_backfill":
        return f"[转写存档:{record.get('note') or '待补齐'}]"
    if status == "complete":
        return base + (",来自已存档转写]" if reuse else "]")
    extras = [record.get("note")] if record.get("note") else []
    extras.append("待补齐")
    return base + (";" + ";".join(extras) if any(extras) else "") + "]"


def _synthesis_prompt(file_name: str, cap_value: int, case_context: str, user_prompt: str) -> str:
    ctx = f"\n案情背景: {case_context}\n" if case_context else ""
    extra = f"\n分析人员补充要求: {user_prompt}\n" if user_prompt else ""
    return (
        f"你是资深数字取证分析师。以下是音频文件“{file_name}”的完整带时间戳转写与文件元数据。"
        f"{ctx}{extra}"
        "请综合全部信息给出该音频的最终取证分析,严格按以下格式输出:\n"
        "SUMMARY: 2-3 句概括音频内容与取证价值\n"
        f"DESCRIPTION: 结构化最终描述——内容概述 + 按时间线归纳的关键内容,"
        f"然后单列“关键片段引用”,最多 {cap_value} 条,每条格式 [时间] 一句话原文,"
        "优先选取涉及账号、身份、交易、威胁、时间地点线索的语句\n"
        "KEYWORDS: 逗号分隔的关键词\n\n"
        f"注意:关键片段引用严格不超过 {cap_value} 条;转写之外不要臆造内容。"
    )


def _timeline_block(record: Dict[str, Any]) -> str:
    from .audio_transcript_store import segments_to_timeline

    segments = record.get("segments") or []
    timeline = segments_to_timeline(segments, limit_chars=_TIMELINE_LIMIT)
    if not timeline:
        return "(未检测到可转写语音)"
    return timeline


async def analyze_audio_file(
    file_path: str,
    *,
    llm_service,
    settings=None,
    source: str = "audio",
    case_context: str = "",
    user_prompt: str = "",
    files_db_path: str = "",
    task_id: str = "",
    trigger_source: str = "pipeline",
) -> Tuple[Dict[str, Any], str]:
    """Transcribe + synthesize one audio file (or a video's soundtrack).

    Returns ``(result, extraction_method)`` where ``result`` matches the
    ``llm_service.analyze`` shape. Persists the transcript row when
    ``files_db_path`` is given.
    """
    outcome = await asyncio.to_thread(
        transcribe_source, file_path,
        settings=settings, source=source, files_db_path=files_db_path,
        task_id=task_id, trigger_source=trigger_source,
    )

    ffprobe_data = run_ffprobe(file_path)
    if outcome.record is None:
        reason = outcome.unavailable_reason or "语音识别不可用"
        return _metadata_only_result(file_path, ffprobe_data, f"*{reason}。*")

    record = outcome.record
    if record.get("status") == "pending_backfill":
        return _metadata_only_result(
            file_path, ffprobe_data, f"*{record.get('note') or '本次未转写,留待补齐。'}*"
        )

    content = (
        f"{_metadata_markdown(file_path, ffprobe_data)}\n\n"
        f"{_disclosure(record, outcome.reused)}\n\n"
        f"=== 带时间戳转写 ===\n{_timeline_block(record)}"
    )
    cap_value = excerpt_cap(float(record.get("duration_sec") or 0.0))
    result = await llm_service.analyze(
        content=content,
        model_type="text",
        prompt=_synthesis_prompt(os.path.basename(file_path), cap_value, case_context, user_prompt),
    )
    method = (
        f"audio_transcript({'reused' if outcome.reused else 'stt'},"
        f"engine={record.get('engine') or 'unknown'},"
        f"segments={len(record.get('segments', []))},"
        f"coverage={float(record.get('coverage', 0.0)):.2f})"
    )
    return result, method
