"""Media metadata extractors: Audio and Video files with content sampling."""
import logging
import os
import subprocess
import json
import tempfile
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024: return f"{size_bytes/1024/1024:.2f} MB"
    else: return f"{size_bytes/1024/1024/1024:.2f} GB"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        m, s = divmod(int(seconds), 60)
        return f"{m}m {s}s"
    else:
        h, remainder = divmod(int(seconds), 3600)
        m, s = divmod(remainder, 60)
        return f"{h}h {m}m {s}s"


def _run_ffprobe(file_path: str) -> dict:
    """Run ffprobe to extract media metadata."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', file_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    return {}


@register_extractor
class VideoExtractor(BaseExtractor):
    """Extracts metadata from video files and optionally samples keyframes."""

    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp', '.ts'}

    def __init__(self, sample_frames: int = 3):
        self.sample_frames = sample_frames

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.VIDEO_EXTENSIONS:
            return f"Error: {ext} is not a recognized video format."

        ffprobe_data = _run_ffprobe(file_path)

        result = [f"# Video File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** {ext.upper()[1:]}")

        if ffprobe_data:
            fmt = ffprobe_data.get('format', {})
            duration = float(fmt.get('duration', 0))
            if duration:
                result.append(f"**Duration:** {_format_duration(duration)}")
            result.append(f"**Bit Rate:** {int(fmt.get('bit_rate', 0)) // 1000} kbps")
            result.append("")

            # Stream info
            streams = ffprobe_data.get('streams', [])
            video_streams = [s for s in streams if s.get('codec_type') == 'video']
            audio_streams = [s for s in streams if s.get('codec_type') == 'audio']

            if video_streams:
                result.append("## Video Streams")
                result.append("| Codec | Resolution | FPS | Bitrate |")
                result.append("| --- | --- | --- | --- |")
                for vs in video_streams:
                    codec = vs.get('codec_name', 'N/A')
                    w = vs.get('width', 'N/A')
                    h = vs.get('height', 'N/A')
                    fps = vs.get('r_frame_rate', 'N/A')
                    if '/' in str(fps):
                        try:
                            num, den = fps.split('/')
                            fps = f"{int(num)/int(den):.2f}"
                        except: pass
                    br = int(vs.get('bit_rate', 0)) // 1000
                    result.append(f"| {codec} | {w}x{h} | {fps} | {br} kbps |")

            if audio_streams:
                result.append("")
                result.append("## Audio Streams")
                result.append("| Codec | Sample Rate | Channels | Bitrate |")
                result.append("| --- | --- | --- | --- |")
                for aus in audio_streams:
                    codec = aus.get('codec_name', 'N/A')
                    sr = aus.get('sample_rate', 'N/A')
                    ch = aus.get('channels', 'N/A')
                    br = int(aus.get('bit_rate', 0)) // 1000
                    result.append(f"| {codec} | {sr} Hz | {ch} | {br} kbps |")

            # Tags
            tags = fmt.get('tags', {})
            if tags:
                result.append("")
                result.append("## Tags")
                result.append("| Key | Value |")
                result.append("| --- | --- |")
                for k, v in list(tags.items())[:20]:
                    result.append(f"| {k} | {str(v)[:100]} |")

            # Keyframe sampling
            if self.sample_frames > 0:
                result.append("")
                result.append(f"## Keyframe Samples (First {self.sample_frames})")
                try:
                    tmp_dir = tempfile.mkdtemp()
                    sample_cmd = [
                        'ffmpeg', '-i', file_path, '-vf',
                        f'select=not(mod(n\,{max(1, int(float(fmt.get("duration", 1)) * 25 / self.sample_frames))})),scale=320:-1',
                        '-vframes', str(self.sample_frames), '-vsync', 'vfr',
                        os.path.join(tmp_dir, 'frame_%03d.jpg')
                    ]
                    subprocess.run(sample_cmd, capture_output=True, timeout=30)

                    frames = sorted([f for f in os.listdir(tmp_dir) if f.endswith('.jpg')])
                    if frames:
                        result.append(f"Extracted {len(frames)} keyframe(s) to: `{tmp_dir}`")
                        for frame in frames:
                            frame_path = os.path.join(tmp_dir, frame)
                            result.append(f"- `{frame_path}` ({_format_size(os.path.getsize(frame_path))})")
                    else:
                        result.append("*Could not extract keyframes (ffmpeg may not be available)*")
                except Exception as e:
                    result.append(f"*Keyframe extraction failed: {e}*")
        else:
            result.append("")
            result.append("*ffprobe not available. Install ffmpeg for detailed media analysis.*")

        return "\n".join(result)


@register_extractor
class AudioExtractor(BaseExtractor):
    """Extracts metadata from audio files."""

    AUDIO_EXTENSIONS = {'.mp3', '.wav', '.aac', '.ogg', '.flac', '.wma', '.m4a', '.opus', '.aiff', '.ape', '.alac'}

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.AUDIO_EXTENSIONS:
            return f"Error: {ext} is not a recognized audio format."

        result = [f"# Audio File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** {ext.upper()[1:]}")

        # Try mutagen for metadata
        try:
            from mutagen import File as MutagenFile
            audio = MutagenFile(file_path)

            if audio is not None:
                if audio.info:
                    result.append(f"**Duration:** {_format_duration(audio.info.length)}")
                    result.append(f"**Sample Rate:** {audio.info.sample_rate} Hz")
                    result.append(f"**Channels:** {audio.info.channels}")
                    if hasattr(audio.info, 'bitrate') and audio.info.bitrate:
                        result.append(f"**Bitrate:** {audio.info.bitrate // 1000} kbps")
                    if hasattr(audio.info, 'bits_per_sample') and audio.info.bits_per_sample:
                        result.append(f"**Bit Depth:** {audio.info.bits_per_sample} bit")
                result.append("")

                # Tags
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
        except Exception as e:
            result.append("")
            result.append(f"*Error reading audio metadata: {e}*")

        # Fallback to ffprobe
        ffprobe_data = _run_ffprobe(file_path)
        if ffprobe_data and not result[-1].startswith('*'):
            pass  # mutagen already handled it
        elif ffprobe_data:
            fmt = ffprobe_data.get('format', {})
            tags = fmt.get('tags', {})
            if tags:
                result.append("")
                result.append("## Tags (via ffprobe)")
                result.append("| Key | Value |")
                result.append("| --- | --- |")
                for k, v in list(tags.items())[:20]:
                    result.append(f"| {k} | {str(v)[:100]} |")

        return "\n".join(result)
