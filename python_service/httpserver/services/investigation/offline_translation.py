"""Small, local EN→ZH reader for Argos' CTranslate2 package.

The model lives in build/models, not in the source tree. It is only loaded
on demand; no evidence text leaves the host. File paths and other forensic
identifiers are replaced by placeholders before inference and restored after.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


class OfflineTranslationError(Exception):
    pass


_HEADINGS = {
    "SUMMARY": "摘要",
    "DESCRIPTION": "详细描述",
    "KEYWORDS": "关键词",
    "摘要": "摘要",
    "详细描述": "详细描述",
    "关键词": "关键词",
}
_IDENTIFIER = re.compile(
    r"https?://[^\s\"'<>]+"
    r"|%[A-Za-z_][A-Za-z0-9_]*%"
    r"|\b[A-Za-z]:\\[^\s\"']+"
    r"|/(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+"
    r"|\b(?:[A-Fa-f0-9]{32,64}|(?:\d{1,3}\.){3}\d{1,3})\b"
    r"|\b[A-Za-z0-9_-]+\.[A-Za-z0-9]{2,10}\b"
    r"|\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b"
    r"|\b[A-Z]{2,}\b"
)


def _mask_identifiers(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = f"TOKEN{len(protected):03d}"
        protected[marker] = match.group()
        return marker

    return _IDENTIFIER.sub(replace, text), protected


def _restore_identifiers(text: str, protected: dict[str, str]) -> str:
    for marker, original in protected.items():
        matches = list(re.finditer(re.escape(marker), text, flags=re.IGNORECASE))
        if len(matches) != 1:
            raise OfflineTranslationError("translation changed a protected identifier")
        text = re.sub(re.escape(marker), lambda _match: original, text, count=1, flags=re.IGNORECASE)
    return text


@lru_cache(maxsize=1)
def _load_model(model_dir: str):
    root = Path(model_dir)
    if not (root / "model" / "model.bin").is_file() or not (root / "sentencepiece.model").is_file():
        raise OfflineTranslationError("offline EN-ZH model is not installed")
    try:
        import ctranslate2
        import sentencepiece as spm
    except ImportError as exc:
        raise OfflineTranslationError("offline translation dependencies are not installed") from exc
    tokenizer = spm.SentencePieceProcessor(model_file=str(root / "sentencepiece.model"))
    translator = ctranslate2.Translator(str(root / "model"), device="cpu", intra_threads=2)
    return tokenizer, translator


def _chunks(text: str, tokenizer, max_tokens: int = 100) -> list[str]:
    """Keep each inference below the Argos model's sentence-length budget."""
    clauses = re.split(r"(?<=[.!?;,])\s+", text)
    chunks: list[str] = []
    current = ""
    for clause in clauses:
        candidate = f"{current} {clause}".strip() if current else clause
        if len(tokenizer.encode(candidate, out_type=str)) <= max_tokens:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = ""
        words = clause.split()
        for word in words:
            candidate = f"{current} {word}".strip() if current else word
            if current and len(tokenizer.encode(candidate, out_type=str)) > max_tokens:
                chunks.append(current)
                current = word
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


class OfflineArgosTranslator:
    def __init__(self, model_dir: Path):
        self.model_dir = Path(model_dir)

    def translate(self, source_text: str) -> tuple[str, str]:
        tokenizer, model = _load_model(str(self.model_dir))

        def infer(body: str) -> str:
            pieces = [tokenizer.encode(chunk, out_type=str) for chunk in _chunks(body, tokenizer)]
            if not pieces:
                return ""
            outputs = model.translate_batch(pieces, beam_size=4, max_decoding_length=256)
            return " ".join(
                tokenizer.decode(output.hypotheses[0]).replace("▁", " ").strip()
                for output in outputs
            )

        translated_parts: list[str] = []
        for paragraph in re.split(r"\n\s*\n", source_text):
            if not paragraph.strip():
                continue
            match = re.match(
                r"^\s*(SUMMARY|DESCRIPTION|KEYWORDS|摘要|详细描述|关键词)\s*[:：]\s*",
                paragraph,
                flags=re.IGNORECASE,
            )
            heading = _HEADINGS[match.group(1).upper()] if match else None
            body = paragraph[match.end():] if match else paragraph
            masked, protected = _mask_identifiers(body.strip())
            translated_body = infer(masked) if masked.strip() else ""
            try:
                translated_body = _restore_identifiers(translated_body, protected)
            except OfflineTranslationError:
                # Some small models omit placeholders in long or keyword-heavy
                # passages. Still offer a reading aid, but explicitly list
                # every original identifier that the unmasked pass omitted.
                translated_body = infer(body.strip())
                missing = list(dict.fromkeys(
                    original for original in protected.values()
                    if original not in translated_body
                ))
                if missing:
                    translated_body += "（原文技术标识：" + "、".join(missing) + "）"
            translated_parts.append(f"{heading}：{translated_body}" if heading else translated_body)
        return "\n\n".join(translated_parts), "Argos en_zh 1.9 (offline)"
