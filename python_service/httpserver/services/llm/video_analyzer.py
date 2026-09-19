"""Video content analysis: segment sampling + multi-image vision + synthesis.

Design (2026-09-19, agreed with the requester):
- NO content-blind frame cap. The whole duration (below the too-long cap) is
  covered by sampling frames at a fixed density (``LLM_VIDEO_FPS``); density
  is a budget dial, not an evidence cut.
- Each ``LLM_VIDEO_SEGMENT_SECONDS`` window is described with ONE multi-image
  vision call; segments are strictly serial.
- A final text pass synthesizes metadata + per-segment timeline notes into the
  video's final description.
- Videos longer than ``LLM_VIDEO_MAX_DURATION_SEC`` (default 30min) get a
  metadata-only description marked for future backfill.
- The audio track is NOT analyzed in this round; every description says so.
- Frames are transient processing aids (D4b): extracted into a scratch dir,
  read into memory, removed in ``finally``; scratch paths never appear in the
  returned text.
- Raw video bytes are NEVER sent to any text model.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Shared extension list so routing stays consistent with the metadata
# extractor's (extractor_mapping.json routes the same set to VideoExtractor).
from ..extractors.media_metadata import VideoExtractor, run_ffprobe

VIDEO_EXTENSIONS = frozenset(VideoExtractor.VIDEO_EXTENSIONS)

_FRAME_SCALE = "320:-1"        # same sample geometry as VideoExtractor
_FFMPEG_TIMEOUT = 90           # per-segment frame extraction
_EMPTY_RETRIES = 2             # nemotron empty-content retries per segment
_SEGMENT_DESC_LIMIT = 1200     # chars of each segment note kept for synthesis
_FFMPEG_MISSING = "*视频内容分析不可用:主机未安装 ffmpeg,仅完成元数据分析。*"


@dataclass
class SegmentPlan:
    """One logical time window; frames are extracted per window."""

    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def plan_segments(duration: float, segment_seconds: int) -> List[SegmentPlan]:
    """Split ``duration`` into serial windows (pure, unit-tested)."""
    if duration <= 0:
        return []
    if segment_seconds <= 0:
        segment_seconds = 15
    plans: List[SegmentPlan] = []
    start = 0.0
    while start < duration - 1e-6:
        step = min(float(segment_seconds), duration - start)
        plans.append(SegmentPlan(start=round(start, 3), duration=round(step, 3)))
        start += step
    return plans


def _format_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def _metadata_markdown(file_path: str, ffprobe_data: dict) -> str:
    """Compact ffprobe summary used as synthesis input (and skip-path text)."""
    ext = os.path.splitext(file_path)[1].lower().lstrip(".").upper() or "?"
    lines = [f"文件: {os.path.basename(file_path)}", f"封装格式: {ext}"]
    try:
        lines.append(f"大小: {os.path.getsize(file_path) / 1024 / 1024:.1f} MB")
    except OSError:
        pass

    fmt = (ffprobe_data or {}).get("format") or {}
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    if duration > 0:
        lines.append(f"时长: {_format_duration(duration)}")
    try:
        lines.append(f"总码率: {int(fmt.get('bit_rate')) // 1000} kbps")
    except (TypeError, ValueError):
        pass

    for stream in fmt.get("streams") or []:
        if stream.get("codec_type") == "video":
            lines.append(
                f"视频流: {stream.get('codec_name', '?')} "
                f"{stream.get('width', '?')}x{stream.get('height', '?')}"
            )
        elif stream.get("codec_type") == "audio":
            lines.append(
                f"音频流: {stream.get('codec_name', '?')} {stream.get('channels', '?')}ch"
            )
    return "\n".join(lines)


def _segment_prompt(index: int, total: int, plan: SegmentPlan, fps: int, case_context: str) -> str:
    ctx = f"\n案情背景（用于聚焦取证关注点）: {case_context}\n" if case_context else ""
    return (
        f"这是同一段视频按时间顺序的第 {index}/{total} 段连续抽帧"
        f"（时间 {plan.start:.0f}s–{plan.end:.0f}s，每 {1 / fps:.0f} 秒一帧）。"
        f"{ctx}"
        "请输出本段时间线描述：画面内容、出现的文字/界面/文档、人物与设备、"
        "时间戳或位置线索、可疑迹象。按时间顺序分点，不要使用 markdown 标记。"
    )


def _synthesis_prompt(video_name: str, case_context: str, user_prompt: str,
                      has_audio_transcript: bool = False) -> str:
    ctx = f"\n案情背景: {case_context}\n" if case_context else ""
    extra = f"\n分析人员补充要求: {user_prompt}\n" if user_prompt else ""
    audio_note = (
        "请按时间线整合画面描述与音轨转写,交叉印证时间点与事件。\n\n"
        if has_audio_transcript else
        "注意:音频轨道未做分析,描述中不要臆造任何声音信息。\n\n"
    )
    return (
        f"你是资深数字取证分析师。以下是对视频“{video_name}”的逐段时间线描述与文件元数据。"
        f"{ctx}{extra}"
        "请综合全部信息给出该视频的最终取证分析，严格按以下格式输出：\n"
        "SUMMARY: 2-3 句概括视频整体内容与取证价值\n"
        "DESCRIPTION: 结构化最终描述——先整体叙述，再按时间线归纳各段要点，"
        "列出画面中出现的文字、账号、设备、位置等关键证据线索\n"
        "KEYWORDS: 逗号分隔的关键词\n\n"
        f"{audio_note}"
    )


def _metadata_only_result(
    file_path: str, ffprobe_data: dict, reason: str
) -> Tuple[Dict[str, Any], str]:
    """No-content-analysis fallback (too long / no ffmpeg / unreadable)."""
    text = _metadata_markdown(file_path, ffprobe_data)
    text += f"\n\n{reason}\n音频轨道未分析。"
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
        "video_metadata_only",
    )


def _extract_segment_frames(
    file_path: str, plan: SegmentPlan, fps: int, out_dir: str
) -> List[str]:
    """Decode one segment's frames to ``out_dir``; returns sorted paths (sync)."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-ss", f"{plan.start:.3f}", "-t", f"{plan.duration:.3f}",
        "-i", file_path,
        "-vf", f"fps={fps},scale={_FRAME_SCALE}",
        "-frames:v", str(int(plan.duration * fps) + 1),
        os.path.join(out_dir, "frame_%04d.jpg"),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed: {completed.stderr.strip()[:200]}")
    return sorted(
        os.path.join(out_dir, name)
        for name in os.listdir(out_dir)
        if name.lower().endswith(".jpg")
    )


