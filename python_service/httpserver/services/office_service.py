"""
Office Document Parsing Service.

Provides parsing capabilities for Office documents:
- DOCX/DOC (Word)
- XLSX/XLS (Excel)
- PPTX/PPT (PowerPoint)

Returns content as Markdown text for forensic analysis.
"""

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class OfficeService:
    """Service for parsing Office documents."""

    def __init__(self):
        """Initialize the Office parsing service."""
        pass

    async def parse_file(self, file_path: str) -> str:
        """
        Parse an Office file and return its content as Markdown.

        Args:
            file_path: Absolute path to the Office file.

        Returns:
            Extracted text content in Markdown format.

        Raises:
            ValueError: If file type is not supported.
            FileNotFoundError: If file does not exist.
        """
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        suffix = path.suffix.lower()

        # The concrete parsers (python-docx / openpyxl / python-pptx /
        # subprocess) are synchronous and can take seconds on large files;
        # offload them to a worker thread so the async event loop is not
        # blocked.
        if suffix == ".docx":
            return await asyncio.to_thread(self._parse_docx, file_path)
        elif suffix == ".doc":
            return await asyncio.to_thread(self._parse_doc, file_path)
        elif suffix == ".xlsx":
            return await asyncio.to_thread(self._parse_xlsx, file_path)
        elif suffix == ".xls":
            return await asyncio.to_thread(self._parse_xls, file_path)
        elif suffix == ".pptx":
            return await asyncio.to_thread(self._parse_pptx, file_path)
        elif suffix == ".ppt":
            return await asyncio.to_thread(self._parse_ppt, file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

    def _parse_docx(self, file_path: str) -> str:
        """Parse DOCX file using python-docx (paragraphs + tables)."""
        try:
            from docx import Document
            from docx.oxml.ns import qn
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            document = Document(file_path)
            result: list[str] = []

            def render_table(table: Table) -> None:
                table_rows = []
                for row in table.rows:
                    cells = [
                        cell.text.replace("|", "\\|").replace("\n", " ")
                        for cell in row.cells
                    ]
                    table_rows.append(cells)
                if table_rows:
                    result.append("| " + " | ".join(table_rows[0]) + " |")
                    result.append("|" + "|".join(["---"] * len(table_rows[0])) + "|")
                    for row in table_rows[1:]:
                        while len(row) < len(table_rows[0]):
                            row.append("")
                        result.append("| " + " | ".join(row[: len(table_rows[0])]) + " |")
                    result.append("")

            def heading_prefix(paragraph: Paragraph) -> str:
                # Style resolution can fail on documents with exotic or
                # missing style definitions; treat those as plain text.
                try:
                    style = (paragraph.style.name or "").lower()
                except Exception:
                    return ""
                if style.startswith("title"):
                    return "# "
                if style.startswith("heading"):
                    digits = "".join(ch for ch in style if ch.isdigit())
                    depth = min(int(digits) if digits else 1, 6)
                    return "#" * depth + " "
                return ""

            # Iterate the document body in order so tables stay in place
            # relative to the surrounding paragraphs.
            for element in document.element.body.iterchildren():
                if element.tag == qn("w:p"):
                    paragraph = Paragraph(element, document)
                    text = (paragraph.text or "").strip()
                    if text:
                        result.append(f"{heading_prefix(paragraph)}{text}\n")
                elif element.tag == qn("w:tbl"):
                    render_table(Table(element, document))

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Error parsing DOCX {file_path}: {e}")
            return f"Error parsing DOCX file: {e}"

    def _parse_doc(self, file_path: str) -> str:
        """Parse legacy DOC file using antiword (text extraction)."""
        try:
            # Capture bytes: antiword output on legacy docs can contain bytes
            # that are not valid UTF-8 even with the UTF-8 mapping.
            result = subprocess.run(
                ["antiword", "-m", "UTF-8", file_path],
                capture_output=True,
                timeout=60,
            )

            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="replace").strip()
                logger.warning(f"antiword error: {stderr}")
                return f"Error parsing DOC: {stderr}"

            return result.stdout.decode("utf-8", errors="replace").strip()

        except FileNotFoundError:
            logger.error("antiword not found. Install the antiword package.")
            return "Error: antiword not found. Please install the antiword package."
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout parsing DOC {file_path}")
            return "Error: Timeout parsing DOC file."
        except Exception as e:
            logger.error(f"Error parsing DOC {file_path}: {e}")
            return f"Error parsing DOC file: {e}"

    def _parse_xlsx(self, file_path: str) -> str:
        """Parse XLSX file using openpyxl."""
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path, read_only=True, data_only=True)
            result = []

            for sheet_name in wb.sheetnames:
                sheet = wb[sheet_name]
                result.append(f"## Sheet: {sheet_name}\n")

                # Build table rows
                rows = []
                for row in sheet.iter_rows():
                    cells = []
                    for cell in row:
                        value = cell.value if cell.value is not None else ""
                        cells.append(str(value).replace("|", "\\|"))
                    if any(cells):  # Skip empty rows
                        rows.append(cells)

                if rows:
                    # Create markdown table
                    if rows:
                        # Header row
                        result.append("| " + " | ".join(rows[0]) + " |")
                        result.append("|" + "|".join(["---"] * len(rows[0])) + "|")
                        # Data rows
                        for row in rows[1:]:
                            # Pad row to match header length
                            while len(row) < len(rows[0]):
                                row.append("")
                            result.append("| " + " | ".join(row[:len(rows[0])]) + " |")
                    result.append("")

            wb.close()
            return "\n".join(result)

        except Exception as e:
            logger.error(f"Error parsing XLSX {file_path}: {e}")
            return f"Error parsing XLSX file: {e}"

    def _parse_xls(self, file_path: str) -> str:
        """Parse XLS file using xlrd."""
        try:
            import xlrd

            wb = xlrd.open_workbook(file_path)
            result = []

            for sheet_idx in range(wb.nsheets):
                sheet = wb.sheet_by_index(sheet_idx)
                result.append(f"## Sheet: {sheet.name}\n")

                rows = []
                for row_idx in range(sheet.nrows):
                    cells = []
                    for col_idx in range(sheet.ncols):
                        value = sheet.cell_value(row_idx, col_idx)
                        cells.append(str(value).replace("|", "\\|"))
                    if any(cells):
                        rows.append(cells)

                if rows:
                    # Create markdown table
                    result.append("| " + " | ".join(rows[0]) + " |")
                    result.append("|" + "|".join(["---"] * len(rows[0])) + "|")
                    for row in rows[1:]:
                        while len(row) < len(rows[0]):
                            row.append("")
                        result.append("| " + " | ".join(row[:len(rows[0])]) + " |")
                    result.append("")

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Error parsing XLS {file_path}: {e}")
            return f"Error parsing XLS file: {e}"

    def _parse_pptx(self, file_path: str) -> str:
        """Parse PPTX file using python-pptx."""
        try:
            from pptx import Presentation

            prs = Presentation(file_path)
            result = []

            for slide_num, slide in enumerate(prs.slides, 1):
                result.append(f"## Slide {slide_num}\n")

                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        # Check if it's a title
                        if shape.is_placeholder and hasattr(shape, "placeholder_format"):
                            ph_type = shape.placeholder_format.type
                            # Title placeholder types: 1 = CENTER_TITLE, 3 = TITLE
                            if ph_type in [1, 3]:
                                result.append(f"### {shape.text.strip()}\n")
                            else:
                                result.append(f"{shape.text.strip()}\n")
                        else:
                            result.append(f"{shape.text.strip()}\n")

                    # Handle tables in slides
                    if shape.has_table:
                        table = shape.table
                        table_rows = []
                        for row in table.rows:
                            cells = []
                            for cell in row.cells:
                                text = cell.text.replace("|", "\\|").replace("\n", " ")
                                cells.append(text)
                            table_rows.append(cells)

                        if table_rows:
                            result.append("| " + " | ".join(table_rows[0]) + " |")
                            result.append("|" + "|".join(["---"] * len(table_rows[0])) + "|")
                            for row in table_rows[1:]:
                                while len(row) < len(table_rows[0]):
                                    row.append("")
                                result.append("| " + " | ".join(row[:len(table_rows[0])]) + " |")
                            result.append("")

                result.append("")

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Error parsing PPTX {file_path}: {e}")
            return f"Error parsing PPTX file: {e}"

    def _parse_ppt(self, file_path: str) -> str:
        """Parse PPT file: catppt (catdoc package) if available, otherwise a
        pure-Python text-atom walk of the PowerPoint 97 stream."""
        try:
            result = subprocess.run(
                ["catppt", file_path],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.warning(f"catppt error: {result.stderr}")
                if result.stderr:
                    return f"Error parsing PPT: {result.stderr}"
                return self._parse_ppt_ole(file_path)

            # Format output as markdown
            lines = result.stdout.strip().split("\n")
            md_lines = []
            current_slide = 0

            for line in lines:
                if line.startswith("Slide"):
                    current_slide += 1
                    md_lines.append(f"\n## Slide {current_slide}\n")
                elif line.strip():
                    md_lines.append(line.strip())

            return "\n".join(md_lines) if md_lines else result.stdout

        except FileNotFoundError:
            # catppt not installed — fall back to the built-in OLE extractor.
            return self._parse_ppt_ole(file_path)
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout parsing PPT {file_path}")
            return "Error: Timeout parsing PPT file."
        except Exception as e:
            logger.error(f"Error parsing PPT {file_path}: {e}")
            return f"Error parsing PPT file: {e}"

    # PowerPoint binary record atom types carrying text.
    _PPT_TEXT_CHARS_ATOM = 0x0FA0  # TextCharsAtom, UTF-16LE
    _PPT_TEXT_BYTES_ATOM = 0x0FA8  # TextBytesAtom, 8-bit codepage text

    def _parse_ppt_ole(self, file_path: str) -> str:
        """Extract text from a PowerPoint 97-2003 stream via olefile.

        Walks the record tree of the "PowerPoint Document" stream and
        concatenates every TextCharsAtom/TextBytesAtom in document order.
        """
        try:
            import olefile
            import struct

            with olefile.OleFileIO(file_path) as ole:
                if not ole.exists("PowerPoint Document"):
                    return "Error parsing PPT: no PowerPoint Document stream found."
                stream = ole.openstream("PowerPoint Document").read()

            texts: list[str] = []

            def walk_records(data: bytes, start: int, end: int, depth: int) -> None:
                pos = start
                while pos + 8 <= end:
                    ver_instance, rec_type, rec_len = struct.unpack_from("<HHI", data, pos)
                    body_start = pos + 8
                    body_end = min(body_start + rec_len, end)
                    if ver_instance & 0xF == 0xF and depth < 10:
                        # Container record: recurse into children.
                        walk_records(data, body_start, body_end, depth + 1)
                    elif rec_type == self._PPT_TEXT_CHARS_ATOM:
                        raw = data[body_start:body_end]
                        texts.append(raw.decode("utf-16-le", errors="replace"))
                    elif rec_type == self._PPT_TEXT_BYTES_ATOM:
                        raw = data[body_start:body_end]
                        for encoding in ("gbk", "cp1252"):
                            try:
                                texts.append(raw.decode(encoding))
                                break
                            except UnicodeDecodeError:
                                continue
                        else:
                            texts.append(raw.decode("utf-8", errors="replace"))
                    pos = body_end

            walk_records(stream, 0, len(stream), 0)
            paragraphs = []
            for text in texts:
                for line in text.replace("\x0b", "\n").split("\r"):
                    line = line.strip()
                    if line:
                        paragraphs.append(line)
            if not paragraphs:
                return "Error parsing PPT: no text found."
            return "\n\n".join(paragraphs)

        except Exception as e:
            logger.error(f"Error parsing PPT {file_path}: {e}")
            return f"Error parsing PPT file: {e}"


# Global service instance
_office_service: Optional[OfficeService] = None


def get_office_service() -> OfficeService:
    """Get the global Office service instance."""
    global _office_service
    if _office_service is None:
        _office_service = OfficeService()
    return _office_service
