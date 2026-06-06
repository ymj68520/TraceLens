"""Windows Registry hive forensic extractor."""
import logging
import os
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

REGF_MAGIC = b'regf'

IMPORTANT_KEYS = {
    'SAM': [r'SAM\Domains\Account\Users', r'SAM\Domains\Account\Users\Names'],
    'SYSTEM': [r'Select', r'ControlSet001\Control\ComputerName\ComputerName', r'ControlSet001\Services'],
    'SOFTWARE': [r'Microsoft\Windows\CurrentVersion\Run', r'Microsoft\Windows\CurrentVersion\RunOnce', r'Microsoft\Windows NT\CurrentVersion'],
    'NTUSER': [r'Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs', r'Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU'],
}


def _detect_hive_type(file_path: str, reg) -> str:
    name = os.path.basename(file_path).upper()
    for key in ['SAM', 'SYSTEM', 'SOFTWARE', 'SECURITY', 'NTUSER', 'USRCLASS', 'DEFAULT']:
        if key in name:
            return key
    try:
        root = reg.root()
        return f"Unknown ({root.name() if root else 'N/A'})"
    except:
        return "Unknown"


@register_extractor
class RegistryExtractor(BaseExtractor):
    """Extracts content from Windows Registry hive files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import Registry
        except ImportError:
            return "Error: python-registry library is not installed."

        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)
            if magic != REGF_MAGIC:
                return f"Error: Not a valid Registry hive file (magic: {magic.hex()})"
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        try:
            reg = Registry.Registry(file_path)
        except Exception as e:
            return f"Error: Failed to open Registry hive: {e}"

        try:
            hive_type = _detect_hive_type(file_path, reg)
            root = reg.root()
            total_keys = self._count_keys(root)

            result = [f"# Windows Registry Summary: `{os.path.basename(file_path)}`"]
            result.append(f"**Hive Type:** {hive_type}")
            result.append(f"**Root Key:** {root.name()}")
            result.append(f"**Total Keys:** {total_keys:,}")
            result.append("")

            result.append("## Forensically Important Keys")
            result.append("")

            important_paths = IMPORTANT_KEYS.get(hive_type, [])
            found_important = False
            for key_path in important_paths:
                try:
                    key = reg.open(key_path)
                    if key:
                        found_important = True
                        result.append(f"### `{key_path}`")
                        values = list(key.values())
                        if values:
                            result.append("| Name | Type | Data |")
                            result.append("| --- | --- | --- |")
                            for v in values[:20]:
                                vdata = str(v.value())
                                if len(vdata) > 100:
                                    vdata = vdata[:97] + "..."
                                vdata = vdata.replace('|', '\\|').replace('\n', ' ')
                                result.append(f"| {v.name()} | {v.type_str()} | {vdata} |")
                        subkeys = list(key.subkeys())
                        if subkeys:
                            result.append(f"\n*Subkeys: {', '.join(sk.name() for sk in subkeys[:10])}*")
                        result.append("")
                except Registry.RegistryKeyNotFoundException:
                    pass
                except Exception as e:
                    logger.warning(f"Error reading registry key {key_path}: {e}")

            if not found_important:
                result.append("*No forensically important keys found for this hive type.*\n")

            result.append("## Key Tree (Sample)")
            result.append("```")
            self._render_tree(root, result, depth=0, max_depth=3, max_children=5)
            result.append("```")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Registry hive: {e}"

    def _count_keys(self, key) -> int:
        count = 1
        try:
            for subkey in key.subkeys():
                count += self._count_keys(subkey)
        except:
            pass
        return count

    def _render_tree(self, key, result: list, depth: int, max_depth: int, max_children: int):
        if depth > max_depth:
            return
        indent = "  " * depth
        result.append(f"{indent}{key.name()}/")
        try:
            subkeys = list(key.subkeys())
            for i, subkey in enumerate(subkeys):
                if i >= max_children:
                    result.append(f"{indent}  ... ({len(subkeys) - max_children} more subkeys)")
                    break
                self._render_tree(subkey, result, depth + 1, max_depth, max_children)
        except:
            pass
