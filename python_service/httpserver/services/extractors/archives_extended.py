"""Extended archive extractors: BZ2, XZ, LZ4, ZST, CAB, ISO."""
import logging
import os
import struct
from collections import defaultdict

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024: return f"{size_bytes/1024/1024:.2f} MB"
    else: return f"{size_bytes/1024/1024/1024:.2f} GB"


@register_extractor
class Bz2Extractor(BaseExtractor):
    """Extracts metadata from BZ2 compressed files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        import bz2

        result = [f"# BZ2 Archive: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** BZ2 (bzip2 compressed)")

        try:
            # Try to decompress and check if it's a tar
            import tarfile
            import tempfile

            with open(file_path, 'rb') as f:
                magic = f.read(3)

            if magic != b'BZh':
                return f"Error: Not a valid BZ2 file (magic: {magic.hex()})"

            # Check if it's a tar.bz2
            try:
                with bz2.open(file_path, 'rb') as bz2_f:
                    # Read first few bytes to check for tar magic
                    header = bz2_f.read(262)
                    if header[257:262] == b'ustar':
                        result.append(f"**Type:** Tar archive compressed with BZ2")
                        # Try to list tar contents
                        bz2_f.seek(0)
                        with tarfile.open(fileobj=bz2_f, mode='r:*') as tar:
                            members = tar.getmembers()
                            total_size = sum(m.size for m in members if m.isfile())
                            result.append(f"**Total Files:** {len([m for m in members if m.isfile()])}")
                            result.append(f"**Uncompressed Size:** {_format_size(total_size)}")
                            result.append("")
                            result.append("## Contents (First 50)")
                            result.append("| File | Size |")
                            result.append("| --- | --- |")
                            for m in members[:50]:
                                if m.isfile():
                                    result.append(f"| {m.name} | {_format_size(m.size)} |")
                    else:
                        result.append(f"**Type:** Compressed file (not tar)")
                        result.append("")
                        result.append("*Single compressed file. Decompress to analyze contents.*")
            except Exception:
                result.append("")
                result.append("*Could not read archive contents.*")
        except Exception as e:
            return f"Error: Failed to parse BZ2 file: {e}"

        return "\n".join(result)


@register_extractor
class XzExtractor(BaseExtractor):
    """Extracts metadata from XZ/LZMA compressed files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        import lzma

        result = [f"# XZ Archive: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** XZ (LZMA2 compressed)")

        try:
            with open(file_path, 'rb') as f:
                magic = f.read(6)

            if magic[:6] != b'\xfd7zXZ\x00':
                return f"Error: Not a valid XZ file"

            try:
                import tarfile
                with lzma.open(file_path, 'rb') as xz_f:
                    header = xz_f.read(262)
                    if header[257:262] == b'ustar':
                        result.append(f"**Type:** Tar archive compressed with XZ")
                        xz_f.seek(0)
                        with tarfile.open(fileobj=xz_f, mode='r:*') as tar:
                            members = tar.getmembers()
                            total_size = sum(m.size for m in members if m.isfile())
                            result.append(f"**Total Files:** {len([m for m in members if m.isfile()])}")
                            result.append(f"**Uncompressed Size:** {_format_size(total_size)}")
                            result.append("")
                            result.append("## Contents (First 50)")
                            result.append("| File | Size |")
                            result.append("| --- | --- |")
                            for m in members[:50]:
                                if m.isfile():
                                    result.append(f"| {m.name} | {_format_size(m.size)} |")
                    else:
                        result.append(f"**Type:** Compressed file (not tar)")
            except Exception:
                result.append("")
                result.append("*Could not read archive contents.*")
        except Exception as e:
            return f"Error: Failed to parse XZ file: {e}"

        return "\n".join(result)


