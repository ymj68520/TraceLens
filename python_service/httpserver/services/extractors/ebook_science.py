"""Ebook, 3D model, subtitle, and scientific data extractors."""
import logging
import os
import re
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


# ---------------------------------------------------------------------------
# Task 8: Pure text parsers
# ---------------------------------------------------------------------------

@register_extractor
class SrtExtractor(BaseExtractor):
    """Extracts metadata and preview from SubRip subtitle files (.srt)."""

    _BLOCK_RE = re.compile(
        r"(\d+)\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\n([\s\S]*?)(?=\n\n|\n\d+\n|\Z)"
    )

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read SRT file: {e}"

        matches = self._BLOCK_RE.findall(content)
        if not matches:
            return f"Error: No subtitle blocks found in {os.path.basename(file_path)}"

        result = [f"# SRT Subtitles: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Total Entries:** {len(matches)}")
        result.append(f"**Time Range:** {matches[0][1]} --> {matches[-1][2]}")
        result.append("")

        result.append("## Subtitle Preview (first 20 entries)")
        result.append("| # | Start | End | Text |")
        result.append("| --- | --- | --- | --- |")
        for idx, (num, start, end, text) in enumerate(matches[:20]):
            clean = text.replace("\n", " ").strip()
            result.append(f"| {num} | {start} | {end} | {clean[:120]} |")

        if len(matches) > 20:
            result.append(f"\n*... and {len(matches) - 20} more entries*")

        return "\n".join(result)


