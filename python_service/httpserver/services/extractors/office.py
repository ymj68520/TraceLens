import logging
import re

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

@register_extractor
class PDFExtractor(BaseExtractor):
    async def extract_to_markdown(self, file_path: str) -> str:
        import fitz  # PyMuPDF
        
        try:
            doc = fitz.open(file_path)
            result = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()
                if text.strip():
                    result.append(f"## Page {page_num + 1}\n\n{text}\n")
                    
            doc.close()
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing PDF {file_path}: {e}")
            raise

@register_extractor
class DocxExtractor(BaseExtractor):
    """DOCX extractor covering more than body paragraphs.

    python-docx's ``doc.paragraphs`` silently drops tables, headers/footers
    and text-box content — table-based scam scripts (话术) come out empty.
    This walker keeps document order for paragraphs and tables, appends
    section headers/footers and text-box runs, and falls back to OCR of the
    embedded package images when the text layer is too thin (image-only
    DOCX produced by screenshots).
    """

    async def extract_to_markdown(self, file_path: str) -> str:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._extract_sync, file_path)
        except Exception as e:
            logger.error(f"Error parsing DOCX {file_path}: {e}")
            raise

    @staticmethod
    def _is_encrypted_ole(file_path: str) -> bool:
        try:
            with open(file_path, "rb") as fh:
                return fh.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
        except OSError:
            return False

    def _extract_sync(self, file_path: str) -> str:
        import hashlib
        import zipfile

        import docx
        from docx.document import Document as _Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        from .doc_ocr import (
            EmbeddedImage,
            MIN_MEANINGFUL_TEXT_CHARS,
            build_image_ocr_markdown,
        )

        # WPS/Word "encrypt with password" output keeps the .docx name but is
        # an OLE compound file; python-docx would raise PackageNotFoundError.
        # Surface a forensic diagnostic instead of an opaque crash.
        if self._is_encrypted_ole(file_path):
            logger.warning(f"{file_path} is an encrypted Office compound document despite its extension")
            return (
                "[该文件虽使用 Office 文档扩展名，实际是加密的 Office 复合文档"
                "（设置过打开密码或权限限制），无法提取正文内容；"
                "文件大小见文件元数据，需先解密才能分析。]"
            )

        doc = docx.Document(file_path)

        def iter_block_items(parent):
            body = parent.element.body if isinstance(parent, _Document) else parent._element
            for child in body.iterchildren():
                if child.tag == qn("w:p"):
                    yield Paragraph(child, parent)
                elif child.tag == qn("w:tbl"):
                    yield Table(child, parent)

        result: list = []

        for block in iter_block_items(doc):
            if isinstance(block, Paragraph):
                text = block.text.strip()
                if text:
                    style = (block.style.name or "").lower() if block.style is not None else ""
                    if style.startswith("heading"):
                        try:
                            level = int(style.split()[-1])
                        except ValueError:
                            level = 2
                        result.append(f"{'#' * min(level, 6)} {text}\n")
                    else:
                        result.append(f"{text}\n")
            else:
                result.append(self._table_to_markdown(block))

        headers_footers: list = []
        for section in doc.sections:
            for container, label in (
                (section.header, "页眉"),
                (section.footer, "页脚"),
            ):
                if container is None:
                    continue
                lines = [p.text.strip() for p in container.paragraphs if p.text.strip()]
                if lines:
                    headers_footers.append(f"【{label}】" + " / ".join(lines))
        if headers_footers:
            result.append("\n".join(headers_footers) + "\n")

        # Text-box content lives nested inside runs and never reaches
        # doc.paragraphs; sweep the raw XML for it.
        textbox_lines: list = []
        for txbx in doc.element.body.iter(qn("w:txbxContent")):
            for t in txbx.iter(qn("w:t")):
                text = (t.text or "").strip()
                if text:
                    textbox_lines.append(text)
        if textbox_lines:
            result.append("【文本框】\n" + "\n".join(textbox_lines) + "\n")

        markdown = "\n".join(part for part in result if part and part.strip())

        # Same bar as the .doc gate: whitespace-free character count, not
        # raw markdown length.
        if len(re.sub(r"\s+", "", markdown)) >= MIN_MEANINGFUL_TEXT_CHARS:
            return markdown

        # Thin text layer: pull the package images and OCR them.
        images: list = []
        with zipfile.ZipFile(file_path) as zf:
            media_names = sorted(
                name for name in zf.namelist() if name.startswith("word/media/")
            )
            for name in media_names:
                try:
                    width, height, blob = self._read_media(zf, name)
                except Exception:
                    continue
                images.append(
                    EmbeddedImage(
                        blob=blob,
                        width=width,
                        height=height,
                        sha256=hashlib.sha256(blob).hexdigest(),
                    )
                )
        if images:
            ocr_markdown = build_image_ocr_markdown(images, file_path)
            markdown = f"{markdown}\n\n{ocr_markdown}".strip() if markdown.strip() else ocr_markdown
        return markdown

    def _read_media(self, zf, name: str):
        from io import BytesIO

        from PIL import Image

        from .doc_ocr import MIN_IMAGE_DIMENSION

        blob = zf.read(name)
        with Image.open(BytesIO(blob)) as im:
            width, height = im.size
        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            raise ValueError(f"image too small: {name}")
        return width, height, blob

    def _table_to_markdown(self, table) -> str:
        rows: list = []
        for row in table.rows:
            cells = [cell.text.strip().replace("\n", " ").replace("|", "\\|") for cell in row.cells]
            rows.append("| " + " | ".join(cells) + " |")
        if not rows:
            return ""
        separator = "| " + " | ".join(["---"] * len(table.rows[0].cells)) + " |"
        return "\n".join([rows[0], separator, *rows[1:]]) + "\n"

