import logging
from .base import BaseExtractor, DocumentContentUnavailableError, register_extractor

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
    async def extract_to_markdown(self, file_path: str) -> str:
        import docx
        
        try:
            doc = docx.Document(file_path)
            result = []
            
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    result.append(f"{text}\n")
                    
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing DOCX {file_path}: {e}")
            raise

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
    """Legacy binary .doc (OLE2) text extraction via antiword.

    antiword's stdout is captured as bytes and decoded here: it emits
    Latin-1 fallback bytes for characters missing from its mappings, so
    ``subprocess(text=True)``'s strict UTF-8 decoding raises
    UnicodeDecodeError on real Chinese documents. Failures raise
    :class:`DocumentContentUnavailableError` instead of returning error
    text, which downstream LLM analysis would otherwise treat as evidence.
    """

    OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    _CARVED_TEXT_MAX_BYTES = 262144

    async def extract_to_markdown(self, file_path: str) -> str:
        import subprocess

        try:
            with open(file_path, "rb") as f:
                head = f.read(8)
                f.seek(0)
                raw = f.read(self._CARVED_TEXT_MAX_BYTES + 1)
        except OSError as e:
            raise DocumentContentUnavailableError(f"无法读取文档文件：{e}")

        if not raw:
            raise DocumentContentUnavailableError("文件为空，没有可分析的内容")

        if head[:8] == self.OLE2_MAGIC:
            return self._extract_ole2_doc(file_path, subprocess)

        # Not an OLE2 container. Deleted-file carving frequently produces
        # .doc records whose clusters were reassigned: readable text there
        # is still analyzable (same stance as the preview path), but binary
        # garbage means the original content is gone.
        carved = self._carved_text_or_none(raw)
        if carved is not None:
            logger.info(f"Non-OLE .doc {file_path}: using carved readable text ({len(carved)} chars)")
            return carved
        raise DocumentContentUnavailableError(
            "不是有效的 Word 文档：原始内容已被覆盖或文件已损坏，正文无法恢复"
        )

    def _extract_ole2_doc(self, file_path: str, subprocess) -> str:
        try:
            result = subprocess.run(
                ["antiword", file_path],
                capture_output=True,
                timeout=60,
            )
        except FileNotFoundError:
            raise DocumentContentUnavailableError("系统未安装 antiword，无法解析旧版 .doc 文档")
        except subprocess.TimeoutExpired:
            raise DocumentContentUnavailableError("解析 .doc 文档超时")

        if result.returncode != 0:
            stderr = self._decode_bytes(result.stderr).strip()
            raise DocumentContentUnavailableError(f"解析 .doc 失败：{stderr[:200] or 'antiword 返回非零退出码'}")

        text = self._decode_bytes(result.stdout).strip()
        if not text:
            raise DocumentContentUnavailableError("该 .doc 文档没有可提取的文本层（可能全部为图片）")
        return text

    @staticmethod
    def _decode_bytes(data: bytes) -> str:
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return data.decode("gb18030")
            except UnicodeDecodeError:
                return data.decode("utf-8", errors="replace")

    def _carved_text_or_none(self, raw: bytes) -> "str | None":
        data = raw[: self._CARVED_TEXT_MAX_BYTES]
        for encoding in ("utf-8", "gb18030"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", errors="replace")
        if not text or "\x00" in text:
            return None
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
        if printable / len(text) < 0.9:
            return None
        return text
