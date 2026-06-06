"""Extended office document extractors: RTF, ODT, ODS, ODP, iWork."""
import logging
import os
import zipfile

try:
    from defusedxml import ElementTree as ET
except ImportError:
    raise ImportError("defusedxml is required for XML parsing. Install with: pip install defusedxml")

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


@register_extractor
class RtfExtractor(BaseExtractor):
    """Extracts text from RTF (Rich Text Format) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError:
            return "Error: striprtf library is not installed."

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                rtf_content = f.read()
            text = rtf_to_text(rtf_content)

            result = [f"# RTF Document: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {os.path.getsize(file_path):,} bytes")
            result.append("")
            result.append("## Content")
            if text.strip():
                if len(text) > 15000:
                    text = text[:15000] + "\n\n... (truncated)"
                result.append(text)
            else:
                result.append("*(No text content found)*")
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse RTF file: {e}"


def _extract_odf_text(file_path: str) -> str:
    """Extract text from ODF files (ODT/ODS/ODP) which are ZIP+XML."""
    texts = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            if 'content.xml' in z.namelist():
                content = z.read('content.xml')
                root = ET.fromstring(content)
                ns = {'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0'}
                for elem in root.iter():
                    if elem.text and elem.text.strip():
                        texts.append(elem.text.strip())
    except Exception as e:
        logger.warning(f"Error extracting ODF text: {e}")
    return '\n'.join(texts)


def _extract_odf_sheets(file_path: str) -> list:
    """Extract sheet data from ODS files."""
    sheets = []
    try:
        with zipfile.ZipFile(file_path, 'r') as z:
            if 'content.xml' in z.namelist():
                content = z.read('content.xml')
                root = ET.fromstring(content)
                ns = {
                    'table': 'urn:oasis:names:tc:opendocument:xmlns:table:1.0',
                    'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
                }
                for table in root.findall('.//table:table', ns):
                    name = table.get('{urn:oasis:names:tc:opendocument:xmlns:table:1.0}name', 'Sheet')
                    rows = []
                    for row in table.findall('table:table-row', ns):
                        cells = []
                        for cell in row.findall('table:table-cell', ns):
                            text_parts = []
                            for p in cell.findall('.//text:p', ns):
                                if p.text:
                                    text_parts.append(p.text.strip())
                            cells.append(' '.join(text_parts) if text_parts else '')
                        if any(c for c in cells):
                            rows.append(cells)
                    if rows:
                        sheets.append((name, rows))
    except Exception as e:
        logger.warning(f"Error extracting ODS sheets: {e}")
    return sheets


@register_extractor
class OdtExtractor(BaseExtractor):
    """Extracts text from ODT (OpenDocument Text) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            text = _extract_odf_text(file_path)
            result = [f"# ODT Document: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {os.path.getsize(file_path):,} bytes")
            result.append("")
            result.append("## Content")
            if text:
                if len(text) > 15000:
                    text = text[:15000] + "\n\n... (truncated)"
                result.append(text)
            else:
                result.append("*(No text content found)*")
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ODT file: {e}"


@register_extractor
class OdsExtractor(BaseExtractor):
    """Extracts data from ODS (OpenDocument Spreadsheet) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            sheets = _extract_odf_sheets(file_path)
            result = [f"# ODS Spreadsheet: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {os.path.getsize(file_path):,} bytes")
            result.append(f"**Sheets:** {len(sheets)}")
            result.append("")

            if not sheets:
                result.append("*(No data found)*")
                return "\n".join(result)

            for name, rows in sheets:
                result.append(f"## Sheet: {name}")
                if rows:
                    # Header row
                    header = rows[0]
                    result.append("| " + " | ".join(str(c) for c in header) + " |")
                    result.append("| " + " | ".join(["---"] * len(header)) + " |")
                    for row in rows[1:min(51, len(rows))]:
                        safe_row = [str(c).replace('|', '\\|')[:100] for c in row]
                        result.append("| " + " | ".join(safe_row) + " |")
                    if len(rows) > 51:
                        result.append(f"\n*(Showing first 50 of {len(rows)} rows)*")
                result.append("")
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ODS file: {e}"


@register_extractor
class OdpExtractor(BaseExtractor):
    """Extracts text from ODP (OpenDocument Presentation) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            text = _extract_odf_text(file_path)
            result = [f"# ODP Presentation: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {os.path.getsize(file_path):,} bytes")
            result.append("")
            result.append("## Content")
            if text:
                if len(text) > 15000:
                    text = text[:15000] + "\n\n... (truncated)"
                result.append(text)
            else:
                result.append("*(No text content found)*")
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ODP file: {e}"


@register_extractor
class IworkExtractor(BaseExtractor):
    """Extracts content from Apple iWork files (Pages, Numbers, Keynote)."""

    IWA_MAGIC = b'\x00\x00\x00\x00'  # IWA (iWork Archive) format

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        type_name = {'.pages': 'Pages Document', '.numbers': 'Numbers Spreadsheet', '.key': 'Keynote Presentation'}.get(ext, 'iWork File')

        try:
            with zipfile.ZipFile(file_path, 'r') as z:
                result = [f"# {type_name}: `{os.path.basename(file_path)}`"]
                result.append(f"**File Size:** {os.path.getsize(file_path):,} bytes")
                result.append(f"**Format:** iWork (ZIP-based)")
                result.append("")

                # List contents
                result.append("## Archive Contents")
                result.append("| File | Size |")
                result.append("| --- | --- |")
                for info in z.infolist()[:50]:
                    result.append(f"| {info.filename} | {info.file_size:,} bytes |")

                # Try to extract protobuf metadata
                result.append("")
                result.append("## Metadata")
                result.append("*iWork files use Protocol Buffers (IWA format). Full text extraction requires specialized iWork parser.*")

                return "\n".join(result)
        except zipfile.BadZipFile:
            return f"Error: Not a valid iWork file (not a ZIP archive)"
        except Exception as e:
            return f"Error: Failed to parse iWork file: {e}"
