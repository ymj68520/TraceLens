"""
doc_media_enhancer — Word 文档嵌入媒体视觉增强。

背景：话术类"截图型" doc/docx（WPS 常见）文本层为空（元数据 0 词 0 字符），
全部内容在嵌入图片里。markitdown 不支持 legacy .doc（回退 antiword 只输出
[pic] 占位符），LLM 拿到占位符只能产出"无有效内容/取证价值低"的无意义分析。

本模块在文档提取后检测近空/纯占位符文本，从文档中提取嵌入图片（.docx 走
zip word/media；.doc 按签名雕刻 JPEG/PNG 并用 PIL 校验），调用调用方注入的
视觉函数转写图片内容，并把结果作为附加章节并入传给 LLM 的文本。

设计约束：
- 仅处理 .doc/.docx；仅当文本层近空时触发（正常文档零额外开销）。
- 图片数量与大小有硬上限，视觉调用次数 = min(可提取嵌入图数, MAX_ENHANCE_IMAGES)。
- 不在提取器层引入 LLM 依赖：vision_fn 由调用方注入（保持分层）。
"""

import hashlib
import io
import logging
import re
import zipfile
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

logger = logging.getLogger(__name__)

DOC_SUFFIXES = {".doc", ".docx"}
_MIN_MEANINGFUL_CHARS = 120       # 去占位符/空白后的有效字符少于此值 → 视为近空文本
MAX_ENHANCE_IMAGES = 5            # 送视觉分析的图片数上限
_MIN_IMAGE_BYTES = 3 * 1024       # 小于 3KB 视为图标/装饰性图元
_MAX_CARVE_SCAN_BYTES = 64 * 1024 * 1024

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_JPEG_SOI = b"\xff\xd8\xff"
_JPEG_EOI = b"\xff\xd9"
_PNG_IEND = b"IEND"


def is_placeholder_text(text: Optional[str]) -> bool:
    """去除 [pic] / markdown 图片语法 / 空白后几乎没有有效文本 → True。"""
    if not text or not text.strip():
        return True
    stripped = re.sub(r"\[pic\]", "", text, flags=re.IGNORECASE)
    stripped = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", stripped)
    meaningful = re.sub(r"\s+", "", stripped)
    return len(meaningful) < _MIN_MEANINGFUL_CHARS


def _pil_ok(data: bytes) -> bool:
    """PIL 能完整解码才算有效图片，过滤雕刻出的碎片。"""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img.load()
        return True
    except Exception:
        return False


def _extract_docx_media(path: Path, limit: int) -> List[bytes]:
    """docx = zip；嵌入图片在 word/media/ 下。大图优先。"""
    out: List[bytes] = []
    with zipfile.ZipFile(path) as zf:
        media = [n for n in zf.namelist() if n.startswith("word/media/")]
        media.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
        for name in media:
            data = zf.read(name)
            if len(data) < _MIN_IMAGE_BYTES or not _pil_ok(data):
                continue
            out.append(data)
            if len(out) >= limit:
                break
    return out


def _collect_images_from_bytes(data: bytes, seen: set, out: List[bytes], limit: int) -> None:
    """在连续字节块内按 JPEG/PNG 签名雕刻，PIL 校验后收集（保持文档顺序）。"""

    def _consider(chunk: bytes) -> None:
        if len(out) >= limit or len(chunk) < _MIN_IMAGE_BYTES:
            return
        digest = hashlib.md5(chunk).hexdigest()
        if digest in seen or not _pil_ok(chunk):
            return
        seen.add(digest)
        out.append(chunk)

    # JPEG：SOI..EOI
    pos = 0
    while len(out) < limit:
        start = data.find(_JPEG_SOI, pos)
        if start == -1:
            break
        end = data.find(_JPEG_EOI, start + 3)
        if end == -1:
            break
        _consider(data[start : end + 2])
        pos = end + 2

    # PNG：签名..IEND+4CRC
    pos = 0
    while len(out) < limit:
        start = data.find(_PNG_SIG, pos)
        if start == -1:
            break
        end = data.find(_PNG_IEND, start)
        if end == -1:
            break
        _consider(data[start : end + 8])
        pos = end + 8


