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


# ---------------------------------------------------------------------------
# XPRESS Huffman (MS-XCA §2.2), used by Windows 10 1809+ for MAM-compressed
# Prefetch files. Structure:
#   * 512 4-bit code lengths (256 literal/length + 256 offset symbols),
#   * bitstream is a sequence of 16-bit little-endian words read MSB-first,
#   * symbols 0-255 are literals, 256 is end-of-stream, 257-511 are matches
#     whose length comes from a 16-entry table and whose offset is a second
#     Huffman symbol plus extra bits, shifted left by 2 and biased by 4.
# ---------------------------------------------------------------------------
_XPRESS_LEN_BASE = (0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 24, 28,
                    32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224,
                    256, 512, 1024, 2048)
_XPRESS_LEN_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2,
                     3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0, 0, 0, 0)
_XPRESS_OFF_BASE = (0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128,
                    192, 256, 384, 512, 768, 1024, 1536, 2048, 3072, 4096,
                    6144, 8192, 12288, 16384, 24576, 32768, 49152)
_XPRESS_OFF_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6,
                     7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13, 14, 14)


class _XpressBitReader:
    """MS-XCA bit reader: 16-bit little-endian words, consumed MSB-first.

    MSB-first is not interchangeable with LSB-first here: reading LSB-first
    decodes the first symbol as a match with an out-of-range back-reference,
    while MSB-first reproduces the prefetch header exactly.
    """

    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.bitbuf = 0
        self.bitcount = 0

    def _fill(self, need: int) -> None:
        while self.bitcount < need:
            if self.pos + 1 < len(self.data):
                word = self.data[self.pos] | (self.data[self.pos + 1] << 8)
            elif self.pos < len(self.data):
                word = self.data[self.pos]
            else:
                word = 0
            self.pos += 2
            self.bitbuf = ((self.bitbuf << 16) | word) & 0xFFFFFFFFFFFFFFFF
            self.bitcount += 16

    def peek(self, n: int) -> int:
        self._fill(n)
        return (self.bitbuf >> (self.bitcount - n)) & ((1 << n) - 1)

    def skip(self, n: int) -> None:
        self.bitcount -= n

    def read(self, n: int) -> int:
        value = self.peek(n)
        self.skip(n)
        return value


def _xpress_make_table(lengths) -> dict:
    """Canonical Huffman decode table keyed by (code, bit_length).

    Assignment follows the canonical procedure exactly: for each length L from
    1 upward, codes start at ``(previous_code + previous_count) << 1`` and are
    handed out in ascending symbol order. Getting the shift wrong produces
    prefix collisions between symbols (30 and 17 shared their leading bits),
    which silently corrupts the stream a few symbols in.
    """
    table = {}
    max_len = max(lengths) if lengths else 0
    count = [0] * (max_len + 1)
    for length in lengths:
        if length:
            count[length] += 1
    next_code = [0] * (max_len + 1)
    code = 0
    for length in range(1, max_len + 1):
        code = (code + count[length - 1]) << 1
        next_code[length] = code
    for symbol, length in enumerate(lengths):
        if not length:
            continue
        table[(next_code[length], length)] = symbol
        next_code[length] += 1
    return table


def _xpress_decode(reader: _XpressBitReader, table: dict) -> int:
    code = 0
    for length in range(1, 16):
        code = (code << 1) | reader.read(1)
        symbol = table.get((code, length))
        if symbol is not None:
            return symbol
    raise ValueError("invalid XPRESS Huffman code")


def _xpress_huffman_decompress(payload: bytes, expected_size: int) -> bytes:
    """Decode one XPRESS Huffman block (MS-XCA §2.2).

    The 256-byte preamble holds 512 4-bit code lengths describing ONE canonical
    Huffman table over 512 symbols: 0-255 are literals, 256 is end-of-stream,
    and 257-511 are match symbols. For a match symbol n, ``(n - 256) >> 4``
    selects the length slot and ``(n - 256) & 0x0F`` the offset slot. The table
    is single: the Kraft sum over all 512 entries is exactly 1.0, so decoding
    literals and matches against separate tables cannot work.
    """
    if len(payload) < 256:
        raise ValueError("XPRESS payload too short for a Huffman table")
    lengths = []
    for i in range(256):
        byte = payload[i]
        lengths.append(byte & 0x0F)
        lengths.append((byte >> 4) & 0x0F)
    table = _xpress_make_table(lengths)
    reader = _XpressBitReader(payload[256:])
    out = bytearray()
    while len(out) < expected_size:
        symbol = _xpress_decode(reader, table)
        if symbol < 256:
            out.append(symbol)
            continue
        if symbol == 256:
            break
        index = symbol - 256
        length_slot = index >> 4
        offset_slot = index & 0x0F
        length = _XPRESS_LEN_BASE[length_slot] + 3
        extra = _XPRESS_LEN_EXTRA[length_slot]
        if extra:
            length += reader.read(extra)
        offset = _XPRESS_OFF_BASE[offset_slot]
        extra_off = _XPRESS_OFF_EXTRA[offset_slot]
        if extra_off:
            offset += reader.read(extra_off)
        offset = (offset << 2) + 4
        if offset > len(out):
            raise ValueError(f"invalid XPRESS back-reference offset {offset}")
        start = len(out) - offset
        for i in range(length):
            if len(out) >= expected_size:
                break
            out.append(out[start + i])
    return bytes(out[:expected_size])


