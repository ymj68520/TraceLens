"""Image metadata extractors: HEIC, RAW, SVG, ICO, AVIF."""
import logging
import os
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


@register_extractor
class HeicExtractor(BaseExtractor):
    """Extracts EXIF metadata from HEIC/HEIF image files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS
        except ImportError:
            return "Error: Pillow is not installed."

        try:
            try:
                import pillow_heif
                pillow_heif.register_heif_opener()
            except ImportError:
                pass

            img = Image.open(file_path)
            result = [f"# HEIC/HEIF Image: `{os.path.basename(file_path)}`"]
            result.append(f"**Dimensions:** {img.width} x {img.height}")
            result.append(f"**Format:** {img.format}")
            result.append(f"**Mode:** {img.mode}")
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            exif = img.getexif()
            if exif:
                result.append("## EXIF Metadata")
                result.append("| Tag | Value |")
                result.append("| --- | --- |")
                for tag_id, value in exif.items():
                    tag_name = TAGS.get(tag_id, f"Tag_{tag_id}")
                    if isinstance(value, bytes):
                        value = value[:50].hex()
                    elif isinstance(value, (tuple, list)) and len(value) > 5:
                        value = str(value[:5]) + "..."
                    result.append(f"| {tag_name} | {str(value)[:100]} |")
            else:
                result.append("*No EXIF metadata found.*")

            img.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse HEIC/HEIF file: {e}"


@register_extractor
class RawImageExtractor(BaseExtractor):
    """Extracts metadata from RAW camera images (CR2, NEF, ARW, DNG, etc.)."""

    RAW_EXTENSIONS = {'.cr2', '.cr3', '.nef', '.arw', '.dng', '.orf', '.rw2', '.raf', '.pef', '.srw'}

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import rawpy
        except ImportError:
            return "Error: rawpy library is not installed."

        try:
            raw = rawpy.imread(file_path)
            result = [f"# RAW Image: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Extract basic info
            result.append("## RAW Properties")
            result.append("| Property | Value |")
            result.append("| --- | --- |")

            try:
                sizes = raw.sizes
                result.append(f"| Width | {sizes.width} |")
                result.append(f"| Height | {sizes.height} |")
                result.append(f"| Raw Width | {sizes.raw_width} |")
                result.append(f"| Raw Height | {sizes.raw_height} |")
            except Exception:
                pass

            try:
                result.append(f"| Color Description | {raw.color_desc} |")
            except Exception:
                pass

            try:
                result.append(f"| Number of Colors | {raw.num_colors} |")
            except Exception:
                pass

            raw.close()

            # Try to get EXIF via Pillow
            try:
                from PIL import Image
                from PIL.ExifTags import TAGS
                img = Image.open(file_path)
                exif = img.getexif()
                if exif:
                    result.append("")
                    result.append("## EXIF Metadata")
                    result.append("| Tag | Value |")
                    result.append("| --- | --- |")
                    for tag_id, value in list(exif.items())[:30]:
                        tag_name = TAGS.get(tag_id, f"Tag_{tag_id}")
                        result.append(f"| {tag_name} | {str(value)[:100]} |")
                img.close()
            except Exception:
                pass

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse RAW image: {e}"


@register_extractor
class SvgExtractor(BaseExtractor):
    """Extracts text content from SVG (Scalable Vector Graphics) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed. Install with: pip install defusedxml"

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            ns = {'svg': 'http://www.w3.org/2000/svg'}

            result = [f"# SVG Image: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

            # Extract viewBox
            viewBox = root.get('viewBox', '')
            if viewBox:
                result.append(f"**ViewBox:** {viewBox}")

            width = root.get('width', '')
            height = root.get('height', '')
            if width and height:
                result.append(f"**Dimensions:** {width} x {height}")
            result.append("")

            # Extract text elements
            texts = []
            for elem in root.iter():
                if elem.tag.endswith('}text') or elem.tag == 'text':
                    if elem.text and elem.text.strip():
                        texts.append(elem.text.strip())
                # Also check tspan
                if elem.tag.endswith('}tspan') or elem.tag == 'tspan':
                    if elem.text and elem.text.strip():
                        texts.append(elem.text.strip())

            if texts:
                result.append("## Text Content")
                for t in texts[:100]:
                    result.append(f"- {t}")
                if len(texts) > 100:
                    result.append(f"\n*(Showing first 100 of {len(texts)} text elements)*")
            else:
                result.append("*No text elements found in SVG.*")

            # Extract metadata
            desc = root.find('.//{http://www.w3.org/2000/svg}desc')
            title = root.find('.//{http://www.w3.org/2000/svg}title')
            if desc is not None and desc.text:
                result.append("")
                result.append(f"## Description\n{desc.text}")
            if title is not None and title.text:
                result.append("")
                result.append(f"## Title\n{title.text}")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse SVG file: {e}"


@register_extractor
class IcoExtractor(BaseExtractor):
    """Extracts metadata from ICO (icon) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from PIL import Image
        except ImportError:
            return "Error: Pillow is not installed."

        try:
            # Read ICO header
            with open(file_path, 'rb') as f:
                header = f.read(6)

            import struct
            _, _, count = struct.unpack('<HHH', header)

            result = [f"# ICO File: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Icon Count:** {count}")
            result.append("")

            # List each icon
            result.append("## Icons")
            result.append("| # | Size | Colors |")
            result.append("| --- | --- | --- |")

            with open(file_path, 'rb') as f:
                f.seek(6)
                for i in range(min(count, 50)):
                    entry = f.read(16)
                    if len(entry) < 16:
                        break
                    w, h, colors, _, planes, bpp, size, offset = struct.unpack('<BBBBHHII', entry)
                    width = w if w != 0 else 256
                    height = h if h != 0 else 256
                    result.append(f"| {i + 1} | {width}x{height} | {colors or 'N/A'} |")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ICO file: {e}"


@register_extractor
class AvifExtractor(BaseExtractor):
    """Extracts metadata from AVIF image files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from PIL import Image
            from PIL.ExifTags import TAGS
        except ImportError:
            return "Error: Pillow is not installed."

        try:
            img = Image.open(file_path)
            result = [f"# AVIF Image: `{os.path.basename(file_path)}`"]
            result.append(f"**Dimensions:** {img.width} x {img.height}")
            result.append(f"**Format:** {img.format}")
            result.append(f"**Mode:** {img.mode}")
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            exif = img.getexif()
            if exif:
                result.append("## EXIF Metadata")
                result.append("| Tag | Value |")
                result.append("| --- | --- |")
                for tag_id, value in list(exif.items())[:30]:
                    tag_name = TAGS.get(tag_id, f"Tag_{tag_id}")
                    result.append(f"| {tag_name} | {str(value)[:100]} |")

            img.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse AVIF file: {e}"
