"""Mobile forensic extractors: iOS backup, Android Manifest, SQLite WAL/SHM."""
import logging
import os
import sqlite3
import struct
import plistlib
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class IosBackupExtractor(BaseExtractor):
    """Extracts metadata from iOS backup Manifest.db and Info.plist."""

    async def extract_to_markdown(self, file_path: str) -> str:
        basename = os.path.basename(file_path)

        if basename == 'Manifest.db':
            return self._parse_manifest_db(file_path)
        elif basename == 'Info.plist' or basename == 'Manifest.plist':
            return self._parse_plist(file_path)
        else:
            return f"Error: Unknown iOS backup file: {basename}"

    def _parse_manifest_db(self, file_path: str) -> str:
        try:
            import tempfile, shutil
            tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
            tmp.close()
            shutil.copy2(file_path, tmp.name)
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
        except Exception as e:
            return f"Error: Failed to open Manifest.db: {e}"

        try:
            result = [f"# iOS Backup Manifest: `{os.path.basename(file_path)}`"]

            # List tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]

            if 'Files' in tables:
                cursor.execute("SELECT COUNT(*) FROM Files")
                total = cursor.fetchone()[0]
                result.append(f"**Total Files:** {total:,}")

                # Domain distribution
                try:
                    cursor.execute("SELECT domain, COUNT(*) FROM Files GROUP BY domain ORDER BY COUNT(*) DESC LIMIT 20")
                    domains = cursor.fetchall()

                    if domains:
                        result.append("")
                        result.append("## Backup Domains")
                        result.append("| Domain | File Count |")
                        result.append("| --- | --- |")
                        for domain, count in domains:
                            result.append(f"| {domain} | {count:,} |")
                except: pass

                # File listing
                result.append("")
                result.append("## Files (First 100)")
                result.append("| Domain | Path | Size |")
                result.append("| --- | --- | --- |")

                try:
                    cursor.execute("SELECT domain, relativePath, file FROM Files LIMIT 100")
                    for domain, path, file_data in cursor.fetchall():
                        domain_str = (domain or '').replace('|', '\\|')[:30]
                        path_str = (path or '').replace('|', '\\|')[:60]
                        size = len(file_data) if file_data else 0
                        result.append(f"| {domain_str} | {path_str} | {_format_size(size)} |")
                except: pass
            else:
                result.append(f"Available tables: {', '.join(tables)}")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Manifest.db: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)

    def _parse_plist(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                plist = plistlib.load(f)

            result = [f"# iOS Backup Info: `{os.path.basename(file_path)}`"]
            result.append("")
            result.append("## Device Information")
            result.append("| Key | Value |")
            result.append("| --- | --- |")

            important_keys = {
                'Device Name': 'Device Name',
                'Display Name': 'Display Name',
                'Product Type': 'Product Type',
                'Product Version': 'iOS Version',
                'Serial Number': 'Serial Number',
                'Unique Identifier': 'UDID',
                'Build Version': 'Build Version',
                'Phone Number': 'Phone Number',
                'IMEI': 'IMEI',
            }

            for key, label in important_keys.items():
                if key in plist:
                    result.append(f"| {label} | {plist[key]} |")

            # Any other interesting keys
            result.append("")
            result.append("## All Properties")
            result.append("| Key | Value |")
            result.append("| --- | --- |")
            for key, value in sorted(plist.items()):
                if key not in important_keys:
                    val_str = str(value)[:100].replace('|', '\\|')
                    result.append(f"| {key} | {val_str} |")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse plist: {e}"


@register_extractor
class AndroidManifestExtractor(BaseExtractor):
    """Extracts information from AndroidManifest.xml (binary XML format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        result = [f"# Android Manifest: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        # Check if it's binary Android XML format
        if len(data) >= 4 and data[:4] == b'\x03\x00\x08\x00':
            result.append("**Format:** Binary Android XML")
            result.append("")

            # Try to extract strings
            strings = []
            try:
                # Binary XML has a string pool
                # Look for readable strings
                text = data.decode('utf-8', errors='replace')
                import re
                # Find meaningful strings (package names, permissions, etc.)
                found = re.findall(r'[a-zA-Z][a-zA-Z0-9_.]{3,}', text)
                seen = set()
                for s in found:
                    if s not in seen and len(s) > 4:
                        seen.add(s)
                        strings.append(s)
            except: pass

            # Look for package name pattern
            import re
            pkg_match = re.search(rb'[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_.]*', data)
            if pkg_match:
                result.append(f"**Likely Package:** {pkg_match.group(0).decode('ascii', errors='replace')}")

            # Look for permissions
            permissions = []
            perm_pattern = re.findall(rb'android\.permission\.[A-Z_]+', data)
            for p in perm_pattern:
                perm = p.decode('ascii', errors='replace')
                if perm not in permissions:
                    permissions.append(perm)

            if permissions:
                result.append("")
                result.append("## Permissions")
                for perm in sorted(permissions):
                    result.append(f"- `{perm}`")

            # Extract other notable strings
            if strings:
                result.append("")
                result.append("## Notable Strings")
                for s in strings[:50]:
                    if '.' in s and not s.startswith('.'):
                        result.append(f"- `{s}`")

        elif data[:5] == b'<?xml':
            result.append("**Format:** Plain XML")
            result.append("")
            result.append("```xml")
            result.append(data[:5000].decode('utf-8', errors='replace'))
            if len(data) > 5000:
                result.append("... (truncated)")
            result.append("```")
        else:
            result.append(f"**Format:** Unknown (magic: {data[:4].hex()})")

        return "\n".join(result)


@register_extractor
class SqliteWalExtractor(BaseExtractor):
    """Extracts data from SQLite WAL (Write-Ahead Log) and SHM files."""

    WAL_MAGIC = b'\x37\x7f\x06\x82'  # WAL magic (big-endian)
    WAL_MAGIC_LE = b'\x82\x06\x7f\x37'  # WAL magic (little-endian)

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == '.wal':
            return self._parse_wal(file_path)
        elif ext == '.shm':
            return self._parse_shm(file_path)
        else:
            return f"Error: Unknown SQLite auxiliary file: {ext}"

    def _parse_wal(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(32)
        except Exception as e:
            return f"Error: Failed to read WAL file: {e}"

        result = [f"# SQLite WAL File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        if len(header) < 32:
            return "Error: File too small."

        magic = header[0:4]
        if magic == self.WAL_MAGIC or magic == self.WAL_MAGIC_LE:
            result.append("**Format:** SQLite Write-Ahead Log")

            try:
                endian = '>' if magic == self.WAL_MAGIC else '<'
                version = struct.unpack_from(endian + 'I', header, 4)[0]
                page_size = struct.unpack_from(endian + 'I', header, 8)[0]
                checkpoint_seq = struct.unpack_from(endian + 'I', header, 12)[0]

                result.append(f"**Version:** {version}")
                result.append(f"**Page Size:** {page_size:,}")
                result.append(f"**Checkpoint Sequence:** {checkpoint_seq}")

                # Count frames
                file_size = os.path.getsize(file_path)
                if page_size > 0:
                    frame_size = 24 + page_size  # Frame header + page
                    num_frames = max(0, (file_size - 32)) // frame_size if frame_size > 0 else 0
                    result.append(f"**Frames:** {num_frames:,}")
            except: pass
        else:
            result.append(f"**Magic:** {magic.hex()}")

        result.append("")
        result.append("*WAL files contain uncommitted database changes. Open with the parent SQLite database for full analysis.*")

        return "\n".join(result)

    def _parse_shm(self, file_path: str) -> str:
        result = [f"# SQLite SHM File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("**Format:** SQLite Shared Memory File")
        result.append("")
        result.append("*SHM files are used for shared memory between SQLite processes. Open with the parent database for analysis.*")

        return "\n".join(result)
