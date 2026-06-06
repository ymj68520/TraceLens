"""Extended Microsoft format extractors: URL shortcuts, MSC, XPS, OneNote, Publisher, Visio, Project, ETL."""
import configparser
import io
import logging
import os
import struct
import zipfile

try:
    from defusedxml import ElementTree as ET
except ImportError:
    from xml.etree import ElementTree as ET

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
# Task 4: Simple extractors
# ---------------------------------------------------------------------------


@register_extractor
class UrlExtractor(BaseExtractor):
    """Extracts metadata from Windows Internet Shortcut files (.url, INI format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read URL file: {e}"

        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(content)

            result = [f"# Internet Shortcut: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # [InternetShortcut] section
            if config.has_section("InternetShortcut"):
                result.append("## Properties")
                result.append("| Property | Value |")
                result.append("| --- | --- |")
                fields = ["URL", "IconFile", "IconIndex", "Visited", "HotKey", "WorkingDirectory", "ShowCommand"]
                for field in fields:
                    if config.has_option("InternetShortcut", field):
                        result.append(f"| {field} | {config.get('InternetShortcut', field)} |")

                # Title may appear as a standalone key outside known sections
                title = config.get("InternetShortcut", "Title", fallback=None)
                if title:
                    result.append("")
                    result.append(f"**Title:** {title}")

                url = config.get("InternetShortcut", "URL", fallback=None)
                if url:
                    result.append("")
                    result.append(f"**URL:** {url}")
            else:
                # No recognised section -- dump raw content
                result.append("## Raw Content")
                result.append(f"```\n{content[:4000]}\n```")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse URL file: {e}"


@register_extractor
class MscExtractor(BaseExtractor):
    """Extracts metadata from MMC Console files (.msc, XML format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except Exception as e:
            return f"Error: Failed to parse MSC file: {e}"

        try:
            result = [f"# MMC Console: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # MMC version from root attributes
            version = root.get("ProgramMode", root.get("ConsoleVersion", "Unknown"))
            result.append(f"**MMC Version/Mode:** {version}")

            # Visual attributes
            visual = root.find(".//VisualAttributes")
            if visual is not None:
                result.append("")
                result.append("## Visual Attributes")
                result.append("| Attribute | Value |")
                result.append("| --- | --- |")
                for attr_name, attr_val in visual.attrib.items():
                    result.append(f"| {attr_name} | {attr_val} |")

            # Snap-Ins
            snap_ins = root.findall(".//SnapIn")
            if snap_ins:
                result.append("")
                result.append(f"## Snap-Ins ({len(snap_ins)})")
                result.append("| Name | CLSID |")
                result.append("| --- | --- |")
                for si in snap_ins:
                    name = si.get("Name", si.findtext("Name", ""))
                    clsid = si.get("CLSID", si.findtext("CLSID", ""))
                    result.append(f"| {name} | {clsid} |")

            # Favorites
            favorites = root.findall(".//Favorite")
            if favorites:
                result.append("")
                result.append(f"## Favorites ({len(favorites)})")
                for fav in favorites:
                    name = fav.get("Name", fav.findtext("Name", "Unknown"))
                    result.append(f"- {name}")

            # If nothing interesting was found, list top-level children
            if not snap_ins and not favorites and visual is None:
                result.append("")
                result.append("## XML Structure (top-level)")
                for child in root:
                    tag = child.tag
                    attribs = ", ".join(f"{k}={v}" for k, v in child.attrib.items())
                    result.append(f"- `{tag}`" + (f" ({attribs})" if attribs else ""))

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to process MSC content: {e}"


@register_extractor
class XpsExtractor(BaseExtractor):
    """Extracts content from XPS/OXPS files (.xps, .oxps, ZIP-based XML)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        if not zipfile.is_zipfile(file_path):
            return "Error: Not a valid XPS/OXPS file (not a ZIP archive)."

        try:
            with zipfile.ZipFile(file_path, "r") as z:
                result = [f"# XPS Document: `{os.path.basename(file_path)}`"]
                result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
                result.append("")

                namelist = z.namelist()
                result.append(f"**Parts in package:** {len(namelist)}")

                # Extract core properties
                core_xml = None
                for name in namelist:
                    if name.lower().endswith("core.xml") or name.lower().endswith("core.properties"):
                        core_xml = name
                        break

                if core_xml:
                    result.append("")
                    result.append("## Document Properties")
                    result.append("| Property | Value |")
                    result.append("| --- | --- |")
                    try:
                        data = z.read(core_xml)
                        root = ET.fromstring(data)
                        # Dublin core namespace
                        ns = {
                            "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                            "dc": "http://purl.org/dc/elements/1.1/",
                            "dcterms": "http://purl.org/dc/terms/",
                        }
                        for tag, label in [
                            ("dc:title", "Title"),
                            ("dc:creator", "Creator"),
                            ("cp:revision", "Revision"),
                            ("dcterms:created", "Created"),
                            ("dcterms:modified", "Modified"),
                            ("cp:category", "Category"),
                            ("cp:contentStatus", "Content Status"),
                            ("dc:subject", "Subject"),
                            ("dc:description", "Description"),
                            ("cp:keywords", "Keywords"),
                            ("cp:lastModifiedBy", "Last Modified By"),
                        ]:
                            elem = root.find(tag, ns)
                            if elem is not None and elem.text:
                                result.append(f"| {label} | {elem.text.strip()} |")
                    except Exception as e:
                        result.append(f"| Error | {e} |")

                # Count pages (FixedPage parts)
                page_files = [n for n in namelist if "FixedPage" in n and n.lower().endswith(".fpage")]
                if not page_files:
                    page_files = [n for n in namelist if "/Pages/" in n and n.lower().endswith(".xml")]

                result.append("")
                result.append(f"**Page count:** {len(page_files)}")

                # Extract text from FixedPage Glyphs elements
                texts = []
                ns_xps = {"fp": "http://schemas.microsoft.com/xps/2005/06"}
                for pf in page_files[:30]:  # limit to 30 pages
                    try:
                        page_data = z.read(pf)
                        page_root = ET.fromstring(page_data)
                        for glyph in page_root.iter():
                            if glyph.tag.endswith("Glyphs"):
                                unicode_str = glyph.get("UnicodeString", "")
                                if unicode_str:
                                    texts.append(unicode_str)
                    except Exception:
                        continue

                result.append("")
                result.append("## Extracted Text")
                if texts:
                    combined = " ".join(texts)
                    if len(combined) > 15000:
                        combined = combined[:15000] + "\n\n... (truncated)"
                    result.append(combined)
                else:
                    result.append("*(No text content extracted from pages)*")

                return "\n".join(result)
        except zipfile.BadZipFile:
            return "Error: Not a valid XPS/OXPS file (corrupt ZIP)."
        except Exception as e:
            return f"Error: Failed to parse XPS/OXPS file: {e}"


# ---------------------------------------------------------------------------
# Task 5: OLE2-based extractors
# ---------------------------------------------------------------------------


def _ole_stream_list(ole) -> list:
    """Return list of (stream_path, size) tuples from an olefile."""
    entries = []
    try:
        for stream in ole.listdir():
            path = "/".join(stream)
            try:
                size = ole.get_size(path)
            except Exception:
                size = -1
            entries.append((path, size))
    except Exception as e:
        logger.warning(f"Error listing OLE streams: {e}")
    return entries


@register_extractor
class OneNoteExtractor(BaseExtractor):
    """Extracts metadata from OneNote files (.one, .onetoc2)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        type_name = "OneNote Notebook" if ext == ".one" else "OneNote TOC"

        try:
            import olefile

            if not olefile.isOleFile(file_path):
                return self._fallback_parse(file_path, type_name)
        except ImportError:
            return self._fallback_parse(file_path, type_name)

        try:
            ole = olefile.OleFileIO(file_path)
            result = [f"# {type_name}: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Format:** OLE2 Compound Document")
            result.append("")

            # Metadata
            meta = ole.get_metadata()
            result.append("## Metadata")
            result.append("| Property | Value |")
            result.append("| --- | --- |")
            if meta.title:
                result.append(f"| Title | {meta.title} |")
            if meta.subject:
                result.append(f"| Subject | {meta.subject} |")
            if meta.author:
                result.append(f"| Author | {meta.author} |")
            if meta.last_saved_by:
                result.append(f"| Last Saved By | {meta.last_saved_by} |")
            if meta.create_time:
                result.append(f"| Created | {meta.create_time} |")
            if meta.last_saved_time:
                result.append(f"| Last Modified | {meta.last_saved_time} |")
            if meta.num_pages:
                result.append(f"| Pages | {meta.num_pages} |")
            if meta.company:
                result.append(f"| Company | {meta.company} |")

            # Stream listing
            streams = _ole_stream_list(ole)
            result.append("")
            result.append(f"## Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for path, size in streams[:100]:
                size_str = _format_size(size) if size >= 0 else "N/A"
                result.append(f"| {path} | {size_str} |")
            if len(streams) > 100:
                result.append(f"\n*(Showing first 100 of {len(streams)} streams)*")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse OneNote file with olefile: {e}"

    def _fallback_parse(self, file_path: str, type_name: str) -> str:
        """Raw binary fallback when olefile is unavailable or fails."""
        try:
            with open(file_path, "rb") as f:
                header = f.read(512)
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        result = [f"# {type_name}: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        # Check for OLE2 magic (D0 CF 11 E0 A1 B1 1A E1)
        if header[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            result.append("**Format:** OLE2 Compound Document (detected via magic bytes)")
        else:
            result.append(f"**Magic:** {header[:8].hex()}")
            result.append("*(olefile library not available for full parsing)*")

        result.append("")
        result.append("## Raw Header (hex)")
        result.append("```")
        result.append(header[:256].hex(" "))
        result.append("```")

        return "\n".join(result)


@register_extractor
class PublisherExtractor(BaseExtractor):
    """Extracts metadata from Microsoft Publisher files (.pub, OLE2).

    NOTE: This extractor is NOT auto-routed. The .pub extension stays with
    TextExtractor because .pub also covers SSH/GPG public key files.
    This class exists for explicit use by forensic pipelines.
    """

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile

            if not olefile.isOleFile(file_path):
                return f"Error: Not a valid Publisher file (not an OLE2 document)."
        except ImportError:
            return "Error: olefile library is not installed."

        try:
            ole = olefile.OleFileIO(file_path)
            result = [f"# Microsoft Publisher: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Format:** OLE2 Compound Document")
            result.append("")

            # Metadata
            meta = ole.get_metadata()
            result.append("## Metadata")
            result.append("| Property | Value |")
            result.append("| --- | --- |")
            for attr, label in [
                ("title", "Title"),
                ("subject", "Subject"),
                ("author", "Author"),
                ("last_saved_by", "Last Saved By"),
                ("create_time", "Created"),
                ("last_saved_time", "Last Modified"),
                ("num_pages", "Pages"),
                ("company", "Company"),
                ("manager", "Manager"),
                ("category", "Category"),
                ("keywords", "Keywords"),
                ("comments", "Comments"),
                ("creating_application", "Application"),
            ]:
                val = getattr(meta, attr, None)
                if val:
                    result.append(f"| {label} | {val} |")

            # Stream listing
            streams = _ole_stream_list(ole)
            result.append("")
            result.append(f"## Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for path, size in streams[:100]:
                size_str = _format_size(size) if size >= 0 else "N/A"
                result.append(f"| {path} | {size_str} |")
            if len(streams) > 100:
                result.append(f"\n*(Showing first 100 of {len(streams)} streams)*")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Publisher file: {e}"


@register_extractor
class VisioExtractor(BaseExtractor):
    """Extracts content from Visio files (.vsdx, .vsdm, ZIP-based XML)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        if not zipfile.is_zipfile(file_path):
            return "Error: Not a valid Visio file (not a ZIP archive)."

        try:
            with zipfile.ZipFile(file_path, "r") as z:
                namelist = z.namelist()
                result = [f"# Visio Document: `{os.path.basename(file_path)}`"]
                result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
                result.append("")

                # Core metadata from docProps/core.xml
                core_xml = None
                for name in namelist:
                    if name.lower().endswith("docprops/core.xml"):
                        core_xml = name
                        break

                if core_xml:
                    result.append("## Document Properties")
                    result.append("| Property | Value |")
                    result.append("| --- | --- |")
                    try:
                        data = z.read(core_xml)
                        root = ET.fromstring(data)
                        ns = {
                            "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                            "dc": "http://purl.org/dc/elements/1.1/",
                            "dcterms": "http://purl.org/dc/terms/",
                        }
                        for tag, label in [
                            ("dc:title", "Title"),
                            ("dc:creator", "Creator"),
                            ("cp:revision", "Revision"),
                            ("dcterms:created", "Created"),
                            ("dcterms:modified", "Modified"),
                            ("cp:category", "Category"),
                            ("cp:keywords", "Keywords"),
                            ("cp:lastModifiedBy", "Last Modified By"),
                            ("dc:subject", "Subject"),
                            ("dc:description", "Description"),
                        ]:
                            elem = root.find(tag, ns)
                            if elem is not None and elem.text:
                                result.append(f"| {label} | {elem.text.strip()} |")
                    except Exception as e:
                        result.append(f"| Error reading metadata | {e} |")

                # Pages
                page_files = sorted(
                    [n for n in namelist if "/pages/" in n.lower() and n.lower().endswith(".xml")]
                )
                result.append("")
                result.append(f"**Page count:** {len(page_files)}")

                # Extract shapes from each page
                ns_visio = {"v": "http://schemas.microsoft.com/office/visio/2012/main"}
                total_shapes = 0
                for pf in page_files[:20]:
                    try:
                        page_data = z.read(pf)
                        page_root = ET.fromstring(page_data)
                        shapes = page_root.findall(".//v:Shape", ns_visio)
                        total_shapes += len(shapes)
                    except Exception:
                        continue

                result.append(f"**Total shapes (sampled):** {total_shapes}")
                result.append("")

                # Shape details
                result.append("## Shapes (sampled from pages)")
                result.append("| Page | Shape ID | Name |")
                result.append("| --- | --- | --- |")
                shape_count = 0
                for pf in page_files[:20]:
                    page_name = os.path.basename(pf)
                    try:
                        page_data = z.read(pf)
                        page_root = ET.fromstring(page_data)
                        shapes = page_root.findall(".//v:Shape", ns_visio)
                        for shape in shapes[:30]:
                            sid = shape.get("ID", shape.get("id", ""))
                            name = shape.get("Name", shape.get("NameU", ""))
                            master = shape.get("Master", "")
                            display_name = name
                            # Try to find text content
                            text_elem = shape.find(".//v:Text", ns_visio)
                            if text_elem is not None:
                                text = "".join(text_elem.itertext()).strip()
                                if text:
                                    display_name = f"{name} -- {text[:60]}" if name else text[:60]
                            if master:
                                display_name += f" (Master: {master})"
                            result.append(f"| {page_name} | {sid} | {display_name} |")
                            shape_count += 1
                            if shape_count >= 100:
                                break
                    except Exception:
                        continue
                    if shape_count >= 100:
                        break

                if shape_count >= 100:
                    result.append(f"\n*(Showing first 100 shapes)*")

                return "\n".join(result)
        except zipfile.BadZipFile:
            return "Error: Not a valid Visio file (corrupt ZIP)."
        except Exception as e:
            return f"Error: Failed to parse Visio file: {e}"


@register_extractor
class ProjectExtractor(BaseExtractor):
    """Extracts metadata from Microsoft Project files (.mpp, .mpt, OLE2)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile

            if not olefile.isOleFile(file_path):
                return "Error: Not a valid Project file (not an OLE2 document)."
        except ImportError:
            return "Error: olefile library is not installed."

        try:
            ole = olefile.OleFileIO(file_path)
            result = [f"# Microsoft Project: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Format:** OLE2 Compound Document")
            result.append("")

            # Metadata
            meta = ole.get_metadata()
            result.append("## Metadata")
            result.append("| Property | Value |")
            result.append("| --- | --- |")
            for attr, label in [
                ("title", "Title"),
                ("subject", "Subject"),
                ("author", "Author"),
                ("last_saved_by", "Last Saved By"),
                ("create_time", "Created"),
                ("last_saved_time", "Last Modified"),
                ("num_pages", "Pages"),
                ("company", "Company"),
                ("manager", "Manager"),
                ("category", "Category"),
                ("keywords", "Keywords"),
                ("comments", "Comments"),
                ("creating_application", "Application"),
            ]:
                val = getattr(meta, attr, None)
                if val:
                    result.append(f"| {label} | {val} |")

            # Stream listing
            streams = _ole_stream_list(ole)
            result.append("")
            result.append(f"## Streams ({len(streams)})")
            result.append("| Stream Path | Size |")
            result.append("| --- | --- |")
            for path, size in streams[:100]:
                size_str = _format_size(size) if size >= 0 else "N/A"
                result.append(f"| {path} | {size_str} |")
            if len(streams) > 100:
                result.append(f"\n*(Showing first 100 of {len(streams)} streams)*")

            ole.close()
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Project file: {e}"


# ---------------------------------------------------------------------------
# Task 6: Binary parser
# ---------------------------------------------------------------------------


@register_extractor
class EtlExtractor(BaseExtractor):
    """Extracts metadata from Windows Event Trace Log files (.etl).

    Attempts python-etw for full parsing; falls back to manual header analysis.
    """

    # ETL magic: 0x00000000 at offset 0, followed by header fields
    # The real signature check is the LoggerName offset and version fields.
    ETL_HEADER_MIN_SIZE = 64

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as f:
                header = f.read(512)
        except Exception as e:
            return f"Error: Failed to read ETL file: {e}"

        if len(header) < self.ETL_HEADER_MIN_SIZE:
            return "Error: File too small to be a valid ETL file."

        result = [f"# Event Trace Log (ETL): `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")

        # Try python-etw first for structured parsing
        parsed_with_etw = False
        try:
            # python-etw provides event reading capabilities
            import etw

            result.append("## Parsing Method: python-etw")
            result.append("")

            event_count = 0
            event_types = {}
            sample_events = []

            with etw.ETW(file_path) as trace:
                for event in trace:
                    event_count += 1
                    provider = getattr(event, "provider_name", "Unknown")
                    event_types[provider] = event_types.get(provider, 0) + 1

                    if len(sample_events) < 20:
                        ts = getattr(event, "timestamp", "")
                        eid = getattr(event, "id", "")
                        level = getattr(event, "level", "")
                        sample_events.append({
                            "time": str(ts),
                            "provider": provider,
                            "id": str(eid),
                            "level": str(level),
                        })

                    if event_count >= 10000:
                        # Limit processing for very large ETL files
                        break

            parsed_with_etw = True
            result.append(f"**Events sampled:** {event_count:,}")
            result.append("")

            # Provider summary
            if event_types:
                result.append("## Event Providers")
                result.append("| Provider | Event Count |")
                result.append("| --- | --- |")
                for prov, cnt in sorted(event_types.items(), key=lambda x: -x[1])[:30]:
                    result.append(f"| {prov} | {cnt:,} |")
                if len(event_types) > 30:
                    result.append(f"\n*(Showing top 30 of {len(event_types)} providers)*")
                result.append("")

            # Sample events
            if sample_events:
                result.append("## Sample Events")
                result.append("| Time | Provider | Event ID | Level |")
                result.append("| --- | --- | --- | --- |")
                for ev in sample_events:
                    result.append(
                        f"| {ev['time'][:25]} | {ev['provider'][:40]} | {ev['id']} | {ev['level']} |"
                    )

        except ImportError:
            logger.info("python-etw not available; using header-only analysis.")
        except Exception as e:
            logger.warning(f"python-etw parsing failed: {e}")

        if not parsed_with_etw:
            result.extend(self._parse_header(header))

        return "\n".join(result)

    def _parse_header(self, header: bytes) -> list:
        """Manual binary header parsing for ETL files."""
        lines = []
        lines.append("## Parsing Method: Header-only analysis")
        lines.append("*(python-etw not available; showing header metadata)*")
        lines.append("")

        # ETL header structure (WMI_EVENT_TRACE_HEADER):
        # Offset 0x00: BufferSize (uint32) -- often 0 for the header marker
        # Offset 0x04: MajorVersion (uint8), MinorVersion (uint8), SubVersion (uint16)
        # Offset 0x08: ProviderVersion (uint32)
        # Offset 0x0C: NumberOfProcessors (uint32)
        # Offset 0x10: EndTime (FILETIME, 8 bytes)
        # Offset 0x18: TimerResolution (uint32)
        # Offset 0x1C: MaxFileSize (uint32)
        # Offset 0x20: LogFileMode (uint32)
        # Offset 0x24: BuffersWritten (uint32)
        # Offset 0x28: StartBuffers (uint32)
        # Offset 0x2C: PointerSize (uint32)
        # Offset 0x30: EventsLost (uint32)
        # Offset 0x34: CPUSpeed (uint32)
        # Offset 0x38: LoggerName (pointer/offset)
        # Offset 0x3C: LogFileName (pointer/offset)

        lines.append("## Header Fields")
        lines.append("| Offset | Field | Value |")
        lines.append("| --- | --- | --- |")

        try:
            buf_size = struct.unpack_from("<I", header, 0)[0]
            lines.append(f"| 0x00 | BufferSize | {buf_size} |")

            if len(header) >= 8:
                major = header[4]
                minor = header[5]
                sub_ver = struct.unpack_from("<H", header, 6)[0]
                lines.append(f"| 0x04 | Version | {major}.{minor}.{sub_ver} |")

            if len(header) >= 12:
                provider_ver = struct.unpack_from("<I", header, 8)[0]
                lines.append(f"| 0x08 | ProviderVersion | {provider_ver} |")

            if len(header) >= 16:
                num_cpus = struct.unpack_from("<I", header, 12)[0]
                lines.append(f"| 0x0C | NumberOfProcessors | {num_cpus} |")

            if len(header) >= 24:
                end_time_ft = struct.unpack_from("<Q", header, 16)[0]
                if end_time_ft > 0:
                    try:
                        from datetime import datetime

                        end_dt = datetime.fromtimestamp(
                            (end_time_ft - 116444736000000000) / 10000000
                        )
                        lines.append(f"| 0x10 | EndTime | {end_dt.strftime('%Y-%m-%d %H:%M:%S')} |")
                    except Exception:
                        lines.append(f"| 0x10 | EndTime | {end_time_ft} (raw FILETIME) |")

            if len(header) >= 32:
                timer_res = struct.unpack_from("<I", header, 24)[0]
                lines.append(f"| 0x18 | TimerResolution | {timer_res} |")

                max_file = struct.unpack_from("<I", header, 28)[0]
                lines.append(f"| 0x1C | MaxFileSize | {max_file} ({_format_size(max_file)}) |")

            if len(header) >= 40:
                log_mode = struct.unpack_from("<I", header, 32)[0]
                mode_desc = []
                if log_mode & 0x00000001:
                    mode_desc.append("FILE")
                if log_mode & 0x00000002:
                    mode_desc.append("REAL_TIME")
                if log_mode & 0x00000004:
                    mode_desc.append("PRIVATE")
                if log_mode & 0x00000008:
                    mode_desc.append("BUFFERING")
                mode_str = " | ".join(mode_desc) if mode_desc else f"0x{log_mode:08X}"
                lines.append(f"| 0x20 | LogFileMode | {mode_str} |")

                buf_written = struct.unpack_from("<I", header, 36)[0]
                lines.append(f"| 0x24 | BuffersWritten | {buf_written:,} |")

            if len(header) >= 48:
                start_bufs = struct.unpack_from("<I", header, 40)[0]
                lines.append(f"| 0x28 | StartBuffers | {start_bufs} |")

                ptr_size = struct.unpack_from("<I", header, 44)[0]
                lines.append(f"| 0x2C | PointerSize | {ptr_size} |")

            if len(header) >= 56:
                events_lost = struct.unpack_from("<I", header, 48)[0]
                lines.append(f"| 0x30 | EventsLost | {events_lost:,} |")

                cpu_speed = struct.unpack_from("<I", header, 52)[0]
                lines.append(f"| 0x34 | CPUSpeed | {cpu_speed} MHz |")

        except Exception as e:
            lines.append(f"| - | Parse Error | {e} |")

        lines.append("")
        lines.append("## Raw Header (hex)")
        lines.append("```")
        lines.append(header[:128].hex(" "))
        lines.append("```")

        return lines
