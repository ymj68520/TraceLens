"""Embedded-image extraction and OCR helpers for binary MS Office documents.

WPS/Word-era documents are frequently screenshots-only (no text layer):
antiword then emits nothing but ``[pic]`` placeholders and the analysis
pipeline forwards them as meaningless evidence. This module carves the
embedded pictures out of the OLE2 ``Data`` stream (legacy ``.doc``) or the
package media parts (``.docx``) and OCRs them with RapidOCR, whose
Chinese/English detection+recognition models ship inside the wheel so the
pipeline keeps working fully offline.
"""

import hashlib
import io
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Icons, bullets and border decorations are smaller than this and are not
# forensic content; skipping them keeps OCR cost on actual screenshots.
MIN_IMAGE_DIMENSION = 64

# Bound the OCR cost for image-bomb documents (a CPU recognition pass costs
# roughly 1-4s per screenshot).
MAX_OCR_IMAGES = 60

# antiword output with fewer real (non-placeholder) characters than this is
# treated as text-less and triggers the image-OCR path. The bar is low on
# purpose: CJK text carries several times the information per character of
# Latin scripts, so a handful of hanzi is already a meaningful layer.
MIN_MEANINGFUL_TEXT_CHARS = 20

# antiword's inline-picture placeholder line (single or repeated on one line).
_PIC_LINE_RE = re.compile(r"^\s*(?:\[pic\])+\s*$", re.MULTILINE)

