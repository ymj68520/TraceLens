import os
import logging
from collections import defaultdict
import zipfile
import tarfile

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

@register_extractor
class ArchiveExtractor(BaseExtractor):
    """
    Analyzes the structural metadata of a compressed archive without extracting it.
    Uses 'Structural Aggregation' to prevent context overflow.
    """
    def __init__(self, max_tree_lines: int = 50, whitelist_path: str = "config/artifact_whitelist.json"):
        self.max_tree_lines = max_tree_lines
        self.whitelist_path = whitelist_path

    def _load_whitelist(self) -> dict:
        import json

        # Determine path relative to the python_service root
        if not os.path.isabs(self.whitelist_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            full_path = os.path.join(base_dir, self.whitelist_path)
        else:
            full_path = self.whitelist_path

        default_whitelist = {
            "high_value_extensions": [".db", ".sqlite", ".sqlite3", ".plist", ".evt", ".evtx", ".log"],
            "high_value_filenames": ["SAM", "SYSTEM", "config.json", "history.dat", "shadow"]
        }

        if not os.path.exists(full_path):
            logger.warning(f"Whitelist {full_path} not found. Using defaults.")
            return default_whitelist

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    "high_value_extensions": data.get("high_value_extensions", default_whitelist["high_value_extensions"]),
                    "high_value_filenames": data.get("high_value_filenames", default_whitelist["high_value_filenames"])
                }
        except Exception as e:
            logger.error(f"Failed to load whitelist from {full_path}: {e}")
            return default_whitelist

    def _is_high_value(self, filename: str, whitelist: dict) -> bool:
        name = filename.split('/')[-1].lower()
        if name in [f.lower() for f in whitelist['high_value_filenames']]:
            return True
        ext = os.path.splitext(name)[1].lower()
        if ext in [e.lower() for e in whitelist['high_value_extensions']]:
            return True
        return False

    async def extract_to_markdown(self, file_path: str) -> str:
        whitelist = self._load_whitelist()
        total_files = 0
        total_size = 0
        ext_stats = defaultdict(lambda: {"count": 0, "size": 0})
        high_value_found = []
        tree_lines = []

        try:
            # 1. Read Metadata
            if zipfile.is_zipfile(file_path):
                with zipfile.ZipFile(file_path, 'r') as archive:
                    for info in archive.infolist():
                        if not info.is_dir():
                            total_files += 1
                            total_size += info.file_size
                            ext = os.path.splitext(info.filename)[1].lower() or "[no_ext]"
                            ext_stats[ext]["count"] += 1
                            ext_stats[ext]["size"] += info.file_size
                            
                            if self._is_high_value(info.filename, whitelist):
                                high_value_found.append((info.filename, info.file_size))
                            if len(tree_lines) < self.max_tree_lines:
                                tree_lines.append(info.filename)
                                
            elif tarfile.is_tarfile(file_path):
                with tarfile.open(file_path, 'r:*') as archive:
                    for info in archive:
                        if info.isfile():
                            total_files += 1
                            total_size += info.size
                            ext = os.path.splitext(info.name)[1].lower() or "[no_ext]"
                            ext_stats[ext]["count"] += 1
                            ext_stats[ext]["size"] += info.size
                            
                            if self._is_high_value(info.name, whitelist):
                                high_value_found.append((info.name, info.size))
                            if len(tree_lines) < self.max_tree_lines:
                                tree_lines.append(info.name)
            else:
                return "Error: Unsupported or corrupted archive format."

            # 2. Build Markdown
            result = [f"# Archive Summary: `{os.path.basename(file_path)}`"]
            result.append(f"**Total Files:** {total_files:,}")
            result.append(f"**Uncompressed Size:** {(total_size / 1024 / 1024):.2f} MB\n")
            
            result.append("### 📊 Content Distribution")
            sorted_exts = sorted(ext_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:15]
            for ext, data in sorted_exts:
                size_mb = data['size'] / 1024 / 1024
                size_str = f"{size_mb:.2f} MB" if size_mb >= 0.01 else f"{data['size']} B"
                result.append(f"- {data['count']:,}x `{ext}` ({size_str})")
            
            if len(ext_stats) > 15:
                result.append(f"- ... (and {len(ext_stats) - 15} other extensions)")
            result.append("")

            result.append("### 🚨 High-Value Forensic Artifacts Found")
            if not high_value_found:
                result.append("*No high-value artifacts detected based on the current whitelist.*")
            else:
                for i, (fname, fsize) in enumerate(high_value_found[:50]):
                    size_kb = fsize / 1024
                    result.append(f"{i+1}. `{fname}` ({size_kb:.1f} KB)")
                if len(high_value_found) > 50:
                    result.append(f"*... and {len(high_value_found) - 50} more high-value files.*")
            result.append("")

            result.append("### 📂 Structure Snapshot (Truncated)")
            result.append("```text")
            for line in tree_lines:
                result.append(f"- {line}")
            if total_files > self.max_tree_lines:
                result.append(f"... (Truncated, {total_files - self.max_tree_lines} files omitted)")
            result.append("```\n")

            return "\n".join(result)

        except Exception as e:
            logger.error(f"Error parsing Archive {file_path}: {e}")
            return f"Error: Failed to process Archive file: {e}"