@register_extractor
class AssVttExtractor(BaseExtractor):
    """Extracts metadata from ASS/SSA/VTT subtitle files."""

    _ASS_SECTION_RE = re.compile(r"^\[(.+?)\]\s*$", re.MULTILINE)
    _ASS_EVENTS_RE = re.compile(r"^Dialogue:.*$", re.MULTILINE)
    _VTT_CUE_RE = re.compile(
        r"((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*((?:\d{2}:)?\d{2}:\d{2}\.\d{3})\n([\s\S]*?)(?=\n\n|\n(?:\d{2}:)?\d{2}:\d{2}\.\d{3}\s*-->|\Z)"
    )

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read subtitle file: {e}"

        ext = os.path.splitext(file_path)[1].lower()

        if ext in (".ass", ".ssa"):
            return self._parse_ass(content, file_path)
        elif ext == ".vtt":
            return self._parse_vtt(content, file_path)
        else:
            return f"Error: Unsupported subtitle format: {ext}"

    def _parse_ass(self, content: str, file_path: str) -> str:
        result = [f"# ASS/SSA Subtitles: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** {os.path.splitext(file_path)[1].upper()[1:]}")
        result.append("")

        # Parse sections
        section_content = re.split(r"^\[.+?\]\s*$", content, flags=re.MULTILINE)
        section_names = self._ASS_SECTION_RE.findall(content)

        # Script Info
        if "Script Info" in section_names:
            idx = section_names.index("Script Info")
            info_text = section_content[idx + 1].strip() if idx + 1 < len(section_content) else ""
            result.append("## Script Info")
            for line in info_text.splitlines()[:20]:
                line = line.strip()
                if line and not line.startswith(";"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        result.append(f"- **{k.strip()}:** {v.strip()}")
                    else:
                        result.append(f"- {line}")

        # Styles
        if "V4+ Styles" in section_names or "V4 Styles" in section_names:
            key = "V4+ Styles" if "V4+ Styles" in section_names else "V4 Styles"
            idx = section_names.index(key)
            style_text = section_content[idx + 1].strip() if idx + 1 < len(section_content) else ""
            result.append("")
            result.append("## Styles")
            for line in style_text.splitlines()[:15]:
                result.append(f"    {line.strip()}")

        # Events
        events = self._ASS_EVENTS_RE.findall(content)
        result.append("")
        result.append(f"## Events ({len(events)} total)")
        if events:
            result.append("### Preview (first 15)")
            for ev in events[:15]:
                result.append(f"- {ev[:200]}")
            if len(events) > 15:
                result.append(f"\n*... and {len(events) - 15} more events*")

        return "\n".join(result)

    def _parse_vtt(self, content: str, file_path: str) -> str:
        result = [f"# WebVTT Subtitles: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** WebVTT")
        result.append("")

        # Check for WEBVTT header
        if content.strip().startswith("WEBVTT"):
            first_line = content.strip().split("\n", 1)[0]
            result.append(f"**Header:** {first_line.strip()}")
        else:
            result.append("*Warning: No WEBVTT header found*")

        # Parse cues
        cues = self._VTT_CUE_RE.findall(content)
        result.append("")
        result.append(f"## Cues ({len(cues)} total)")
        result.append("| # | Start | End | Text |")
        result.append("| --- | --- | --- | --- |")
        for i, (start, end, text) in enumerate(cues[:30]):
            clean = text.strip().replace("\n", " ")
            result.append(f"| {i + 1} | {start} | {end} | {clean[:120]} |")

        if len(cues) > 30:
            result.append(f"\n*... and {len(cues) - 30} more cues*")

        # NOTE section
        notes = re.findall(r"NOTE\s*\n([\s\S]*?)(?=\n\n|\Z)", content)
        if notes:
            result.append("")
            result.append(f"## Notes ({len(notes)} total)")
            for note in notes[:5]:
                result.append(f"> {note.strip()[:200]}")

        return "\n".join(result)


@register_extractor
class ObjExtractor(BaseExtractor):
    """Extracts metadata from Wavefront OBJ 3D model files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception as e:
            return f"Error: Failed to read OBJ file: {e}"

        vertices = []
        texcoords = []
        normals = []
        faces = []
        objects = []
        materials = set()
        mtllib = []

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not parts:
                continue
            cmd = parts[0]
            if cmd == "v" and len(parts) >= 4:
                try:
                    vertices.append(tuple(float(x) for x in parts[1:4]))
                except ValueError:
                    pass
            elif cmd == "vt" and len(parts) >= 3:
                texcoords.append(parts[1:])
            elif cmd == "vn" and len(parts) >= 4:
                normals.append(parts[1:4])
            elif cmd == "f":
                faces.append(parts[1:])
            elif cmd in ("o", "g") and len(parts) >= 2:
                objects.append(parts[1])
            elif cmd == "usemtl" and len(parts) >= 2:
                materials.add(parts[1])
            elif cmd == "mtllib" and len(parts) >= 2:
                mtllib.append(" ".join(parts[1:]))

        result = [f"# OBJ 3D Model: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Lines:** {len(lines)}")
        result.append("")
        result.append("## Geometry Summary")
        result.append("| Property | Count |")
        result.append("| --- | --- |")
        result.append(f"| Vertices | {len(vertices)} |")
        result.append(f"| Texture Coordinates | {len(texcoords)} |")
        result.append(f"| Normals | {len(normals)} |")
        result.append(f"| Faces | {len(faces)} |")
        result.append(f"| Objects/Groups | {len(objects)} |")
        result.append(f"| Materials | {len(materials)} |")

        # Bounding box
        if vertices:
            xs = [v[0] for v in vertices]
            ys = [v[1] for v in vertices]
            zs = [v[2] for v in vertices]
            result.append("")
            result.append("## Bounding Box")
            result.append("| Axis | Min | Max | Size |")
            result.append("| --- | --- | --- | --- |")
            result.append(f"| X | {min(xs):.6f} | {max(xs):.6f} | {max(xs) - min(xs):.6f} |")
            result.append(f"| Y | {min(ys):.6f} | {max(ys):.6f} | {max(ys) - min(ys):.6f} |")
            result.append(f"| Z | {min(zs):.6f} | {max(zs):.6f} | {max(zs) - min(zs):.6f} |")

        # Objects
        if objects:
            result.append("")
            result.append("## Objects/Groups")
            for obj in objects[:30]:
                result.append(f"- {obj}")
            if len(objects) > 30:
                result.append(f"\n*... and {len(objects) - 30} more*")

        # Materials
        if materials or mtllib:
            result.append("")
            result.append("## Materials")
            if mtllib:
                result.append(f"**Library files:** {', '.join(mtllib)}")
            for mat in sorted(materials)[:20]:
                result.append(f"- {mat}")

        return "\n".join(result)


@register_extractor
class StlExtractor(BaseExtractor):
    """Extracts metadata from STL (3D printing) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                header = f.read(80)
                if len(header) < 5:
                    return "Error: File too small to be a valid STL."
                # Check if ASCII
                header_text = header.decode("ascii", errors="ignore").strip().lower()
                is_ascii = header_text.startswith("solid")
                if is_ascii:
                    # Read a bit more to confirm ASCII with facet keyword
                    f.seek(0)
                    sample = f.read(4096).decode("ascii", errors="ignore")
                    if "facet" not in sample:
                        is_ascii = False

                if is_ascii:
                    return self._parse_ascii(file_path)
                else:
                    return self._parse_binary(file_path)
        except Exception as e:
            return f"Error: Failed to read STL file: {e}"

    def _parse_ascii(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read ASCII STL: {e}"

        normals = re.findall(
            r"facet\s+normal\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)", content
        )
        vertices = re.findall(
            r"vertex\s+([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)", content
        )

        result = [f"# STL 3D Model: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** ASCII STL")
        result.append("")
        result.append("## Geometry Summary")
        result.append("| Property | Value |")
        result.append("| --- | --- |")
        result.append(f"| Triangles (facets) | {len(normals)} |")
        result.append(f"| Vertices | {len(vertices)} |")

        # Bounding box
        if vertices:
            xs = [float(v[0]) for v in vertices]
            ys = [float(v[1]) for v in vertices]
            zs = [float(v[2]) for v in vertices]
            result.append("")
            result.append("## Bounding Box")
            result.append("| Axis | Min | Max | Size |")
            result.append("| --- | --- | --- | --- |")
            result.append(f"| X | {min(xs):.6f} | {max(xs):.6f} | {max(xs) - min(xs):.6f} |")
            result.append(f"| Y | {min(ys):.6f} | {max(ys):.6f} | {max(ys) - min(ys):.6f} |")
            result.append(f"| Z | {min(zs):.6f} | {max(zs):.6f} | {max(zs) - min(zs):.6f} |")

        return "\n".join(result)

    def _parse_binary(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                header = f.read(80)
                tri_count_bytes = f.read(4)
                if len(tri_count_bytes) < 4:
                    return "Error: Binary STL file is truncated."
                tri_count = struct.unpack("<I", tri_count_bytes)[0]
        except Exception as e:
            return f"Error: Failed to parse binary STL: {e}"

        result = [f"# STL 3D Model: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** Binary STL")
        result.append("")
        result.append("## Geometry Summary")
        result.append("| Property | Value |")
        result.append("| --- | --- |")
        result.append(f"| Triangles (facets) | {tri_count} |")
        result.append(f"| Vertices | {tri_count * 3} |")

        # File size sanity check: 80 + 4 + tri_count * 50
        expected_size = 80 + 4 + tri_count * 50
        result.append(f"| Expected file size | {expected_size} bytes |")
        result.append(f"| Actual file size | {os.path.getsize(file_path)} bytes |")

        # Read first few triangles for normal info
        try:
            with open(file_path, "rb") as f:
                f.seek(84)
                normals = []
                for _ in range(min(tri_count, 10)):
                    data = f.read(50)
                    if len(data) < 50:
                        break
                    nx, ny, nz = struct.unpack("<fff", data[0:12])
                    normals.append((nx, ny, nz))
                    # skip 12*3 bytes of vertex data + 2 bytes attribute
                if normals:
                    result.append("")
                    result.append("## Sample Normals (first 10 triangles)")
                    result.append("| # | NX | NY | NZ |")
                    result.append("| --- | --- | --- | --- |")
                    for i, (nx, ny, nz) in enumerate(normals):
                        result.append(f"| {i + 1} | {nx:.6f} | {ny:.6f} | {nz:.6f} |")
        except Exception:
            pass

        return "\n".join(result)


# ---------------------------------------------------------------------------
# Task 9: eBook parsers
# ---------------------------------------------------------------------------

@register_extractor
class EpubExtractor(BaseExtractor):
    """Extracts metadata, spine, manifest, and TOC from EPUB files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        import zipfile
        try:
            from defusedxml import ElementTree as ET
        except ImportError:
            return "Error: defusedxml library is not installed. Install with: pip install defusedxml"

        try:
            if not zipfile.is_zipfile(file_path):
                return f"Error: {os.path.basename(file_path)} is not a valid ZIP/EPUB file."

            with zipfile.ZipFile(file_path, "r") as zf:
                # Find container.xml
                container_xml = None
                if "META-INF/container.xml" in zf.namelist():
                    container_xml = zf.read("META-INF/container.xml").decode("utf-8", errors="replace")
                else:
                    return "Error: No META-INF/container.xml found in EPUB."

                # Parse container to find OPF file
                try:
                    container_tree = ET.fromstring(container_xml)
                except Exception as e:
                    return f"Error: Failed to parse container.xml: {e}"

                ns_c = {"c": "urn:oasis:names:tc:opendml:xmlns:container"}
                rootfiles = container_tree.findall(".//c:rootfile", ns_c)
                if not rootfiles:
                    rootfiles = container_tree.findall(".//rootfile")

                if not rootfiles:
                    return "Error: No rootfile found in container.xml."

                opf_path = rootfiles[0].get("full-path", "")
                if not opf_path or opf_path not in zf.namelist():
                    return f"Error: OPF file '{opf_path}' not found in EPUB."

                opf_content = zf.read(opf_path).decode("utf-8", errors="replace")
                try:
                    opf_tree = ET.fromstring(opf_content)
                except Exception as e:
                    return f"Error: Failed to parse OPF: {e}"

                result = [f"# EPUB eBook: `{os.path.basename(file_path)}`"]
                result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
                result.append("")

                # Metadata
                ns_opf = {
                    "opf": "http://www.idpf.org/2007/opf",
                    "dc": "http://purl.org/dc/elements/1.1/",
                }

                # Try with and without namespace prefixes
                def find_meta(tag):
                    elem = opf_tree.find(f".//{{*}}{tag.split(':')[-1]}") if ":" in tag else opf_tree.find(f".//{{*}}{tag}")
                    if elem is None:
                        elem = opf_tree.find(f".//{tag}")
                    return elem

                # Also try with explicit dc namespace
                metadata = opf_tree.find(".//{http://www.idpf.org/2007/opf}metadata")
                if metadata is None:
                    metadata = opf_tree.find(".//metadata")

                result.append("## Metadata")

                dc_tags = {
                    "title": "Title",
                    "creator": "Author",
                    "publisher": "Publisher",
                    "date": "Date",
                    "description": "Description",
                    "language": "Language",
                    "identifier": "Identifier",
                    "rights": "Rights",
                    "subject": "Subject",
                }

                found_meta = False
                if metadata is not None:
                    for dc_key, label in dc_tags.items():
                        elem = metadata.find(f"{{http://purl.org/dc/elements/1.1/}}{dc_key}")
                        if elem is None:
                            elem = metadata.find(dc_key)
                        if elem is not None and elem.text and elem.text.strip():
                            result.append(f"- **{label}:** {elem.text.strip()[:200]}")
                            found_meta = True

                if not found_meta:
                    result.append("*No metadata found in OPF.*")

                result.append("")

                # Manifest
                manifest = opf_tree.find(".//{http://www.idpf.org/2007/opf}manifest")
                if manifest is None:
                    manifest = opf_tree.find(".//manifest")

                items = []
                if manifest is not None:
                    items = manifest.findall("{http://www.idpf.org/2007/opf}item")
                    if not items:
                        items = manifest.findall("item")

                if items:
                    result.append(f"## Manifest ({len(items)} items)")
                    result.append("| ID | Media Type | Href |")
                    result.append("| --- | --- | --- |")
                    for item in items[:30]:
                        item_id = item.get("id", "N/A")
                        media_type = item.get("media-type", "N/A")
                        href = item.get("href", "N/A")
                        result.append(f"| {item_id} | {media_type} | {href} |")
                    if len(items) > 30:
                        result.append(f"\n*... and {len(items) - 30} more items*")

                result.append("")

                # Spine (reading order)
                spine = opf_tree.find(".//{http://www.idpf.org/2007/opf}spine")
                if spine is None:
                    spine = opf_tree.find(".//spine")

                if spine is not None:
                    spine_refs = spine.findall("{http://www.idpf.org/2007/opf}itemref")
                    if not spine_refs:
                        spine_refs = spine.findall("itemref")
                    result.append(f"## Spine / Reading Order ({len(spine_refs)} items)")
                    for i, ref in enumerate(spine_refs[:20]):
                        idref = ref.get("idref", "N/A")
                        result.append(f"{i + 1}. {idref}")
                    if len(spine_refs) > 20:
                        result.append(f"\n*... and {len(spine_refs) - 20} more items*")

                result.append("")

                # TOC (toc.ncx)
                toc_ncx_path = None
                # Try to find toc.ncx in manifest
                for item in items:
                    props = item.get("properties", "")
                    href = item.get("href", "")
                    if "nav" in props or href.endswith("toc.ncx") or href.endswith("nav.xhtml"):
                        toc_ncx_path = href
                        break
                if not toc_ncx_path:
                    # Try common paths relative to OPF
                    opf_dir = os.path.dirname(opf_path)
                    for candidate in ["toc.ncx", "TOC.ncx"]:
                        full = f"{opf_dir}/{candidate}" if opf_dir else candidate
                        if full in zf.namelist():
                            toc_ncx_path = full
                            break

                if toc_ncx_path and toc_ncx_path in zf.namelist():
                    try:
                        toc_content = zf.read(toc_ncx_path).decode("utf-8", errors="replace")
                        toc_tree = ET.fromstring(toc_content)
                        nav_points = toc_tree.findall(".//{*}navPoint")
                        if not nav_points:
                            nav_points = toc_tree.findall(".//navPoint")
                        if nav_points:
                            result.append(f"## Table of Contents ({len(nav_points)} entries)")
                            for np in nav_points[:25]:
                                label_el = np.find("{*}navLabel/{*}text")
                                if label_el is None:
                                    label_el = np.find("navLabel/text")
                                label = label_el.text.strip() if label_el is not None and label_el.text else "Untitled"
                                result.append(f"- {label}")
                            if len(nav_points) > 25:
                                result.append(f"\n*... and {len(nav_points) - 25} more entries*")
                    except Exception as e:
                        result.append(f"*Failed to parse TOC: {e}*")

                return "\n".join(result)

        except zipfile.BadZipFile:
            return f"Error: {os.path.basename(file_path)} is not a valid ZIP/EPUB file."
        except Exception as e:
            return f"Error: Failed to parse EPUB: {e}"


@register_extractor
class MobiExtractor(BaseExtractor):
    """Extracts metadata from MOBI/AZW/AZW3 eBook files."""

    # EXTH record type mapping
    _EXTH_TYPES = {
        100: "Creator",
        101: "Publisher",
        103: "Description",
        104: "ISBN",
        105: "Subject",
        106: "Date",
        109: "ASIN",
        110: "Language",
        112: "Language (alt)",
        113: "Creator2",
        114: "Publisher2",
        115: "Label",
        116: "ISBN2",
        201: "Cover Offset",
        202: "Thumb Offset",
        203: "Has Fake Cover",
        401: "Clipping Limit",
        403: "Text-to-Speech Enabled",
    }

    _ENCODINGS = {
        1252: "cp1252",
        65001: "utf-8",
    }

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read MOBI file: {e}"

        if len(data) < 4:
            return "Error: File too small to be a valid MOBI."

        # Find MOBI magic
        mobi_offset = data.find(b"MOBI")
        if mobi_offset == -1:
            return "Error: No MOBI header found in file."

        result = [f"# MOBI eBook: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")

        # Parse MOBI header
        try:
            if mobi_offset + 24 > len(data):
                return "Error: MOBI header truncated."

            mobi_data = data[mobi_offset:]
            header_len = struct.unpack(">I", mobi_data[4:8])[0]
            mobi_type = struct.unpack(">I", mobi_data[8:12])[0]
            text_encoding = struct.unpack(">I", mobi_data[12:16])[0]
            unique_id = struct.unpack(">I", mobi_data[16:20])[0]
            mobi_version = struct.unpack(">I", mobi_data[20:24])[0]

            type_names = {2: "MOBI Book", 3: "PalmDoc", 4: "Audio", 257: "News", 258: "News Feed", 259: "News Magazine"}
            encoding_name = self._ENCODINGS.get(text_encoding, f"Unknown ({text_encoding})")

            result.append("## MOBI Header")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            result.append(f"| Header Length | {header_len} bytes |")
            result.append(f"| Type | {type_names.get(mobi_type, mobi_type)} |")
            result.append(f"| Text Encoding | {encoding_name} |")
            result.append(f"| MOBI Version | {mobi_version} |")
        except Exception as e:
            result.append(f"*Failed to parse MOBI header: {e}*")

        # Parse EXTH header
        try:
            exth_offset = mobi_offset + header_len
            if exth_offset + 4 <= len(data) and data[exth_offset:exth_offset + 4] == b"EXTH":
                exth_data = data[exth_offset:]
                exth_count = struct.unpack(">I", exth_data[8:12])[0]
                result.append("")
                result.append(f"## EXTH Records ({exth_count} records)")
                result.append("| Type | Name | Value |")
                result.append("| --- | --- | --- |")

                pos = 12
                for _ in range(min(exth_count, 50)):
                    if pos + 8 > len(exth_data):
                        break
                    record_type = struct.unpack(">I", exth_data[pos:pos + 4])[0]
                    record_len = struct.unpack(">I", exth_data[pos + 4:pos + 8])[0]
                    if record_len < 8 or pos + record_len > len(exth_data):
                        break
                    record_data = exth_data[pos + 8:pos + record_len]
                    type_name = self._EXTH_TYPES.get(record_type, f"Unknown")

                    # Decode value
                    try:
                        value = record_data.decode(encoding_name, errors="replace").strip()
                    except Exception:
                        value = record_data.hex()

                    # Truncate long values
                    if len(value) > 150:
                        value = value[:150] + "..."

                    result.append(f"| {record_type} | {type_name} | {value} |")
                    pos += record_len
            else:
                result.append("\n*No EXTH header found.*")
        except Exception as e:
            result.append(f"\n*Failed to parse EXTH records: {e}*")

        return "\n".join(result)


# ---------------------------------------------------------------------------
# Task 10: Scientific data parsers
# ---------------------------------------------------------------------------

@register_extractor
class Hdf5Extractor(BaseExtractor):
    """Extracts metadata and structure from HDF5 scientific data files."""

    _MAX_DEPTH = 5
    _MAX_ITEMS_PER_GROUP = 50

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import h5py
        except ImportError:
            return "Error: h5py library is not installed. Install with: pip install h5py"

        try:
            with h5py.File(file_path, "r") as f:
                result = [f"# HDF5 File: `{os.path.basename(file_path)}`"]
                result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
                result.append("")

                # File-level attributes
                if f.attrs:
                    result.append("## File Attributes")
                    result.append("| Key | Value |")
                    result.append("| --- | --- |")
                    for key in list(f.attrs.keys())[:30]:
                        val = f.attrs[key]
                        if hasattr(val, "shape") and len(val.shape) > 0:
                            val = f"Array shape={val.shape}, dtype={val.dtype}"
                        result.append(f"| {key} | {str(val)[:120]} |")
                    result.append("")

                # Tree structure
                result.append("## Structure")
                datasets = []
                self._walk_group(f, result, datasets, depth=0, prefix="")
                result.append("")

                # Dataset summary
                if datasets:
                    result.append(f"## Datasets ({len(datasets)} total)")
                    result.append("| Path | Shape | Dtype |")
                    result.append("| --- | --- | --- |")
                    for ds_path, shape, dtype in datasets[:50]:
                        result.append(f"| {ds_path} | {shape} | {dtype} |")
                    if len(datasets) > 50:
                        result.append(f"\n*... and {len(datasets) - 50} more datasets*")

                return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to read HDF5 file: {e}"

    def _walk_group(self, group, result: list, datasets: list, depth: int, prefix: str):
        if depth >= self._MAX_DEPTH:
            result.append(f"{'  ' * depth}*... (max depth reached)*")
            return

        import h5py

        items = list(group.keys())
        for i, name in enumerate(items[: self._MAX_ITEMS_PER_GROUP]):
            item = group[name]
            if isinstance(item, h5py.Group):
                result.append(f"{'  ' * depth}- **{name}/** (group, {len(item)} items)")
                self._walk_group(item, result, datasets, depth + 1, prefix + name + "/")
            elif isinstance(item, h5py.Dataset):
                shape_str = str(item.shape) if item.shape else "scalar"
                result.append(f"{'  ' * depth}- `{name}` (dataset, shape={shape_str}, dtype={item.dtype})")
                datasets.append((prefix + name, shape_str, str(item.dtype)))

        if len(items) > self._MAX_ITEMS_PER_GROUP:
            result.append(f"{'  ' * depth}*... and {len(items) - self._MAX_ITEMS_PER_GROUP} more items*")


@register_extractor
class DicomExtractor(BaseExtractor):
    """Extracts metadata from DICOM medical imaging files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import pydicom
        except ImportError:
            return "Error: pydicom library is not installed. Install with: pip install pydicom"

        try:
            ds = pydicom.dcmread(file_path, stop_before_pixels=True)

            result = [f"# DICOM File: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Patient info
            result.append("## Patient Information")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            patient_fields = [
                ("PatientID", "Patient ID"),
                ("PatientName", "Patient Name"),
                ("PatientBirthDate", "Birth Date"),
                ("PatientSex", "Sex"),
                ("PatientAge", "Age"),
            ]
            for attr_name, label in patient_fields:
                val = getattr(ds, attr_name, None)
                if val is not None:
                    result.append(f"| {label} | {str(val).strip()[:100]} |")

            # Study info
            result.append("")
            result.append("## Study Information")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            study_fields = [
                ("StudyDate", "Study Date"),
                ("StudyTime", "Study Time"),
                ("StudyDescription", "Study Description"),
                ("StudyID", "Study ID"),
                ("AccessionNumber", "Accession Number"),
                ("Modality", "Modality"),
                ("InstitutionName", "Institution"),
                ("ReferringPhysicianName", "Referring Physician"),
            ]
            for attr_name, label in study_fields:
                val = getattr(ds, attr_name, None)
                if val is not None:
                    result.append(f"| {label} | {str(val).strip()[:100]} |")

            # Equipment
            result.append("")
            result.append("## Equipment")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            equip_fields = [
                ("Manufacturer", "Manufacturer"),
                ("ManufacturerModelName", "Model"),
                ("SoftwareVersions", "Software"),
                ("StationName", "Station"),
                ("DeviceSerialNumber", "Serial Number"),
            ]
            for attr_name, label in equip_fields:
                val = getattr(ds, attr_name, None)
                if val is not None:
                    result.append(f"| {label} | {str(val).strip()[:100]} |")

            # Image parameters
            result.append("")
            result.append("## Image Parameters")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            image_fields = [
                ("Rows", "Rows"),
                ("Columns", "Columns"),
                ("BitsAllocated", "Bits Allocated"),
                ("BitsStored", "Bits Stored"),
                ("HighBit", "High Bit"),
                ("PixelRepresentation", "Pixel Representation"),
                ("SamplesPerPixel", "Samples Per Pixel"),
                ("PhotometricInterpretation", "Photometric Interpretation"),
                ("PixelSpacing", "Pixel Spacing"),
                ("SliceThickness", "Slice Thickness"),
                ("ImagePositionPatient", "Image Position"),
                ("ImageOrientationPatient", "Image Orientation"),
                ("WindowCenter", "Window Center"),
                ("WindowWidth", "Window Width"),
            ]
            for attr_name, label in image_fields:
                val = getattr(ds, attr_name, None)
                if val is not None:
                    result.append(f"| {label} | {str(val)[:100]} |")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse DICOM file: {e}"