async def _describe_segment(
    file_path: str,
    plan: SegmentPlan,
    index: int,
    total: int,
    fps: int,
    case_context: str,
    llm_service,
    tmp_root: str,
) -> Tuple[str, int]:
    """Extract frames for one segment and describe them with ONE vision call.

    Returns ``(timeline_note, frames_used)``. The note is never empty —
    failures degrade to an explicit per-segment marker so synthesis still
    sees full coverage and honest gaps.
    """
    header = f"### 第 {index}/{total} 段（{plan.start:.0f}s–{plan.end:.0f}s）"
    out_dir = os.path.join(tmp_root, f"seg_{index:03d}")
    os.makedirs(out_dir, exist_ok=True)

    try:
        frame_paths = await asyncio.to_thread(
            _extract_segment_frames, file_path, plan, fps, out_dir
        )
    except Exception as exc:
        logger.warning(f"[VIDEO_ANALYZER] segment {index} frame extraction failed: {exc}")
        return f"{header}\n(本段抽帧失败: {exc})", 0

    frame_bytes: List[bytes] = []
    for frame_path in frame_paths:
        try:
            with open(frame_path, "rb") as handle:
                frame_bytes.append(handle.read())
        except OSError:
            continue
    if not frame_bytes:
        return f"{header}\n(本段无可解码帧)", 0

    prompt = _segment_prompt(index, total, plan, fps, case_context)
    description = ""
    last_error = ""
    for _attempt in range(1, _EMPTY_RETRIES + 1):
        try:
            result = await llm_service.analyze_images(
                image_data_list=frame_bytes, prompt=prompt
            )
        except Exception as exc:
            last_error = f"调用失败: {exc}"
            logger.warning(f"[VIDEO_ANALYZER] segment {index} vision call failed: {exc}")
            continue
        description = (result.get("analysis", {}).get("description") or "").strip()
        if description:
            break
        last_error = "模型返回空内容"

    if not description:
        return f"{header}\n(本段视觉分析未成功: {last_error})", len(frame_bytes)

    if len(description) > _SEGMENT_DESC_LIMIT:
        description = description[:_SEGMENT_DESC_LIMIT] + "…(截断)"
    return f"{header}\n{description}", len(frame_bytes)