# Parallel OCR: recognition is CPU-bound and releases the GIL inside
# onnxruntime, so a small worker pool gives near-linear speedup.
OCR_MAX_WORKERS = max(1, min(8, (os.cpu_count() or 2) // 4))

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_END = b"IEND"
_JPEG_SIG = b"\xff\xd8\xff"
_JPEG_END = b"\xff\xd9"

# Cap on OCR text kept in the final markdown; the LLM input layer applies
# its own ceiling, but carving only the head here avoids useless CPU work
# on 50-screenshot documents.
MAX_TOTAL_OCR_CHARS = 200_000


@dataclass(frozen=True)
class EmbeddedImage:
    """One validated picture carved out of an Office document."""

    blob: bytes
    width: int
    height: int
    sha256: str


class _OcrEngine:
    """Lazy per-thread RapidOCR singletons.

    onnxruntime ``InferenceSession.run`` is thread-safe, but the RapidOCR
    pipeline keeps per-call buffers; one engine per OCR thread is the
    conservative layout and costs ~0.5s of model load per thread.
    """

    def __init__(self) -> None:
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._available: Optional[bool] = None

    def _create(self):
        from rapidocr_onnxruntime import RapidOCR

        # Default -1 gives every engine all cores; N parallel engines then
        # thrash. The unprefixed Global kwarg does not reach the Det/Cls/Rec
        # sessions (the config.yaml anchors resolve at load time), so pass
        # each module's thread count explicitly.
        threads = max(2, (os.cpu_count() or 4) // OCR_MAX_WORKERS)
        return RapidOCR(
            det_intra_op_num_threads=threads,
            cls_intra_op_num_threads=threads,
            rec_intra_op_num_threads=threads,
        )

    def get(self):
        engine = getattr(self._local, "engine", None)
        if engine is not None:
            return engine
        # First import check decides availability once, process-wide; the
        # per-thread construction itself stays under a lock so a burst of
        # OCR threads fail together instead of each importing separately.
        if self._available is None:
            with self._init_lock:
                if self._available is None:
                    try:
                        self._create()
                        self._available = True
                        logger.info("RapidOCR engine available for document image OCR")
                    except Exception as exc:
                        self._available = False
                        logger.warning(f"RapidOCR unavailable, document image OCR disabled: {exc}")
                    if not self._available:
                        return None
        elif not self._available:
            return None
        try:
            engine = self._create()
        except Exception as exc:
            logger.warning(f"RapidOCR thread engine failed to initialize: {exc}")
            return None
        self._local.engine = engine
        return engine


_ocr_engine = _OcrEngine()


def get_ocr_engine():
    """Return this thread's RapidOCR instance, or ``None`` if not installed."""
    return _ocr_engine.get()


def ocr_image_bytes(blob: bytes) -> List[str]:
    """OCR one encoded image (PNG/JPEG bytes) and return the text lines."""
    engine = get_ocr_engine()
    if engine is None:
        raise RuntimeError("OCR engine is not available")

    import numpy as np

    frame = None
    try:
        import cv2

        frame = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        frame = None
    if frame is None:
        # CMYK JPEGs and palette edge cases fail in cv2; go through PIL.
        from PIL import Image

        with Image.open(io.BytesIO(blob)) as im:
            frame = np.asarray(im.convert("RGB"))[:, :, ::-1]

    result, _ = engine(frame)
    if not result:
        return []
    return [str(item[1]).strip() for item in result if item and len(item) > 1 and str(item[1]).strip()]


def _decode_size(blob: bytes):
    from PIL import Image

    with Image.open(io.BytesIO(blob)) as im:
        return im.size


def carve_images_from_stream(data: bytes) -> List[EmbeddedImage]:
    """Carve validated PNG/JPEG pictures out of a raw ``Data`` stream.

    Legacy ``.doc`` stores inline pictures as opaque blobs in the OLE2
    ``Data`` stream; signature carving with PIL validation is deliberately
    used instead of full [MS-DOC] FBT parsing — WPS-produced files violate
    enough of the spec details that strict parsing is the fragile option.
    """
    candidates: List[bytes] = []
    for match in re.finditer(re.escape(_PNG_SIG), data):
        end = data.find(_PNG_END, match.start())
        if end != -1:
            # IEND chunk: 4-byte length + type + CRC.
            candidates.append(data[match.start() : end + 8])
    for match in re.finditer(re.escape(_JPEG_SIG), data):
        end = data.find(_JPEG_END, match.start() + 3)
        if end != -1:
            candidates.append(data[match.start() : end + 2])

    images: List[EmbeddedImage] = []
    seen: set = set()
    for blob in candidates:
        try:
            width, height = _decode_size(blob)
        except Exception:
            continue
        if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
            continue
        digest = hashlib.sha256(blob).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        images.append(EmbeddedImage(blob=blob, width=width, height=height, sha256=digest))
    return images


def extract_doc_images(file_path: str) -> List[EmbeddedImage]:
    """Extract embedded pictures from a legacy ``.doc`` (OLE2 compound file)."""
    try:
        import olefile

        with olefile.OleFileIO(file_path) as ole:
            if not ole.exists("Data"):
                return []
            data = ole.openstream("Data").read()
    except Exception as exc:
        logger.warning(f"Cannot open OLE structure of {file_path} for image carving: {exc}")
        return []
    return carve_images_from_stream(data)


def has_meaningful_text(text: str) -> bool:
    """True when antiword output carries real text, not just ``[pic]`` lines."""
    real = _PIC_LINE_RE.sub("", text or "")
    return len(re.sub(r"\s+", "", real)) >= MIN_MEANINGFUL_TEXT_CHARS


def ocr_embedded_images(
    images: List[EmbeddedImage],
    *,
    max_images: int = MAX_OCR_IMAGES,
    max_total_chars: int = MAX_TOTAL_OCR_CHARS,
) -> List[tuple]:
    """OCR carved images; returns ``[(image, [lines])]`` in document order.

    Runs a small thread pool (onnxruntime releases the GIL during
    inference) with per-image error isolation so one corrupt screenshot
    cannot void the rest of the document.
    """
    selected = images[:max_images]
    if not selected:
        return []

    def _ocr(image: EmbeddedImage) -> List[str]:
        try:
            return ocr_image_bytes(image.blob)
        except Exception as exc:
            logger.warning(f"OCR failed for embedded image {image.sha256[:12]}: {exc}")
            return []

    if len(selected) == 1 or OCR_MAX_WORKERS == 1:
        rendered = [(image, _ocr(image)) for image in selected]
    else:
        with ThreadPoolExecutor(max_workers=OCR_MAX_WORKERS) as pool:
            rendered = list(zip(selected, pool.map(_ocr, selected)))

    results: List[tuple] = []
    total_chars = 0
    for image, lines in rendered:
        if not lines:
            continue
        results.append((image, lines))
        total_chars += sum(len(line) for line in lines)
        if total_chars >= max_total_chars:
            logger.info(f"OCR text cap {max_total_chars} reached after {len(results)} images")
            break
    return results


def build_image_ocr_markdown(images: List[EmbeddedImage], source_path: str) -> str:
    """Render carved images + OCR text as analysis-ready Markdown."""
    total = len(images)
    if not images:
        return f"[No content extracted from {source_path}]"

    engine = get_ocr_engine()
    if engine is None:
        sizes = ", ".join(f"{im.width}x{im.height}" for im in images[:5])
        return (
            f"[本文档不含文本层，由 {total} 张内嵌图片组成（如 {sizes}...）。"
            f"OCR 组件不可用，无法识别图片中的文字内容。]"
        )

    sections: List[str] = [
        f"[本文档不含文本层，由 {total} 张内嵌图片组成；以下为逐张图片的 OCR 识别内容。]"
    ]
    for index, (image, lines) in enumerate(ocr_embedded_images(images), start=1):
        sections.append(f"## 图片 {index}（{image.width}x{image.height}）\n\n" + "\n".join(lines))
    return "\n\n".join(sections)
