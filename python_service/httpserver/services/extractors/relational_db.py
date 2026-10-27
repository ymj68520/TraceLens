import logging
import os
from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

from .sqlite_records import SQLiteExtractor


@register_extractor
class GenericDatabaseExtractor(BaseExtractor):
    """
    Fallback for database-like files that are not valid SQLite databases
    (for example, certain `.db` files such as `aliases.db`).
    """
    def __init__(self):
        pass

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            file_size = os.path.getsize(file_path)
        except Exception:
            file_size = -1

        result = [
            "# Generic Database File Summary\n",
            f"**File:** `{file_path}`\n",
            f"**Size:** {file_size:,} bytes\n",
            "**Note:** This file is not a readable SQLite database. "
            "Displaying binary/generic metadata only.\n",
        ]
        try:
            with open(file_path, "rb") as f:
                data = f.read(64)
            hex_dump = " ".join(f"{byte:02x}" for byte in data)
            result.append("```hex")
            result.append(hex_dump)
            result.append("```\n")
        except Exception as e:
            result.append(f"*Unable to read file bytes: {e}*\n")

        return "\n".join(result)


@register_extractor
class SqlDumpExtractor(BaseExtractor):
    """
    Extracts the beginning of a SQL dump file. Since SQL dumps can be massive
    we only extract the first N lines.
    """
    def __init__(self, max_lines: int = 500):
        self.max_lines = max_lines
        
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            result = [f"# SQL Dump Summary (`{file_path.split('/')[-1]}`)\n"]
            result.append("```sql")
            
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                for idx, line in enumerate(f):
                    if idx >= self.max_lines:
                        break
                    result.append(line.rstrip())
                    
            result.append("```\n")
            result.append(f"\n*(Truncated to first {self.max_lines} lines)*")
            return "\n".join(result)
            
        except Exception as e:
            logger.error(f"Error parsing SQL Dump {file_path}: {e}")
            return f"Error: Failed to read SQL Dump file: {e}"
