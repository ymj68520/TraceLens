import logging
from pathlib import Path

from .base import BaseExtractor, ExtractionResult, DocumentContentUnavailableError, register_extractor

logger = logging.getLogger(__name__)


@register_extractor
class TextDumpExtractor(BaseExtractor):
    """
    Generic text dump extractor for files without a reliable extension or
    when higher-priority extractors did not claim the file.
    """
    def __init__(self, max_bytes: int = 200_000):
        self.max_bytes = max_bytes

    async def extract_to_markdown(self, file_path: str) -> str:
        return (await self.extract_result(file_path)).require_content()

    async def extract_result(self,file_path):
        path=Path(file_path)
        try:
            with path.open('rb') as stream:raw=stream.read(self.max_bytes+1)
        except OSError as exc:
            raise DocumentContentUnavailableError('文本文件无法读取',code='TEXT_READ_FAILED') from exc
        truncated=len(raw)>self.max_bytes
        raw=raw[:self.max_bytes]
        try:
            # incremental decoder avoids a false failure at a budget cut UTF-8 boundary.
            import codecs
            encoding='utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig'
            text=codecs.getincrementaldecoder(encoding)().decode(raw,final=not truncated)
        except UnicodeError as exc:
            raise DocumentContentUnavailableError('未知编码或二进制内容，无法确认为正文',code='TEXT_ENCODING_UNKNOWN') from exc
        if any(ord(c)<32 and c not in '\n\r\t\f' for c in text):
            raise DocumentContentUnavailableError('二进制内容不能当作文本正文',code='TEXT_BINARY_CONTENT')
        return ExtractionResult('partial' if truncated else 'ok','text','1',text=text,
            diagnostics=('TEXT_READ_BUDGET',) if truncated else (),coverage={'bytes_read':len(raw),'truncated':truncated},diagnostics_separated=True)
