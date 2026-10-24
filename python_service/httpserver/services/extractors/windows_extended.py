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
    """Extracts execution history from Windows Prefetch files (.pf).

    Parsing goes through libscca (pyscca), which handles both the plain SCCA
    format and the MAM-compressed container Windows 10 1809+ writes. A
    hand-rolled XPRESS Huffman decoder was attempted first and could not be
    made correct — it reproduced the SCCA header but diverged a few symbols
    later — so the library is a hard dependency rather than an optional
    upgrade. Without it the extractor reports the container metadata only,
    which is honest but loses run counts and execution timestamps.
    """

    PF_MAGIC_SCCA = b'\x53\x43\x43\x41'
    PF_MAGIC_MAM = b'\x4d\x41\x4d\x04'

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                head = f.read(8)
        except Exception as e:
            return f"Error: Failed to read Prefetch file: {e}"

        if len(head) < 8:
            return "Error: File too small to be a valid Prefetch file."

        # A plain SCCA file starts with "SCCA"; a MAM container starts with
        # "MAM\x04". Anything else is not a prefetch file.
        if head[:4] != self.PF_MAGIC_SCCA and head[:4] != self.PF_MAGIC_MAM:
            return f"Error: Not a valid Prefetch file (magic: {head[:4].hex()})"

        try:
            import pyscca
        except ImportError:
            return _prefetch_metadata_only(file_path, head,
                                           reason="libscca-python (pyscca) is not installed")

        try:
            return self._extract_with_libscca(pyscca, file_path)
        except Exception as e:
            logger.error(f"Error parsing Prefetch file {file_path}: {e}")
            return _prefetch_metadata_only(
                file_path, head, reason=f"libscca could not parse it: {e}")

    def _extract_with_libscca(self, pyscca, file_path: str) -> str:
        scca = pyscca.file()
        scca.open(file_path)
        try:
            return self._render(scca, file_path)
        finally:
            scca.close()

    def _render(self, scca, file_path: str) -> str:
        name = os.path.basename(file_path)
        result = [f"# Prefetch Analysis: `{name}`"]
        result.append(f"**Format Version:** {scca.get_format_version()}")

        executable = scca.get_executable_filename() or ""
        if executable:
            result.append(f"**Executable:** {executable}")

        try:
            result.append(f"**Prefetch Hash:** 0x{scca.get_prefetch_hash():08x}")
        except Exception:
            pass

        run_count = scca.get_run_count()
        result.append(f"**Run Count:** {run_count}")

        # Run timestamps: index 0 is the most recent execution. This is the
        # field that makes prefetch evidence: it dates program execution even
        # when the filesystem timestamps have been altered.
        timestamps = []
        for index in range(min(run_count, 8)):
            try:
                filetime = scca.get_last_run_time_as_integer(index)
            except Exception:
                continue
            if not filetime:
                continue
            parsed = _filetime_to_datetime(filetime)
            if parsed:
                timestamps.append((index, parsed))
        if timestamps:
            result.append("")
            result.append("## Last Execution Times")
            result.append("| # | UTC Time |")
            result.append("| --- | --- |")
            for index, parsed in timestamps:
                result.append(f"| {index} | {parsed.strftime('%Y-%m-%d %H:%M:%S')} |")
        elif run_count:
            result.append("*Run timestamps unavailable (device may be a solid-state "
                          "drive with timestamp recording disabled).*")

        # Volume information ties the prefetch record to the filesystem it ran
        # on, including the volume creation time.
        try:
            volume_count = scca.get_number_of_volumes()
        except Exception:
            volume_count = 0
        if volume_count:
            result.append("")
            result.append("## Volumes")
            result.append("| # | Device Path | Serial | Creation Time |")
            result.append("| --- | --- | --- | --- |")
            for index in range(volume_count):
                try:
                    volume = scca.get_volume_information(index)
                    device = volume.get_device_path() or ""
                    serial = volume.get_serial_number()
                    created = volume.get_creation_time()
                    created_text = created.strftime("%Y-%m-%d %H:%M:%S") if created else ""
                    result.append(f"| {index} | `{device}` | 0x{serial:08x} | {created_text} |")
                except Exception as exc:
                    logger.debug("volume %s unreadable: %s", index, exc)

        # Referenced files show which DLLs, data files and documents the
        # process touched. Bounded so one prefetch file cannot dominate the
        # analysis budget.
        try:
            filename_count = scca.get_number_of_filenames()
        except Exception:
            filename_count = 0
        if filename_count:
            limit = 60
            result.append("")
            result.append(f"## Referenced Files (first {min(limit, filename_count)} of {filename_count})")
            for index in range(min(limit, filename_count)):
                try:
                    entry = scca.get_filename(index)
                except Exception:
                    continue
                if entry:
                    result.append(f"- `{entry}`")

        result.append("")
        result.append("## Forensic Reading")
        result.append(f"This record establishes that `{executable or name}` executed on this "
                      f"host{(' ' + str(run_count) + ' time(s)') if run_count else ''}"
                      f"{(': most recently at ' + timestamps[0][1].strftime('%Y-%m-%d %H:%M:%S') + ' UTC') if timestamps else ''}. "
                      "Prefetch is created by the Windows prefetcher, so the record is "
                      "system-generated rather than user-supplied.")
        return "\n".join(result)


def _prefetch_metadata_only(file_path: str, head: bytes, reason: str) -> str:
    """Fallback when libscca is unavailable or rejects the file.

    Reports the container facts and states plainly which fields are missing,
    so a report never presents an unparsed prefetch file as analysed content.
    """
    name = os.path.basename(file_path)
    stem = name[:-3] if name.lower().endswith('.pf') else name
    executable, _, hash_suffix = stem.rpartition('-')
    compressed = head[:4] == b'MAM\x04'
    lines = [f"# Prefetch Analysis: `{name}`"]
    lines.append("**Format:** " + ("MAM-compressed Prefetch (XPRESS Huffman)"
                                   if compressed else "SCCA Prefetch"))
    if executable:
        lines.append(f"**Executable:** {executable}")
    if hash_suffix:
        lines.append(f"**Path Hash:** {hash_suffix}")
    if compressed and len(head) >= 8:
        expected = struct.unpack_from('<I', head, 4)[0]
        if expected:
            lines.append(f"**Declared Uncompressed Size:** {_format_size(expected)}")
    lines.append("")
    lines.append("## Parsing Status")
    lines.append(f"The payload was not decoded: {reason}.")
    lines.append("Run counts, execution timestamps and referenced files are "
                 "**not available** for this file.")
    lines.append("")
    lines.append("## What the metadata establishes")
    lines.append(f"The file name records that `{executable or 'an executable'}` has a "
                 "Prefetch entry on this host, i.e. Windows created a tracing record "
                 "for it. Execution timing requires a decoded payload and is not "
                 "inferred here.")
    return "\n".join(lines)


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
            # python-registry 1.3 exposes the class only in the Registry.Registry
            # submodule; `import Registry` leaves the package namespace empty.
            from Registry.Registry import Registry, RegistryKeyNotFoundException
        except ImportError:
            return "Error: python-registry library is not installed."

        try:
            reg = Registry(file_path)
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
            except RegistryKeyNotFoundException:
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
            except RegistryKeyNotFoundException:
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
