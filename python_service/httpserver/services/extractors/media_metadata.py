"""Media metadata extractors: Audio and video files with content sampling."""
import json
import logging
import os
import subprocess
import tempfile

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        minutes, remainder = divmod(int(seconds), 60)
        return f"{minutes}m {remainder}s"
    hours, remainder = divmod(int(seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def _to_float(value, default=None):
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if converted >= 0 else default


def _format_bitrate(value) -> str:
    bitrate = _to_float(value)
    if bitrate is None:
        return "N/A"
    return f"{int(bitrate) // 1000} kbps"


def _format_frame_rate(value) -> str:
    if value in (None, "", "N/A"):
        return "N/A"
    try:
        numerator, denominator = str(value).split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return "N/A"
        return f"{float(numerator) / denominator_value:.2f}"
    except (TypeError, ValueError):
        return str(value)


def _run_ffprobe(file_path: str) -> dict:
    """Run ffprobe and return its JSON output when available."""
    try:
        completed = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_format", "-show_streams", file_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
        logger.debug("ffprobe unavailable for %s: %s", file_path, error)
        return {}

    if completed.returncode != 0:
        logger.debug("ffprobe failed for %s: %s", file_path, completed.stderr.strip())
        return {}

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        logger.debug("ffprobe returned invalid JSON for %s: %s", file_path, error)
        return {}
    return data if isinstance(data, dict) else {}


@register_extractor
class VideoExtractor(BaseExtractor):
    """Extracts video metadata and optionally creates temporary frame samples."""

    VIDEO_EXTENSIONS = {
        ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm",
        ".m4v", ".mpg", ".mpeg", ".3gp", ".ts",
    }

    def __init__(self, sample_frames: int = 3):
        self.sample_frames = sample_frames

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.VIDEO_EXTENSIONS:
            return f"Error: {ext} is not a recognized video format."
        if not os.path.isfile(file_path):
            return f"Error: Video file not found: {file_path}"

        ffprobe_data = _run_ffprobe(file_path)
        result = [f"# Video File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** {ext.upper()[1:]}")

        if not ffprobe_data:
            result.append("")
            result.append("*ffprobe metadata is unavailable; the file may be unsupported or incomplete.*")
            return "\n".join(result)

        fmt = ffprobe_data.get("format") or {}
        duration = _to_float(fmt.get("duration"))
        if duration is not None and duration > 0:
            result.append(f"**Duration:** {_format_duration(duration)}")
        result.append(f"**Bit Rate:** {_format_bitrate(fmt.get('bit_rate'))}")
        result.append("")

        streams = ffprobe_data.get("streams") or []
        video_streams = [stream for stream in streams if stream.get("codec_type") == "video"]
        audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]

        if video_streams:
            result.append("## Video Streams")
            result.append("| Codec | Resolution | FPS | Bitrate |")
            result.append("| --- | --- | --- | --- |")
            for stream in video_streams:
                codec = stream.get("codec_name", "N/A")
                width = stream.get("width", "N/A")
                height = stream.get("height", "N/A")
                fps = _format_frame_rate(stream.get("r_frame_rate"))
                bitrate = _format_bitrate(stream.get("bit_rate"))
                result.append(f"| {codec} | {width}x{height} | {fps} | {bitrate} |")

        if audio_streams:
            result.append("")
            result.append("## Audio Streams")
            result.append("| Codec | Sample Rate | Channels | Bitrate |")
            result.append("| --- | --- | --- | --- |")
            for stream in audio_streams:
                codec = stream.get("codec_name", "N/A")
                sample_rate = stream.get("sample_rate", "N/A")
                channels = stream.get("channels", "N/A")
                bitrate = _format_bitrate(stream.get("bit_rate"))
                result.append(f"| {codec} | {sample_rate} Hz | {channels} | {bitrate} |")

        tags = fmt.get("tags") or {}
        if tags:
            result.append("")
            result.append("## Tags")
            result.append("| Key | Value |")
            result.append("| --- | --- |")
            for key, value in list(tags.items())[:20]:
                result.append(f"| {key} | {str(value)[:100]} |")

        if self.sample_frames > 0:
            self._append_frame_samples(result, file_path, duration)

        return "\n".join(result)

    def _append_frame_samples(self, result: list[str], file_path: str, duration: float | None) -> None:
        result.append("")
        result.append(f"## Temporary Frame Samples (Up to {self.sample_frames})")
        if duration is None or duration <= 0:
            result.append("*Frame sampling skipped because video duration is unavailable.*")
            return

        tmp_dir = tempfile.mkdtemp(prefix="tracelens_video_samples_")
        sample_cmd = [
            "ffmpeg", "-v", "error", "-i", file_path,
            "-vf", f"fps={self.sample_frames}/{duration:.6f},scale=320:-1",
            "-frames:v", str(self.sample_frames),
            os.path.join(tmp_dir, "frame_%03d.jpg"),
        ]
        try:
            completed = subprocess.run(sample_cmd, capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as error:
            result.append(f"*Frame sampling unavailable: {error}*")
            return

        frames = sorted(
            name for name in os.listdir(tmp_dir) if name.lower().endswith(".jpg")
        )
        if completed.returncode != 0 or not frames:
            result.append("*Could not create frame samples; the video may be incomplete or ffmpeg is unavailable.*")
            return

        result.append(
            f"Created {len(frames)} temporary frame sample(s) in: `{tmp_dir}`"
        )
        result.append("*These derived samples do not validate the source video or its completeness.*")
        for frame in frames:
            frame_path = os.path.join(tmp_dir, frame)
            result.append(f"- `{frame_path}` ({_format_size(os.path.getsize(frame_path))})")


@register_extractor
class AudioExtractor(BaseExtractor):
    """Extracts metadata from audio files."""

    AUDIO_EXTENSIONS = {
        ".mp3", ".wav", ".aac", ".ogg", ".flac", ".wma", ".m4a",
        ".opus", ".aiff", ".ape", ".alac",
    }

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.AUDIO_EXTENSIONS:
            return f"Error: {ext} is not a recognized audio format."

        result = [f"# Audio File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** {ext.upper()[1:]}")

        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(file_path)

            if audio is not None:
                if audio.info:
                    result.append(f"**Duration:** {_format_duration(audio.info.length)}")
                    result.append(f"**Sample Rate:** {audio.info.sample_rate} Hz")
                    result.append(f"**Channels:** {audio.info.channels}")
                    if hasattr(audio.info, "bitrate") and audio.info.bitrate:
                        result.append(f"**Bitrate:** {audio.info.bitrate // 1000} kbps")
                    if hasattr(audio.info, "bits_per_sample") and audio.info.bits_per_sample:
                        result.append(f"**Bit Depth:** {audio.info.bits_per_sample} bit")
                result.append("")

                if audio.tags:
                    result.append("## Tags")
                    result.append("| Key | Value |")
                    result.append("| --- | --- |")
                    for key, value in list(audio.tags.items())[:30]:
                        result.append(f"| {key} | {str(value)[:100]} |")
            else:
                result.append("")
                result.append("*Could not read audio metadata with mutagen.*")
        except ImportError:
            result.append("")
            result.append("*mutagen library not installed. Install for detailed audio metadata.*")
        except Exception as error:
            result.append("")
            result.append(f"*Error reading audio metadata: {error}*")

        ffprobe_data = _run_ffprobe(file_path)
        if ffprobe_data and result[-1].startswith("*"):
            fmt = ffprobe_data.get("format") or {}
            tags = fmt.get("tags") or {}
            if tags:
                result.append("")
                result.append("## Tags (via ffprobe)")
                result.append("| Key | Value |")
                result.append("| --- | --- |")
                for key, value in list(tags.items())[:20]:
                    result.append(f"| {key} | {str(value)[:100]} |")

        return "\n".join(result)