def _extract_doc_images(path: Path, limit: int) -> List[bytes]:
    """legacy .doc = OLE 复合文档。

    WPS 截图型文档的图片全部躺在 Data 等大流里；OLE 流在原始文件中按扇区
    碎片化存储，直接对整文件做签名扫描会因碎片化失配而扫不到，必须先用
    olefile 按流读取连续数据再雕刻。olefile 不可用时退回整文件扫描兜底。
    """
    seen: set = set()
    out: List[bytes] = []
    try:
        import olefile

        if olefile.isOleFile(str(path)):
            with olefile.OleFileIO(str(path)) as ole:
                for entry in ole.listdir(streams=True, storages=False):
                    if len(out) >= limit:
                        return out
                    try:
                        stream = ole.openstream(entry).read()
                    except Exception:
                        continue
                    if len(stream) < _MIN_IMAGE_BYTES:
                        continue
                    _collect_images_from_bytes(stream, seen, out, limit)
            return out
    except ImportError:
        logger.info("doc media enhance: olefile unavailable, falling back to raw scan for %s", path)
    except Exception as exc:
        logger.warning("doc media enhance: OLE scan failed for %s: %s", path, exc)

    _collect_images_from_bytes(path.read_bytes()[:_MAX_CARVE_SCAN_BYTES], seen, out, limit)
    return out


def extract_embedded_images(file_path: str, limit: int = MAX_ENHANCE_IMAGES) -> List[bytes]:
    """从 doc/docx 中提取嵌入图片（PIL 校验通过的字节块）。"""
    suffix = Path(file_path).suffix.lower()
    try:
        if suffix == ".docx":
            return _extract_docx_media(Path(file_path), limit)
        if suffix == ".doc":
            return _extract_doc_images(Path(file_path), limit)
    except Exception as exc:
        logger.warning("doc media enhance: embedded image extraction failed for %s: %s", file_path, exc)
    return []


def _vision_text(result: object) -> str:
    """兼容各视觉分析返回形状，取其中的文本。"""
    if isinstance(result, dict):
        analysis = result.get("analysis")
        if isinstance(analysis, dict):
            description = analysis.get("description")
            if description:
                return str(description)
        if isinstance(analysis, str) and analysis:
            return analysis
        if result.get("content"):
            return str(result["content"])
    return str(result or "")


async def enhance_document_text(
    file_path: str,
    text: str,
    vision_fn: Callable[[bytes], Awaitable[object]],
    max_images: int = MAX_ENHANCE_IMAGES,
) -> "tuple[str, int]":
    """文档文本层近空时，用视觉模型转写嵌入图片内容并追加到文本。

    Returns:
        (enhanced_text, used_images) — 未触发增强时原样返回 (text, 0)。
    """
    try:
        if Path(file_path).suffix.lower() not in DOC_SUFFIXES:
            return text, 0
        if not is_placeholder_text(text):
            return text, 0

        images = extract_embedded_images(file_path, max_images)
        if not images:
            logger.info("doc media enhance: no embedded images extracted from %s", file_path)
            return text, 0

        logger.info(
            "doc media enhance: %d embedded images found in %s, running vision transcription",
            len(images), file_path,
        )
        sections: List[str] = []
        for index, data in enumerate(images):
            try:
                result = await vision_fn(data)
                content = _vision_text(result).strip()
            except Exception as exc:
                logger.warning("doc media enhance: vision call %d failed for %s: %s", index + 1, file_path, exc)
                continue
            if not content:
                continue
            sections.append(f"### 嵌入图片 {index + 1}\n\n{content}")

        used = len(sections)
        if used == 0:
            logger.info("doc media enhance: vision produced no text for %s", file_path)
            return text, 0

        header = (
            "\n\n## 嵌入图片视觉分析\n\n"
            f"（该文档文本层为空，实际内容为 {len(images)} 张嵌入图片；"
            f"以下为视觉模型对图片内容的转写，共分析 {used} 张）\n\n"
        )
        return text + header + "\n\n".join(sections), used
    except Exception as exc:
        logger.warning("doc media enhance failed for %s: %s", file_path, exc)
        return text, 0
