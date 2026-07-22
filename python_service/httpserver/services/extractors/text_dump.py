import logging
from pathlib import Path

from .base import BaseExtractor, register_extractor

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
        path = Path(file_path)
        result = [f"# Text Dump (`{path.name}`)\n"]
        try:
            size = path.stat().st_size
        except Exception as e:
            return f"Error: Failed to stat text file: {e}"

        result.append(f"**Path:** `{path}`\n")
        result.append(f"**Size:** {size:,} bytes\n\n")

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = f.read(self.max_bytes)
        except Exception as e:
            return f"Error: Failed to read text file: {e}"

        result.append("```text")
        result.append(data)
        if size > len(data.encode("utf-8", errors="replace")):
            result.append("```\n\n*(truncated)\n")
        else:
            result.append("```\n")

        return "\n".join(result)
