"""Adobe format extractors: PSD (Photoshop), AI (Illustrator), INDD (InDesign)."""
import logging
import os
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# PSD color mode mapping
PSD_COLOR_MODES = {
    0: "Bitmap",
    1: "Grayscale",
    2: "Indexed",
    3: "RGB",
    4: "CMYK",
    7: "Multichannel",
    8: "Duotone",
    9: "Lab",
}

# PSD blend mode signatures to human-readable names
PSD_BLEND_MODES = {
    b"norm": "Normal",
    b"diss": "Dissolve",
    b"dark": "Darken",
    b"mul ": "Multiply",
    b"idiv": "Color Burn",
    b"lbrn": "Linear Burn",
    b"dkCn": "Darker Color",
    b"lite": "Lighten",
    b"scrn": "Screen",
    b"div ": "Color Dodge",
    b"lddg": "Linear Dodge",
    b"lgCl": "Lighter Color",
    b"over": "Overlay",
    b"sLit": "Soft Light",
    b"hLit": "Hard Light",
    b"vLit": "Vivid Light",
    b"lLit": "Linear Light",
    b"pLit": "Pin Light",
    b"hMix": "Hard Mix",
    b"dif ": "Difference",
    b"smud": "Exclusion",
    b"fsub": "Subtract",
    b"fdiv": "Divide",
    b"hue ": "Hue",
    b"sat ": "Saturation",
    b"colr": "Color",
    b"lum ": "Luminosity",
}


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


def _read_psd_string(data: bytes, offset: int) -> tuple:
    """Read a Pascal string (4-byte length-prefixed) from PSD binary data."""
    length = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    if length == 0:
        length = 4  # PSD pads to multiples of 4
    s = data[offset:offset + length].decode("latin-1", errors="replace").rstrip("\x00")
    # Align to multiple of 2 (not 4) for layer records
    offset += length
    if length % 2 != 0:
        offset += 1
    return s, offset