async def analyze_video_file(
    file_path: str,
    *,
    llm_service,
    settings=None,
    fps: Optional[int] = None,
    segment_seconds: Optional[int] = None,
    max_duration: Optional[int] = None,
    case_context: str = "",
    user_prompt: str = "",
    files_db_path: str = "",
    task_id: str = "",
    trigger_source: str = "pipeline",
) -> Tuple[Dict[str, Any], str]:
    """Analyze one video end-to-end. Returns ``(result, extraction_method)``.

    ``result`` matches the shape returned by ``llm_service.analyze`` so both
    wiring points (interactive /api/llm/analyze and the case-analysis batch)
    can persist it unchanged. ``extraction_method`` records provenance, e.g.
    ``video_segment_vision(fps=1,segs=4,frames=52)``; the metadata-only skip
    path returns ``video_metadata_only``. The soundtrack is transcribed via
    the audio analyzer and woven into the synthesis input when available.
    """
    if settings is None:
        from ...config import get_settings
        settings = get_settings()
    fps = int(fps or settings.llm_video_fps)
    segment_seconds = int(segment_seconds or settings.llm_video_segment_seconds)
    max_duration = settings.llm_video_max_duration if max_duration is None else int(max_duration)

    ffprobe_data = run_ffprobe(file_path)
    fmt = ffprobe_data.get("format") or {}
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        duration = 0.0

    if max_duration and duration > max_duration:
        logger.info(
            f"[VIDEO_ANALYZER] {file_path} duration {duration:.0f}s exceeds cap "
            f"{max_duration}s — metadata-only, left for future backfill"
        )
        return _metadata_only_result(
            file_path,
            ffprobe_data,
            f"*该视频时长 {_format_duration(duration)} 超过当前分析上限 "
            f"({_format_duration(max_duration)}),本次未做内容级分析,留待后续补齐。*",
        )

    if shutil.which("ffmpeg") is None:
        return _metadata_only_result(file_path, ffprobe_data, _FFMPEG_MISSING)

    plans = plan_segments(duration, segment_seconds)
    if not plans:
        return _metadata_only_result(
            file_path, ffprobe_data, "*无法读取视频时长,未做内容级分析。*"
        )

    # Soundtrack transcription (same STT path as standalone audio); when the
    # engine is unavailable the description keeps the explicit "未分析" note.
    from .audio_analyzer import transcribe_source

    outcome = await asyncio.to_thread(
        transcribe_source, file_path,
        settings=settings, source="video-track",
        files_db_path=files_db_path, task_id=task_id,
        trigger_source=trigger_source,
    )

    # Serial segment loop (agreed design): one multi-image call per segment,
    # ffmpeg decoding off-loaded to a worker thread, LLM calls on the loop.
    segment_notes: List[str] = []
    frames_used = 0
    tmp_root = tempfile.mkdtemp(prefix="tracelens_video_frames_")
    try:
        for index, plan in enumerate(plans, start=1):
            note, frames = await _describe_segment(
                file_path, plan, index, len(plans), fps,
                case_context, llm_service, tmp_root,
            )
            segment_notes.append(note)
            frames_used += frames
            logger.info(
                f"[VIDEO_ANALYZER] segment {index}/{len(plans)} done "
                f"({frames} frames, note {len(note)} chars)"
            )
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    metadata_text = _metadata_markdown(file_path, ffprobe_data)
    timeline = "\n\n".join(segment_notes)
    if outcome.record is not None:
        from .audio_analyzer import _disclosure, _timeline_block

        audio_block = (
            f"{_disclosure(outcome.record, outcome.reused)}\n\n"
            f"=== 音轨转写(带时间戳)===\n{_timeline_block(outcome.record)}"
        )
        audio_method = (
            f"+audio_transcript(coverage={float(outcome.record.get('coverage', 0.0)):.2f})"
        )
    else:
        audio_block = "音频轨道未分析。"
        audio_method = ""
    content = (
        f"{metadata_text}\n\n"
        f"抽帧密度: {fps} 帧/秒,共 {len(plans)} 段。{audio_block}\n\n"
        f"=== 各段画面时间线描述 ===\n{timeline}"
    )
    result = await llm_service.analyze(
        content=content,
        model_type="text",
        prompt=_synthesis_prompt(
            os.path.basename(file_path), case_context, user_prompt,
            has_audio_transcript=outcome.record is not None,
        ),
    )

    method = (
        f"video_segment_vision(fps={fps},segs={len(plans)},frames={frames_used})"
        f"{audio_method}"
    )
    return result, method