@register_extractor
class OfficeServiceAdapter(BaseExtractor):
    """Adapter for existing office_service.py for Excel/PPT formats."""
    async def extract_to_markdown(self, file_path: str) -> str:
        # Since office_service.py is usually in the parent directory of extractors
        from ..office_service import get_office_service
        service = get_office_service()
        return await service.parse_file(file_path)

@register_extractor
class DocExtractorProxy(BaseExtractor):
    """Legacy ``.doc`` parser: antiword text layer with image-OCR fallback.

    markitdown cannot convert legacy ``.doc`` at all, so everything lands
    here. antiword handles text-mode documents (WPS/Word 97-2003), but
    screenshot-only documents — common in WPS-produced evidence — come back
    as nothing but ``[pic]`` placeholder lines. When the text layer is
    placeholder-dominated, carve the OLE2 ``Data`` stream pictures and OCR
    them so the analysis input reflects what the document actually shows.
    """

    async def extract_to_markdown(self, file_path: str) -> str:
        import asyncio

        loop = asyncio.get_running_loop()
        antiword_text, antiword_failed = await loop.run_in_executor(
            None, self._run_antiword, file_path
        )

        if antiword_text and not self._placeholder_dominated(antiword_text):
            return antiword_text

        # Thin or placeholder-only text layer: recover content from the
        # embedded pictures. Carving and OCR are CPU-bound, so both run in
        # the executor alongside each other.
        from .doc_ocr import build_image_ocr_markdown, extract_doc_images

        try:
            images = await loop.run_in_executor(None, extract_doc_images, file_path)
        except Exception as e:
            logger.error(f"Image carving failed for DOC {file_path}: {e}")
            images = []

        if not images:
            # Nothing recoverable from pictures either — surface whatever
            # antiword said (real error message or short text remnant).
            if antiword_text:
                return antiword_text
            if antiword_failed:
                return "Error parsing DOC: no text layer and no embedded images could be read."
            return f"[No content extracted from {file_path}]"

        ocr_markdown = await loop.run_in_executor(
            None, build_image_ocr_markdown, images, file_path
        )

        if antiword_text and not antiword_failed:
            # Keep captions/labels antiword did find; drop bare [pic] noise.
            from .doc_ocr import _PIC_LINE_RE

            text_part = _PIC_LINE_RE.sub("", antiword_text).strip()
            if text_part:
                return f"{text_part}\n\n{ocr_markdown}"
        return ocr_markdown

    @staticmethod
    def _run_antiword(file_path: str):
        import subprocess

        # Read bytes and decode leniently: antiword emits the document's own
        # byte stream for unmapped runs (GBK documents are common in this
        # corpus) and strict text-mode decoding used to crash the whole
        # extraction with UnicodeDecodeError.
        try:
            result = subprocess.run(
                ["antiword", file_path],
                capture_output=True,
                timeout=60,
            )
        except FileNotFoundError:
            logger.error("antiword not found.")
            return None, True
        except subprocess.TimeoutExpired:
            logger.error(f"Timeout parsing DOC {file_path}")
            return None, True
        except Exception as e:
            logger.error(f"Error parsing DOC {file_path}: {e}")
            return None, True

        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")
            logger.warning(f"antiword error: {stderr}")
            return None, True
        return result.stdout.decode("utf-8", errors="replace").strip(), False

    @staticmethod
    def _placeholder_dominated(text: str) -> bool:
        from .doc_ocr import MIN_MEANINGFUL_TEXT_CHARS, has_meaningful_text

        if has_meaningful_text(text):
            return False
        # Short-but-real text (captions) stays on the antiword path unless
        # the document clearly leans on embedded pictures.
        return "[pic]" in text or len(text.strip()) < MIN_MEANINGFUL_TEXT_CHARS