@register_extractor
class PsdExtractor(BaseExtractor):
    """Extracts metadata from Adobe Photoshop (.psd) files.

    Tries psd-tools library first for full layer extraction.
    Falls back to manual binary parsing of the PSD header.
    """

    async def extract_to_markdown(self, file_path: str) -> str:
        # Try psd-tools first
        try:
            return self._extract_with_psd_tools(file_path)
        except ImportError:
            logger.debug("psd-tools not available, falling back to binary parsing")
        except Exception as e:
            logger.debug(f"psd-tools failed ({e}), falling back to binary parsing")

        # Fallback: manual binary parsing
        return self._extract_binary(file_path)

    def _extract_with_psd_tools(self, file_path: str) -> str:
        from psd_tools import PSDImage

        psd = PSDImage.open(file_path)
        result = [f"# PSD Image: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Dimensions:** {psd.width} x {psd.height}")
        result.append(f"**Color Mode:** {PSD_COLOR_MODES.get(psd.color_mode, str(psd.color_mode))}")
        result.append(f"**Channels:** {psd.channels}")
        result.append(f"**Depth:** {psd.depth} bit")
        result.append("")

        # Layer info
        result.append("## Layers")
        result.append("| # | Name | Visible | Opacity | Blend Mode |")
        result.append("| --- | --- | --- | --- | --- |")
        for i, layer in enumerate(psd):
            name = layer.name or f"Layer {i}"
            visible = "Yes" if layer.visible else "No"
            opacity = f"{layer.opacity}%" if layer.opacity is not None else "N/A"
            blend = layer.blend_mode.name if layer.blend_mode else "Normal"
            result.append(f"| {i + 1} | {name} | {visible} | {opacity} | {blend} |")

        if not list(psd):
            result.append("| - | *(No layers or flat image)* | - | - | - |")

        psd.close()
        return "\n".join(result)

    def _extract_binary(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError as e:
            return f"Error: Cannot read PSD file: {e}"

        if len(data) < 30:
            return "Error: File too small to be a valid PSD."

        # Verify magic: '8BPS'
        magic = data[0:4]
        if magic != b"8BPS":
            return f"Error: Invalid PSD magic bytes: {magic!r} (expected b'8BPS')"

        # Parse header
        version = struct.unpack_from(">H", data, 4)[0]
        # Bytes 6-13: reserved (6 bytes of zeros)
        channels = struct.unpack_from(">H", data, 12)[0]
        height = struct.unpack_from(">I", data, 14)[0]
        width = struct.unpack_from(">I", data, 18)[0]
        depth = struct.unpack_from(">H", data, 22)[0]
        color_mode = struct.unpack_from(">H", data, 24)[0]

        result = [f"# PSD Image: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(len(data))}")
        result.append(f"**Dimensions:** {width} x {height}")
        result.append(f"**Version:** {version}")
        result.append(f"**Color Mode:** {PSD_COLOR_MODES.get(color_mode, str(color_mode))}")
        result.append(f"**Channels:** {channels}")
        result.append(f"**Bit Depth:** {depth}")
        result.append("")

        # Parse color mode data section (skip it)
        offset = 26
        if offset + 4 > len(data):
            result.append("*Header only — file truncated before color mode data.*")
            return "\n".join(result)
        color_data_len = struct.unpack_from(">I", data, offset)[0]
        offset += 4 + color_data_len

        # Parse image resources section (skip it)
        if offset + 4 > len(data):
            result.append("*No image resources section.*")
            return "\n".join(result)
        resource_data_len = struct.unpack_from(">I", data, offset)[0]
        offset += 4 + resource_data_len

        # Parse layer and mask information section
        if offset + 4 > len(data):
            result.append("*No layer information section.*")
            return "\n".join(result)
        layer_data_len = struct.unpack_from(">I", data, offset)[0]
        offset += 4

        if layer_data_len > 0 and offset + layer_data_len <= len(data):
            result.append("## Layers (Binary Parse)")
            result.append("| # | Name | Visible | Opacity | Blend Mode |")
            result.append("| --- | --- | --- | --- | --- |")

            try:
                # Layer info sub-section
                layer_info_len = struct.unpack_from(">i", data, offset)[0]
                offset += 4

                if layer_info_len > 0:
                    layer_count = struct.unpack_from(">h", data, offset)[0]
                    # Negative count means first alpha channel contains transparency
                    layer_count = abs(layer_count)
                    offset += 2

                    for i in range(min(layer_count, 100)):
                        if offset + 34 > len(data):
                            break

                        top = struct.unpack_from(">i", data, offset)[0]
                        left = struct.unpack_from(">i", data, offset + 4)[0]
                        bottom = struct.unpack_from(">i", data, offset + 8)[0]
                        right = struct.unpack_from(">i", data, offset + 12)[0]
                        layer_channels = struct.unpack_from(">H", data, offset + 16)[0]
                        offset += 18

                        # Skip channel information (6 bytes per channel)
                        offset += layer_channels * 6

                        if offset + 12 > len(data):
                            break

                        # Blend mode signature and key
                        blend_sig = data[offset:offset + 4]
                        blend_key = data[offset + 4:offset + 8]
                        opacity = data[offset + 8]
                        # clipping: offset+9, flags: offset+10, filler: offset+11
                        offset += 12

                        blend_name = "Unknown"
                        if blend_sig == b"8BIM":
                            blend_name = PSD_BLEND_MODES.get(blend_key, blend_key.decode("latin-1", errors="replace"))

                        # Extra data length
                        if offset + 4 > len(data):
                            break
                        extra_len = struct.unpack_from(">I", data, offset)[0]
                        offset += 4
                        extra_end = offset + extra_len

                        layer_name = f"Layer {i + 1}"
                        visible = "Yes"

                        # Parse layer mask data (skip)
                        if offset + 4 > len(data):
                            break
                        mask_len = struct.unpack_from(">I", data, offset)[0]
                        offset += 4 + mask_len

                        # Parse layer blending ranges (skip)
                        if offset + 4 > len(data):
                            break
                        blend_ranges_len = struct.unpack_from(">I", data, offset)[0]
                        offset += 4 + blend_ranges_len

                        # Parse layer name (Pascal string, padded to 4 bytes)
                        if offset < extra_end:
                            name_len = data[offset]
                            offset += 1
                            if name_len > 0 and offset + name_len <= extra_end:
                                layer_name = data[offset:offset + name_len].decode("latin-1", errors="replace")
                            offset += name_len
                            # Pad to 4-byte boundary
                            pad = (4 - ((name_len + 1) % 4)) % 4
                            offset += pad

                        # Ensure we're at the end of extra data
                        offset = extra_end

                        # Check visibility via flags (bit 1 = invisible)
                        # We don't have the flags byte easily accessible, report opacity
                        width_l = right - left
                        height_l = bottom - top
                        result.append(
                            f"| {i + 1} | {layer_name} | N/A | {opacity}% | {blend_name} |"
                        )

                    if layer_count > 100:
                        result.append(f"\n*(Showing first 100 of {layer_count} layers)*")
                    elif layer_count == 0:
                        result.append("| - | *(No layers — flat image)* | - | - | - |")
                else:
                    result.append("| - | *(No layer records)* | - | - | - |")
            except struct.error as e:
                result.append(f"*Layer parsing stopped due to binary read error: {e}*")
        else:
            result.append("*No layer data available.*")

        return "\n".join(result)


@register_extractor
class AiExtractor(BaseExtractor):
    """Extracts metadata from Adobe Illustrator (.ai) files.

    AI files may be PDF or EPS format. Detects format by file header
    and parses accordingly.
    """

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                header = f.read(256)
        except OSError as e:
            return f"Error: Cannot read AI file: {e}"

        if len(header) < 4:
            return "Error: File too small to identify format."

        result = [f"# Adobe Illustrator File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        # Detect format
        if header[:5] == b"%PDF-":
            result.append(f"**Format:** PDF-based AI")
            result.append("")
            result.append(self._parse_pdf(file_path))
        elif header[:4] == b"%!PS":
            result.append(f"**Format:** EPS-based AI (PostScript)")
            result.append("")
            result.append(self._parse_eps(file_path))
        elif header[:4] == b"\xc5\xd0\xd3\xc6":
            result.append(f"**Format:** EPS-based AI (binary DSC)")
            result.append("")
            result.append(self._parse_eps_binary(file_path, header))
        else:
            result.append(f"**Format:** Unknown")
            result.append(f"**Header (hex):** `{header[:16].hex()}`")
            result.append(f"**Header (ascii):** `{header[:32].decode('ascii', errors='replace')}`")
            result.append("")
            result.append("*Could not determine AI file format from header.*")

        return "\n".join(result)

    def _parse_pdf(self, file_path: str) -> str:
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                return "Error: pypdf (or PyPDF2) is not installed."

        try:
            reader = PdfReader(file_path)
            result = ["## PDF Metadata"]
            result.append("| Field | Value |")
            result.append("| --- | --- |")

            meta = reader.metadata
            if meta:
                fields = {
                    "Title": "/Title",
                    "Author": "/Author",
                    "Creator": "/Creator",
                    "Producer": "/Producer",
                    "Creation Date": "/CreationDate",
                    "Modification Date": "/ModDate",
                    "Subject": "/Subject",
                    "Keywords": "/Keywords",
                }
                for label, key in fields.items():
                    val = meta.get(key) if hasattr(meta, "get") else getattr(meta, key, None)
                    if val:
                        result.append(f"| {label} | {str(val)[:200]} |")
            else:
                result.append("| - | *(No metadata found)* |")

            result.append("")
            result.append("## Document Info")
            result.append(f"- **Pages:** {len(reader.pages)}")
            result.append(f"- **Encrypted:** {'Yes' if reader.is_encrypted else 'No'}")

            # Try to extract page dimensions from first page
            if reader.pages:
                first_page = reader.pages[0]
                box = first_page.mediabox
                if box:
                    w = float(box.width)
                    h = float(box.height)
                    result.append(f"- **Page Size:** {w:.1f} x {h:.1f} points ({w / 72:.2f} x {h / 72:.2f} inches)")

            return "\n".join(result)
        except Exception as e:
            return f"*PDF parsing error: {e}*"

    def _parse_eps(self, file_path: str) -> str:
        result = ["## PostScript DSC Comments"]
        result.append("| Comment | Value |")
        result.append("| --- | --- |")

        try:
            with open(file_path, "r", encoding="latin-1", errors="replace") as f:
                for line_num, line in enumerate(f):
                    if line_num > 500:
                        break
                    line = line.strip()
                    if line.startswith("%%"):
                        # Split on first ':'
                        if ":" in line:
                            key, _, val = line.partition(":")
                            val = val.strip()
                            if val:
                                result.append(f"| {key} | {val[:200]} |")
                        else:
                            result.append(f"| {line} | *(standalone)* |")
        except OSError as e:
            return f"*EPS read error: {e}*"

        if len(result) == 2:
            result.append("| - | *(No DSC comments found)* |")

        return "\n".join(result)

    def _parse_eps_binary(self, file_path: str, header: bytes) -> str:
        result = ["## Binary EPS Header"]
        result.append(f"- **Magic:** `{header[:4].hex()}` (WMF/EPS binary header)")
        result.append(f"- **Header (hex):** `{header[:64].hex()}`")
        result.append("")
        result.append("*Binary EPS format — limited metadata available without full PostScript interpreter.*")
        return "\n".join(result)


@register_extractor
class InddExtractor(BaseExtractor):
    """Extracts metadata from Adobe InDesign (.indd) files.

    INDD files are typically OLE2 compound document containers.
    Uses olefile for metadata and stream listing.
    """

    async def extract_to_markdown(self, file_path: str) -> str:
        result = [f"# Adobe InDesign File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        # Check if it's an OLE2 file
        try:
            import olefile
        except ImportError:
            result.append("")
            result.append("Error: olefile is not installed. Install with `pip install olefile`.")
            result.append("")
            result.append(self._raw_binary_info(file_path))
            return "\n".join(result)

        if not olefile.isOleFile(file_path):
            result.append(f"**Format:** Raw binary (not OLE2)")
            result.append("")
            result.append(self._raw_binary_info(file_path))
            return "\n".join(result)

        result.append(f"**Format:** OLE2 Compound Document")
        result.append("")

        try:
            ole = olefile.OleFileIO(file_path)
        except Exception as e:
            result.append(f"Error: Failed to open OLE2 file: {e}")
            return "\n".join(result)

        try:
            # Metadata
            meta = ole.get_metadata()
            result.append("## OLE2 Metadata")
            result.append("| Field | Value |")
            result.append("| --- | --- |")

            meta_fields = [
                ("Title", meta.title),
                ("Subject", meta.subject),
                ("Author", meta.author),
                ("Last Saved By", meta.last_saved_by),
                ("Revision Number", meta.revision_number),
                ("Application", meta.creating_application),
                ("Created", meta.create_time),
                ("Last Saved", meta.last_saved_time),
                ("Code Page", meta.codepage),
                ("Category", meta.category),
                ("Keywords", meta.keywords),
                ("Comments", meta.comments),
                ("Manager", meta.manager),
                ("Company", meta.company),
            ]

            for label, val in meta_fields:
                if val is not None and val != b"" and val != "":
                    if isinstance(val, bytes):
                        val = val.decode("latin-1", errors="replace").strip("\x00")
                    result.append(f"| {label} | {str(val)[:200]} |")

            result.append("")

            # List streams
            streams = ole.listdir()
            if streams:
                result.append("## OLE2 Streams")
                result.append("| # | Stream Path | Size |")
                result.append("| --- | --- | --- |")
                for i, stream_path in enumerate(streams[:200]):
                    path_str = "/".join(stream_path)
                    try:
                        size = ole.get_size(path_str)
                        result.append(f"| {i + 1} | `{path_str}` | {_format_size(size)} |")
                    except Exception:
                        result.append(f"| {i + 1} | `{path_str}` | N/A |")
                if len(streams) > 200:
                    result.append(f"\n*(Showing first 200 of {len(streams)} streams)*")
            else:
                result.append("*No streams found in OLE2 container.*")

        finally:
            ole.close()

        return "\n".join(result)

    def _raw_binary_info(self, file_path: str) -> str:
        """Fallback: show basic binary header information."""
        try:
            with open(file_path, "rb") as f:
                header = f.read(128)
        except OSError as e:
            return f"Error: Cannot read file: {e}"

        result = ["## Raw Binary Analysis"]
        result.append(f"- **Header (hex):** `{header[:32].hex()}`")
        result.append(f"- **Header (ascii):** `{header[:64].decode('ascii', errors='replace')}`")

        # Check for known signatures
        if header[:4] == b"\xc5\xd0\xd3\xc6":
            result.append("- **Detected Format:** Likely EPS/Illustrator file embedded in INDD")
        elif header[:2] == b"PK":
            result.append("- **Detected Format:** ZIP-based format (possibly IDML or modern INDD)")
        elif header[:4] == b"\x06\x06\xed\xf5":
            result.append("- **Detected Format:** Adobe Large Document Format (DjVu-like)")
        else:
            result.append("- **Detected Format:** Unknown binary format")

        return "\n".join(result)
