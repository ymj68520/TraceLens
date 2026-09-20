"""
Office Document Parsing Service.

Provides parsing capabilities for Office documents:
- DOCX/DOC (Word)
- XLSX/XLS (Excel)
- PPTX/PPT (PowerPoint)

Returns content as Markdown text for forensic analysis, plus structured
slide/sheet data for richer client-side previews.
"""

import asyncio
import base64
import io
import logging
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class OfficeService:
    """Service for parsing Office documents."""

    # Content signatures the dedicated parsers require. Recovered/deleted
    # files frequently carry data that does not match their recorded
    # extension, so parse_file sniffs before dispatching.
    _MAGIC_BY_SUFFIX = {
        ".docx": b"PK\x03\x04",
        ".xlsx": b"PK\x03\x04",
        ".pptx": b"PK\x03\x04",
        ".doc": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        ".xls": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
        ".ppt": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    }

    # Cap for the text fallback: recovered files can be huge; a preview does
    # not need more than the first megabyte.
    _TEXT_FALLBACK_LIMIT = 1024 * 1024

    # Limits for the structured slide/sheet extraction used by the rich
    # preview: base64 images inflate quickly and the response must stay
    # servable for preview-sized requests.
    _SLIDE_MAX_IMAGES = 12
    _SLIDE_MAX_IMAGE_BYTES = 5 * 1024 * 1024
    _SLIDE_IMAGE_MAX_DIM = 1600
    _SLIDE_IMAGE_KEEP_BYTES = 400 * 1024
    _SHEET_MAX_ROWS = 500
    _SHEET_MAX_COLS = 64

    # Legacy .doc files are often pure screenshot collections (the text is
    # inside the images), so extract more images and tolerate a bigger
    # payload than the per-slide budget.
    _DOC_MAX_IMAGES = 50
    _DOC_IMAGE_MAX_DIM = 1100
    _DOC_IMAGE_JPEG_QUALITY = 72
    _DOC_IMAGES_BUDGET_BYTES = 12 * 1024 * 1024
    _DOC_MIN_IMAGE_BYTES = 2048

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

        # Content sniffing: when the leading bytes do not match the expected
        # container format the dedicated parsers would just fail (e.g.
        # antiword: "not a Word Document"). Show recovered text instead when
        # the bytes are decodable, or explain that the content does not match.
        expected_magic = self._MAGIC_BY_SUFFIX.get(suffix)
        if expected_magic is not None:
            with open(file_path, "rb") as handle:
                head = handle.read(len(expected_magic))
            if head and not head.startswith(expected_magic):
                return await asyncio.to_thread(
                    self._parse_mismatched_content, file_path, suffix
                )

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

    async def extract_slides(self, file_path: str) -> list[dict]:
        """Structured slide data (title/texts/images/table) for PPTX."""
        suffix = Path(file_path).suffix.lower()
        if suffix != ".pptx":
            return []
        return await asyncio.to_thread(self._slides_pptx, file_path)

    async def extract_sheets(self, file_path: str) -> list[dict]:
        """Structured sheet data (name + cell rows) for XLSX/XLS."""
        suffix = Path(file_path).suffix.lower()
        if suffix == ".xlsx":
            return await asyncio.to_thread(self._sheets_xlsx, file_path)
        if suffix == ".xls":
            return await asyncio.to_thread(self._sheets_xls, file_path)
        return []

    async def extract_doc_images(self, file_path: str) -> list[str]:
        """Embedded pictures of a legacy .doc as data URIs, in stream order."""
        if Path(file_path).suffix.lower() != ".doc":
            return []
        return await asyncio.to_thread(self._doc_images, file_path)

    def _doc_images(self, file_path: str) -> list[str]:
        """Carve PNG/JPEG blips out of the .doc OLE streams.

        antiword renders embedded pictures as [PIC] markers in document
        order; the carved images follow the same Data-stream order, so the
        web preview can interleave them back into the text.
        """
        try:
            import olefile

            with olefile.OleFileIO(file_path) as ole:
                images: list[str] = []
                budget = self._DOC_IMAGES_BUDGET_BYTES
                for entry in ole.listdir():
                    stream = "/".join(entry)
                    try:
                        raw = ole.openstream(entry).read()
                    except Exception:
                        continue
                    for blob in self._carve_images(raw):
                        uri = self._blob_data_uri(blob)
                        if uri is None:
                            continue
                        images.append(uri)
                        budget -= len(uri)
                        if (
                            len(images) >= self._DOC_MAX_IMAGES
                            or budget <= 0
                        ):
                            return images
                return images
        except Exception as e:
            logger.error(f"Error extracting images from {file_path}: {e}")
            return []

    @staticmethod
    def _carve_images(raw: bytes) -> list[bytes]:
        """Extract verified, deduplicated PNG/JPEG blobs from raw bytes."""
        import hashlib
        import io as _io

        from PIL import Image

        starts: list[tuple[str, int]] = []
        i = 0
        png_sig = b"\x89PNG\r\n\x1a\n"
        while i < len(raw) - 8:
            if raw[i : i + 3] == b"\xff\xd8\xff":
                starts.append(("jpeg", i))
                i += 3
            elif raw[i : i + 8] == png_sig:
                starts.append(("png", i))
                i += 8
            else:
                i += 1

        blobs: list[bytes] = []
        seen: set[str] = set()
        for kind, start in starts:
            if kind == "png":
                end = raw.find(b"IEND", start)
                if end == -1:
                    continue
                blob = raw[start : end + 8]
            else:
                # JPEGs may contain inner FFD9 markers (EXIF thumbnails);
                # accept the first end position that yields a parseable image.
                end = start
                while True:
                    end = raw.find(b"\xff\xd9", end + 3)
                    if end == -1:
                        break
                    blob = raw[start : end + 2]
                    try:
                        Image.open(_io.BytesIO(blob)).verify()
                        break
                    except Exception:
                        continue
                else:
                    continue
            if len(blob) < 2048:
                continue
            digest = hashlib.md5(blob).hexdigest()
            if digest in seen:
                continue
            try:
                Image.open(_io.BytesIO(blob)).verify()
            except Exception:
                continue
            seen.add(digest)
            blobs.append(blob)
        return blobs

    def _blob_data_uri(self, blob: bytes) -> Optional[str]:
        """Downscale when oversized and encode an image blob as a data URI."""
        from PIL import Image

        try:
            with Image.open(io.BytesIO(blob)) as img:
                img.load()
                needs_resize = max(img.size) > self._DOC_IMAGE_MAX_DIM
                if len(blob) <= self._SLIDE_IMAGE_KEEP_BYTES and not needs_resize:
                    encoded = base64.b64encode(blob).decode("ascii")
                    mime = Image.MIME.get(img.format, "image/png")
                    return f"data:{mime};base64,{encoded}"
                if img.mode not in ("RGB", "L"):
                    img = img.convert("RGB")
                if needs_resize:
                    img.thumbnail((self._DOC_IMAGE_MAX_DIM, self._DOC_IMAGE_MAX_DIM))
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self._DOC_IMAGE_JPEG_QUALITY)
        except Exception:
            return None
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _slides_pptx(self, file_path: str) -> list[dict]:
        """Walk PPTX shapes into plain dicts consumable by the web preview."""
        try:
            from pptx import Presentation
            from pptx.enum.shapes import MSO_SHAPE_TYPE

            prs = Presentation(file_path)
            slides: list[dict] = []
            for slide_doc in prs.slides:
                slide: dict = {"title": "", "texts": [], "images": [], "table": None}
                try:
                    title_shape = slide_doc.shapes.title
                    if title_shape is not None and title_shape.has_text_frame:
                        slide["title"] = title_shape.text.strip()
                except Exception:
                    pass

                def walk(shapes) -> None:
                    for shape in shapes:
                        try:
                            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                                walk(shape.shapes)
                                continue
                            # Pictures hide behind several shape kinds: real
                            # Picture shapes but also OBJECT placeholders
                            # holding an image (PlaceholderPicture exposes
                            # .image the same way).
                            if hasattr(shape, "image"):
                                uri = self._picture_data_uri(shape)
                                if uri and len(slide["images"]) < self._SLIDE_MAX_IMAGES:
                                    slide["images"].append(uri)
                                continue
                            if getattr(shape, "has_table", False) and slide["table"] is None:
                                slide["table"] = [
                                    [cell.text.replace("\n", " ") for cell in row.cells]
                                    for row in shape.table.rows
                                ]
                                continue
                            if shape.has_text_frame:
                                text = shape.text.strip()
                                if text and text != slide["title"]:
                                    slide["texts"].append(text)
                        except Exception:
                            continue

                walk(slide_doc.shapes)
                slides.append(slide)
            return slides
        except Exception as e:
            logger.error(f"Error extracting slides from {file_path}: {e}")
            return []

    def _picture_data_uri(self, picture) -> Optional[str]:
        """Base64 data URI for an embedded picture, downscaled when huge."""
        image = picture.image
        blob = image.blob
        if len(blob) > self._SLIDE_MAX_IMAGE_BYTES:
            return None

        content_type = image.content_type or "image/png"
        if len(blob) <= self._SLIDE_IMAGE_KEEP_BYTES:
            encoded = base64.b64encode(blob).decode("ascii")
            return f"data:{content_type};base64,{encoded}"

        # Oversized: downscale and re-encode as JPEG to keep responses small.
        from PIL import Image

        with Image.open(io.BytesIO(blob)) as img:
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            if max(img.size) > self._SLIDE_IMAGE_MAX_DIM:
                img.thumbnail((self._SLIDE_IMAGE_MAX_DIM, self._SLIDE_IMAGE_MAX_DIM))
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
        encoded = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"

    def _sheets_xlsx(self, file_path: str) -> list[dict]:
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path, read_only=True, data_only=True)
            sheets = []
            for name in wb.sheetnames:
                ws = wb[name]
                rows = []
                for row in ws.iter_rows(
                    max_row=self._SHEET_MAX_ROWS,
                    max_col=self._SHEET_MAX_COLS,
                    values_only=True,
                ):
                    cells = ["" if v is None else str(v) for v in row]
                    # read_only mode pads rows to max_col; drop the padding.
                    while cells and cells[-1] == "":
                        cells.pop()
                    rows.append(cells)
                sheets.append({"name": name, "data": rows, "total_rows": len(rows)})
            wb.close()
            return sheets
        except Exception as e:
            logger.error(f"Error extracting sheets from {file_path}: {e}")
            return []

    def _sheets_xls(self, file_path: str) -> list[dict]:
        try:
            import xlrd

            wb = xlrd.open_workbook(file_path)
            sheets = []
            for idx in range(wb.nsheets):
                sheet = wb.sheet_by_index(idx)
                rows = []
                for r in range(min(sheet.nrows, self._SHEET_MAX_ROWS)):
                    rows.append(
                        [
                            str(sheet.cell_value(r, c))
                            for c in range(min(sheet.ncols, self._SHEET_MAX_COLS))
                        ]
                    )
                sheets.append({"name": sheet.name, "data": rows, "total_rows": sheet.nrows})
            return sheets
        except Exception as e:
            logger.error(f"Error extracting sheets from {file_path}: {e}")
            return []

    def _parse_mismatched_content(self, file_path: str, suffix: str) -> str:
        """Fallback for files whose content does not match their extension.

        Typical for deleted files recovered from unallocated space: the
        carved bytes can be anything, often a readable fragment followed by
        overwritten garbage. Show the readable part when there is one and
        explain otherwise.
        """
        with open(file_path, "rb") as handle:
            raw = handle.read(self._TEXT_FALLBACK_LIMIT)

        if not raw.strip():
            return (
                f"文件扩展名为 {suffix},但内容为空或全为空白"
                "(可能为已删除文件的残留数据),无法预览。"
            )

        note = f"[注意] 文件内容与 {suffix} 格式不符(可能为已删除/残留数据)。"

        # 1. Whole buffer decodes cleanly in a common encoding.
        for encoding in ("utf-8", "gbk", "cp1252"):
            try:
                text = raw.decode(encoding)
            except UnicodeDecodeError:
                continue
            if text.count("\ufffd") <= len(text) * 0.1 and self._is_mostly_printable(text):
                return f"{note}以下为按文本提取的内容:\n\n{text}"

        # 2. Mostly textual with a few stray bytes: show the whole thing.
        text = raw.decode("utf-8", errors="replace")
        if (
            text.count("\ufffd") <= len(text) * 0.1
            and self._is_mostly_printable(text)
        ):
            return f"{note}以下为按文本提取的内容:\n\n{text}"

        # 3. Readable prefix followed by garbage: preview the prefix.
        encoding, usable = self._longest_decodable_prefix(raw)
        if usable >= 32:
            prefix = raw[:usable].decode(encoding, errors="replace")
            if self._is_mostly_printable(prefix):
                truncation = (
                    f"仅前 {usable} 字节可读,其余部分已损坏或被覆盖:"
                    if usable < len(raw)
                    else "以下为按文本提取的内容:"
                )
                return f"{note}{truncation}\n\n{prefix}"

        # 4. Nothing readable. Deleted files frequently carve back as
        # mostly-zeroed clusters (the data was overwritten before recovery);
        # say so with the numbers instead of a bare failure.
        zero_ratio = raw.count(0) / len(raw)
        if zero_ratio >= 0.3:
            return (
                f"该已删除文件仅恢复出 {len(raw)} 字节,其中 {zero_ratio:.0%} 为空字节,"
                "其余为覆盖后的无结构数据,原始内容已无法恢复,故无法预览。"
            )

        return (
            f"文件扩展名为 {suffix},但内容与该格式不符"
            "(可能为已删除文件的残留数据),无法提取可读文本。"
        )

    @staticmethod
    def _is_mostly_printable(text: str) -> bool:
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
        return printable >= len(text) * 0.7

    @staticmethod
    def _longest_decodable_prefix(raw: bytes) -> tuple[str, int]:
        """Longest byte prefix that decodes cleanly in a common encoding."""
        best: tuple[str, int] = ("utf-8", 0)
        for encoding in ("utf-8", "gbk", "cp1252"):
            try:
                raw.decode(encoding)
            except UnicodeDecodeError as exc:
                if exc.start > best[1]:
                    best = (encoding, exc.start)
            else:
                return encoding, len(raw)
        return best

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

            # antiword marks embedded pictures with a literal [PIC]; present
            # them in Chinese so previews read consistently.
            text = result.stdout.decode("utf-8", errors="replace").strip()
            return re.sub(r"\[PIC\]", "[图片]", text, flags=re.IGNORECASE)

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