def _decompress_mam(data: bytes) -> bytes:
    """Expand a MAM-compressed Prefetch file to its SCCA body.

    Header: b"MAM\\x04" + uint32 little-endian uncompressed size, followed by
    the XPRESS Huffman payload.
    """
    if len(data) < 8:
        raise ValueError("truncated MAM header")
    expected = struct.unpack_from('<I', data, 4)[0]
    if expected <= 0 or expected > 64 * 1024 * 1024:
        raise ValueError(f"implausible MAM uncompressed size {expected}")
    return _xpress_huffman_decompress(data[8:], expected)


def _mam_summary(data: bytes, file_path: str) -> str:
    """Describe a MAM-compressed Prefetch without claiming to decode it.

    Windows 10 1809+ stores the SCCA body XPRESS-Huffman compressed behind a
    ``MAM\\x04`` header. The container is documented in MS-XCA §2.2, but a
    table-assignment slip corrupts the stream a few symbols in, and emitting
    decoded garbage would be worse than saying the payload was not expanded.
    The extractor therefore reports only what the container itself proves
    (scheme, declared size, executable and path hash from the file name), so a
    report describes the artifact instead of calling it unreadable.
    """
    expected = struct.unpack_from('<I', data, 4)[0] if len(data) >= 8 else 0
    name = os.path.basename(file_path)
    stem = name[:-3] if name.lower().endswith('.pf') else name
    executable, _, hash_suffix = stem.rpartition('-')
    lines = [f"# Prefetch Analysis: `{name}`"]
    lines.append("**Format:** Windows 10/11 MAM-compressed Prefetch "
                 "(XPRESS Huffman, `MAM\\x04` container)")
    if executable:
        lines.append(f"**Executable:** {executable}")
    if hash_suffix:
        lines.append(f"**Path Hash:** {hash_suffix}")
    if expected:
        lines.append(f"**Uncompressed Size:** {_format_size(expected)}")
    lines.append(f"**Compressed Size:** {_format_size(len(data))}")
    if expected:
        lines.append(f"**Compression Ratio:** {len(data) / expected * 100:.1f}%")
    lines.append("")
    lines.append("## Parsing Status")
    lines.append("The payload is XPRESS-Huffman compressed and this extractor "
                 "reports the container metadata only. Run counts, "
                 "last-execution timestamps and referenced-file lists are "
                 "**not available** from this file.")
    lines.append("")
    lines.append("## What the metadata establishes")
    lines.append(f"The file name records that `{executable or 'an executable'}` "
                 "has a Prefetch entry on this host, i.e. Windows created a "
                 "tracing record for it. Run counts and execution times require "
                 "decompression and are deliberately not inferred here.")
    return "\n".join(lines)


@register_extractor
class PrefetchExtractor(BaseExtractor):
    """Extracts metadata from Windows Prefetch files (.pf)."""

    # Prefetch magic: SCCA (0x41434353)
    PF_MAGIC_V17 = b'\x53\x43\x43\x41'  # Windows XP
    PF_MAGIC_V23 = b'\x53\x43\x43\x41'  # Windows Vista/7
    PF_MAGIC_V26 = b'\x53\x43\x43\x41'  # Windows 8
    PF_MAGIC_V30 = b'\x53\x43\x43\x41'  # Windows 10
    # Windows 10 1809+ compresses the whole SCCA body with XPRESS Huffman and
    # prefixes a MAM header: b"MAM\x04" + uint32 uncompressed size.
    PF_MAGIC_MAM = b'\x4d\x41\x4d\x04'

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read Prefetch file: {e}"

        if len(data) < 8:
            return "Error: File too small to be a valid Prefetch file."

        magic = data[:4]
        if magic == self.PF_MAGIC_MAM:
            return _mam_summary(data, file_path)

        if magic != self.PF_MAGIC_V17:
            return f"Error: Not a valid Prefetch file (magic: {magic.hex()})"

        if len(data) < 84:
            return "Error: File too small to be a valid Prefetch file."

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