@register_extractor
class Lz4Extractor(BaseExtractor):
    """Extracts metadata from LZ4 compressed files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        result = [f"# LZ4 Archive: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** LZ4 compressed")

        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)

            # LZ4 legacy magic: 0x184D2204
            # LZ4 skippable: 0x184D2A50-0x184D2A5F
            if magic == b'\x04\x22\x4d\x18':
                result.append(f"**Type:** LZ4 frame format")
            else:
                result.append(f"**Type:** LZ4 (magic: {magic.hex()})")

            result.append("")
            result.append("*LZ4 decompression requires the `lz4` library. Install `lz4` for content extraction.*")

            # Try lz4 library
            try:
                import lz4.frame
                with open(file_path, 'rb') as f:
                    compressed = f.read()
                decompressed = lz4.frame.decompress(compressed)
                result.append(f"**Uncompressed Size:** {_format_size(len(decompressed))}")

                # Check if it's a tar
                if decompressed[257:262] == b'ustar':
                    import tarfile, io
                    result.append(f"**Type:** Tar archive compressed with LZ4")
                    with tarfile.open(fileobj=io.BytesIO(decompressed), mode='r:*') as tar:
                        members = tar.getmembers()
                        result.append(f"**Total Files:** {len([m for m in members if m.isfile()])}")
                        result.append("")
                        result.append("## Contents (First 50)")
                        result.append("| File | Size |")
                        result.append("| --- | --- |")
                        for m in members[:50]:
                            if m.isfile():
                                result.append(f"| {m.name} | {_format_size(m.size)} |")
            except ImportError:
                pass
            except Exception as e:
                result.append(f"*Error decompressing: {e}*")
        except Exception as e:
            return f"Error: Failed to parse LZ4 file: {e}"

        return "\n".join(result)


@register_extractor
class ZstExtractor(BaseExtractor):
    """Extracts metadata from Zstandard compressed files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        result = [f"# Zstandard Archive: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** Zstandard (zstd) compressed")

        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)

            # ZSTD magic: 0xFD2FB528 (little-endian: 28 B5 2F FD)
            if magic == b'\x28\xb5\x2f\xfd':
                result.append(f"**Type:** Zstandard frame format")
            else:
                result.append(f"**Type:** (magic: {magic.hex()})")

            result.append("")

            try:
                import zstandard as zstd
                with open(file_path, 'rb') as f:
                    compressed = f.read()
                dctx = zstd.ZstdDecompressor()
                decompressed = dctx.decompress(compressed, max_output_size=100*1024*1024)
                result.append(f"**Uncompressed Size:** {_format_size(len(decompressed))}")

                if decompressed[257:262] == b'ustar':
                    import tarfile, io
                    result.append(f"**Type:** Tar archive compressed with Zstandard")
                    with tarfile.open(fileobj=io.BytesIO(decompressed), mode='r:*') as tar:
                        members = tar.getmembers()
                        result.append(f"**Total Files:** {len([m for m in members if m.isfile()])}")
                        result.append("")
                        result.append("## Contents (First 50)")
                        result.append("| File | Size |")
                        result.append("| --- | --- |")
                        for m in members[:50]:
                            if m.isfile():
                                result.append(f"| {m.name} | {_format_size(m.size)} |")
            except ImportError:
                result.append("*Install `zstandard` library for decompression.*")
            except Exception as e:
                result.append(f"*Error decompressing: {e}*")
        except Exception as e:
            return f"Error: Failed to parse ZST file: {e}"

        return "\n".join(result)


@register_extractor
class IsoExtractor(BaseExtractor):
    """Extracts file listing from ISO disc images."""

    async def extract_to_markdown(self, file_path: str) -> str:
        result = [f"# ISO Image: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** ISO 9660 disc image")

        try:
            with open(file_path, 'rb') as f:
                # Check for ISO 9660 magic at offset 32769
                f.seek(32769)
                magic = f.read(5)

                if magic == b'CD001':
                    result.append(f"**Type:** ISO 9660 (standard)")

                    # Try pycdlib
                    try:
                        import pycdlib
                        iso = pycdlib.Pycdlib()
                        iso.open(file_path)

                        entries = []
                        for dirname, dirlist, filelist in iso.walk(iso_path='/'):
                            for f in filelist:
                                entries.append(os.path.join(dirname, f.decode() if isinstance(f, bytes) else f))

                        result.append(f"**Total Files:** {len(entries)}")
                        result.append("")
                        result.append("## File Listing (First 100)")
                        for entry in entries[:100]:
                            result.append(f"- {entry}")
                        if len(entries) > 100:
                            result.append(f"\n*(Showing first 100 of {len(entries)} files)*")

                        iso.close()
                    except ImportError:
                        result.append("")
                        result.append("*Install `pycdlib` for full ISO content listing.*")
                    except Exception as e:
                        result.append(f"*Error reading ISO: {e}*")
                elif magic == b'BEA01':
                    result.append(f"**Type:** ISO 9660 (multi-session/UDF)")
                else:
                    result.append(f"**Magic:** {magic}")
        except Exception as e:
            return f"Error: Failed to parse ISO file: {e}"

        return "\n".join(result)


@register_extractor
class CabExtractor(BaseExtractor):
    """Extracts metadata from Microsoft Cabinet (.cab) files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        result = [f"# Cabinet Archive: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** Microsoft Cabinet (.cab)")

        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)

                if magic != b'MSCF':
                    return f"Error: Not a valid CAB file (magic: {magic.hex()})"

                # Parse CAB header
                f.seek(8)
                total_size = struct.unpack('<I', f.read(4))[0]
                f.read(4)  # reserved
                offset_cffile = struct.unpack('<I', f.read(4))[0]
                num_files = struct.unpack('<I', f.read(4))[0]

                result.append(f"**Total Files:** {num_files}")
                result.append("")

                # Read file entries
                result.append("## File Listing")
                result.append("| File | Size | Date |")
                result.append("| --- | --- | --- |")

                f.seek(offset_cffile)
                for i in range(min(num_files, 100)):
                    entry = f.read(16)
                    if len(entry) < 16:
                        break
                    uncompressed_size = struct.unpack('<I', entry[0:4])[0]
                    date = struct.unpack('<H', entry[10:12])[0]
                    time = struct.unpack('<H', entry[12:14])[0]

                    # Read filename (null-terminated)
                    name_bytes = b''
                    while True:
                        b = f.read(1)
                        if b == b'\x00' or not b:
                            break
                        name_bytes += b

                    name = name_bytes.decode('cp1252', errors='replace')

                    # Parse date
                    year = ((date >> 9) & 0x7F) + 1980
                    month = (date >> 5) & 0x0F
                    day = date & 0x1F
                    date_str = f"{year}-{month:02d}-{day:02d}"

                    result.append(f"| {name} | {_format_size(uncompressed_size)} | {date_str} |")

                if num_files > 100:
                    result.append(f"\n*(Showing first 100 of {num_files} files)*")
        except Exception as e:
            return f"Error: Failed to parse CAB file: {e}"

        return "\n".join(result)
