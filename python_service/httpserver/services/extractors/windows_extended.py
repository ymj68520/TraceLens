"""Extended Windows forensic artifact extractors: Prefetch, SRUM, Amcache, Thumbcache, Timeline."""
import logging
import os
import struct
import sqlite3
from datetime import datetime, timedelta

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


def _filetime_to_datetime(filetime: int) -> datetime:
    if filetime == 0: return None
    try: return datetime.fromtimestamp((filetime - 116444736000000000) / 10000000)
    except: return None


@register_extractor
class PrefetchExtractor(BaseExtractor):
    """Extracts metadata from Windows Prefetch files (.pf)."""

    # Prefetch magic: SCCA (0x41434353)
    PF_MAGIC_V17 = b'\x53\x43\x43\x41'  # Windows XP
    PF_MAGIC_V23 = b'\x53\x43\x43\x41'  # Windows Vista/7
    PF_MAGIC_V26 = b'\x53\x43\x43\x41'  # Windows 8
    PF_MAGIC_V30 = b'\x53\x43\x43\x41'  # Windows 10

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read Prefetch file: {e}"

        if len(data) < 84:
            return "Error: File too small to be a valid Prefetch file."

        magic = data[:4]
        if magic != self.PF_MAGIC_V17:
            return f"Error: Not a valid Prefetch file (magic: {magic.hex()})"

        try:
            version = struct.unpack_from('<I', data, 0)[0]

            result = [f"# Prefetch Analysis: `{os.path.basename(file_path)}`"]

            # Parse based on version
            if version == 0x11:  # v17 (XP)
                result.append("**Version:** Windows XP (v17)")
                filename_offset = 0x10
                filename_size = 60
                run_count_offset = 0x90
                last_run_offset = 0x78
            elif version == 0x17:  # v23 (Vista/7)
                result.append("**Version:** Windows Vista/7 (v23)")
                filename_offset = 0x10
                filename_size = 60
                run_count_offset = 0x98
                last_run_offset = 0x80
            elif version == 0x1A:  # v26 (Win8)
                result.append("**Version:** Windows 8 (v26)")
                filename_offset = 0x10
                filename_size = 60
                run_count_offset = 0xD0
                last_run_offset = 0x80
            elif version == 0x1E:  # v30 (Win10)
                result.append("**Version:** Windows 10 (v30)")
                filename_offset = 0x10
                filename_size = 60
                run_count_offset = 0xD0
                last_run_offset = 0x80
            else:
                result.append(f"**Version:** Unknown ({version})")

            # Extract filename (UTF-16LE)
            try:
                fn_bytes = data[filename_offset:filename_offset + filename_size]
                filename = fn_bytes.decode('utf-16-le').rstrip('\x00')
                result.append(f"**Executable:** {filename}")
            except:
                filename = "Unknown"

            # Run count
            if run_count_offset + 4 <= len(data):
                run_count = struct.unpack_from('<I', data, run_count_offset)[0]
                result.append(f"**Run Count:** {run_count}")

            # Last run time
            if last_run_offset + 8 <= len(data):
                last_run_ft = struct.unpack_from('<Q', data, last_run_offset)[0]
                last_run = _filetime_to_datetime(last_run_ft)
                if last_run:
                    result.append(f"**Last Run:** {last_run.strftime('%Y-%m-%d %H:%M:%S')}")

            # File size
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            # Extract referenced filenames
            result.append("## Referenced Files")
            # Look for filename strings in the file
            filenames = []
            try:
                # Prefetch files contain referenced filenames as UTF-16LE strings
                text = data.decode('utf-16-le', errors='replace')
                # Look for common Windows paths
                import re
                paths = re.findall(r'[A-Z]:\\[^\x00]{5,200}', text)
                seen = set()
                for p in paths:
                    p_clean = p.rstrip('\x00').strip()
                    if p_clean and p_clean not in seen and '\\' in p_clean:
                        seen.add(p_clean)
                        filenames.append(p_clean)
            except: pass

            if filenames:
                for fn in filenames[:50]:
                    result.append(f"- `{fn}`")
                if len(filenames) > 50:
                    result.append(f"\n*(Showing first 50 of {len(filenames)} referenced files)*")
            else:
                result.append("*Could not extract referenced filenames.*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Prefetch file: {e}"


@register_extractor
class SrumExtractor(BaseExtractor):
    """Extracts data from Windows SRUM (System Resource Usage Monitor) database."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import tempfile, shutil
            tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
            tmp.close()
            shutil.copy2(file_path, tmp.name)
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
        except Exception as e:
            return f"Error: Failed to open SRUM database: {e}"

        try:
            result = [f"# SRUM Analysis: `{os.path.basename(file_path)}`"]

            # List tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            result.append(f"**Total Tables:** {len(tables)}")
            result.append("")

            # Key SRUM tables
            srum_tables = {
                '{973F5D5C-1D90-4944-BE8E-24B94231A174}': 'Application Resource Usage',
                '{D10CA2FE-6FCF-4F6D-848E-B2E99266FA86}': 'Network Data Usage',
                '{FEE4E14F-02A9-4550-B5CE-5FA2DA202E37}': 'Energy Usage',
                '{DD6636C4-8929-4683-974E-22C046A43763}': 'Network Connectivity',
            }

            for table in tables:
                # Try to identify known SRUM tables
                table_name = srum_tables.get(table, table)

                try:
                    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
                    count = cursor.fetchone()[0]
                    if count > 0:
                        result.append(f"## {table_name}")
                        result.append(f"**Records:** {count:,}")

                        # Get columns
                        cursor.execute(f'PRAGMA table_info("{table}")')
                        columns = [r[1] for r in cursor.fetchall()]

                        # Sample data
                        cursor.execute(f'SELECT * FROM "{table}" LIMIT 10')
                        rows = cursor.fetchall()

                        if rows and columns:
                            result.append("| " + " | ".join(columns[:8]) + " |")
                            result.append("| " + " | ".join(["---"] * min(8, len(columns))) + " |")
                            for row in rows:
                                cells = [str(c)[:50] if c is not None else "NULL" for c in row[:8]]
                                cells = [c.replace('|', '\\|') for c in cells]
                                result.append("| " + " | ".join(cells) + " |")
                        result.append("")
                except Exception as e:
                    logger.warning(f"Error reading SRUM table {table}: {e}")
                    continue

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse SRUM database: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)


@register_extractor
class AmcacheExtractor(BaseExtractor):
    """Extracts data from Windows Amcache.hve (application execution history)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import Registry
        except ImportError:
            return "Error: python-registry library is not installed."

        try:
            reg = Registry.Registry(file_path)
            root = reg.root()

            result = [f"# Amcache Analysis: `{os.path.basename(file_path)}`"]
            result.append(f"**Root Key:** {root.name()}")
            result.append("")

            # Navigate to InventoryApplicationFile
            try:
                app_file_key = reg.open(r'Root\File\InventoryApplicationFile')
                if app_file_key:
                    result.append("## Application Execution History")
                    result.append("| Application | Publisher | Version | Last Run |")
                    result.append("| --- | --- | --- | --- |")

                    count = 0
                    for subkey in app_file_key.subkeys():
                        if count >= 100:
                            break
                        try:
                            app_name = ""
                            publisher = ""
                            version = ""
                            last_run = ""

                            for value in subkey.values():
                                if value.name() == 'LowerCaseLongPath':
                                    app_name = os.path.basename(str(value.value()))
                                elif value.name() == 'Publisher':
                                    publisher = str(value.value())
                                elif value.name() == 'Version':
                                    version = str(value.value())
                                elif value.name() == 'LastRunTime':
                                    last_run = str(value.value())

                            if app_name:
                                result.append(f"| {app_name[:50]} | {publisher[:30]} | {version[:20]} | {last_run[:20]} |")
                                count += 1
                        except: pass

                    if count >= 100:
                        result.append(f"\n*(Showing first 100 entries)*")
            except Registry.RegistryKeyNotFoundException:
                result.append("*InventoryApplicationFile key not found.*")

            # Also check InventoryApplication
            try:
                app_key = reg.open(r'Root\InventoryApplication')
                if app_key:
                    result.append("")
                    result.append("## Installed Applications")
                    result.append("| Name | Publisher | Install Date |")
                    result.append("| --- | --- | --- |")

                    count = 0
                    for subkey in app_key.subkeys():
                        if count >= 50:
                            break
                        try:
                            name = publisher = install_date = ""
                            for value in subkey.values():
                                if value.name() == 'Name':
                                    name = str(value.value())
                                elif value.name() == 'Publisher':
                                    publisher = str(value.value())
                                elif value.name() == 'InstallDate':
                                    install_date = str(value.value())
                            if name:
                                result.append(f"| {name[:50]} | {publisher[:30]} | {install_date[:20]} |")
                                count += 1
                        except: pass
            except Registry.RegistryKeyNotFoundException:
                pass

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Amcache: {e}"


@register_extractor
class ThumbcacheExtractor(BaseExtractor):
    """Extracts metadata from Windows Thumbcache databases."""

    # Thumbcache magic: CMMM (0x4D4D4D43)
    TC_MAGIC = b'\x43\x4D\x4D\x4D'

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(24)
        except Exception as e:
            return f"Error: Failed to read Thumbcache file: {e}"

        if len(header) < 24:
            return "Error: File too small to be a valid Thumbcache file."

        magic = header[:4]
        if magic != self.TC_MAGIC:
            return f"Error: Not a valid Thumbcache file (magic: {magic.hex()})"

        try:
            version = struct.unpack_from('<I', header, 4)[0]
            cache_type = struct.unpack_from('<I', header, 8)[0]
            num_entries = struct.unpack_from('<I', header, 12)[0]

            type_names = {0: '32x32', 1: '96x96', 2: '256x256', 3: '1024x1024', 4: 'SRGB', 5: 'Wide'}

            result = [f"# Thumbcache Analysis: `{os.path.basename(file_path)}`"]
            result.append(f"**Version:** {version}")
            result.append(f"**Cache Type:** {type_names.get(cache_type, f'Unknown ({cache_type})')}")
            result.append(f"**Entries:** {num_entries:,}")
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append("")

            result.append("## Thumbnail Entries")
            result.append("| # | Size | Offset |")
            result.append("| --- | --- | --- |")

            # Read entries
            offset = 24
            entry_count = 0
            try:
                with open(file_path, 'rb') as f:
                    f.seek(offset)
                    while entry_count < min(num_entries, 100):
                        entry_header = f.read(16)
                        if len(entry_header) < 16:
                            break

                        entry_size = struct.unpack_from('<I', entry_header, 0)[0]
                        entry_hash = struct.unpack_from('<I', entry_header, 4)[0]
                        entry_width = struct.unpack_from('<I', entry_header, 8)[0]
                        entry_height = struct.unpack_from('<I', entry_header, 12)[0]

                        result.append(f"| {entry_count + 1} | {entry_width}x{entry_height} | {hex(offset)} |")

                        # Skip to next entry
                        if entry_size > 0:
                            f.seek(offset + entry_size)
                            offset += entry_size
                        else:
                            break
                        entry_count += 1
            except: pass

            if entry_count >= 100:
                result.append(f"\n*(Showing first 100 entries)*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Thumbcache: {e}"


@register_extractor
class WindowsTimelineExtractor(BaseExtractor):
    """Extracts data from Windows Timeline (ActivitiesCache.db)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import tempfile, shutil
            tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
            tmp.close()
            shutil.copy2(file_path, tmp.name)
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
        except Exception as e:
            return f"Error: Failed to open ActivitiesCache database: {e}"

        try:
            result = [f"# Windows Timeline Analysis: `{os.path.basename(file_path)}`"]

            # Check for Activity table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]

            if 'Activity' in tables:
                cursor.execute("SELECT COUNT(*) FROM Activity")
                total = cursor.fetchone()[0]
                result.append(f"**Total Activities:** {total:,}")
                result.append("")

                result.append("## Recent Activities")
                result.append("| App | Title | Start | Duration | Type |")
                result.append("| --- | --- | --- | --- | --- |")

                try:
                    cursor.execute("""
                        SELECT AppActivityId, ActivityType, StartTime, EndTime,
                               AppId, DisplayText
                        FROM Activity
                        ORDER BY StartTime DESC
                        LIMIT 100
                    """)
                    for row in cursor.fetchall():
                        app_id, act_type, start, end, app_name, display = row
                        start_str = start[:19] if start else 'N/A'
                        duration = ''
                        if start and end:
                            try:
                                s = datetime.fromisoformat(start.replace('Z', '+00:00'))
                                e = datetime.fromisoformat(end.replace('Z', '+00:00'))
                                dur = (e - s).total_seconds()
                                if dur > 3600:
                                    duration = f"{dur/3600:.1f}h"
                                elif dur > 60:
                                    duration = f"{dur/60:.0f}m"
                                else:
                                    duration = f"{dur:.0f}s"
                            except: pass

                        display = (display or '').replace('|', '\\|')[:50]
                        app_name = (app_name or '').replace('|', '\\|')[:30]
                        result.append(f"| {app_name} | {display} | {start_str} | {duration} | {act_type or ''} |")
                except Exception as e:
                    result.append(f"*Error reading activities: {e}*")
            else:
                result.append("*Activity table not found. This may not be a valid ActivitiesCache.db.*")
                result.append(f"\nAvailable tables: {', '.join(tables)}")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Windows Timeline: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)
