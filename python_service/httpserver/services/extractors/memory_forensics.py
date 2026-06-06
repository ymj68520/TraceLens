"""Memory forensics extractors: Windows DMP, LiME, raw memory dumps."""
import logging
import os
import struct
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024: return f"{size_bytes/1024/1024:.2f} MB"
    else: return f"{size_bytes/1024/1024/1024:.2f} GB"


@register_extractor
class WindowsDmpExtractor(BaseExtractor):
    """Extracts metadata from Windows memory dump files (.dmp)."""

    # DMP magic: PAGE (0x45474150) or DUMP (0x504D5544)
    DMP_MAGIC_PAGE = b'PAGE'
    DMP_MAGIC_DUMP = b'DUMP'

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4096)
        except Exception as e:
            return f"Error: Failed to read DMP file: {e}"

        if len(header) < 32:
            return "Error: File too small to be a valid DMP file."

        magic = header[:4]

        result = [f"# Memory Dump Analysis: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        if magic == self.DMP_MAGIC_PAGE:
            result.append("**Format:** Windows Full Memory Dump (PAGE)")

            # Parse DMP header
            try:
                # PhysicalMemoryBlock at offset 32
                signature = struct.unpack_from('<I', header, 0)[0]
                valid_dump = struct.unpack_from('<I', header, 4)[0]

                if valid_dump == 0x504D5544:  # "DUMP"
                    result.append("**Valid Dump:** Yes")

                # Machine type
                machine = struct.unpack_from('<H', header, 8)[0]
                machine_types = {0x8664: 'x64', 0x014C: 'x86', 0xAA64: 'ARM64'}
                result.append(f"**Architecture:** {machine_types.get(machine, f'Unknown ({hex(machine)})')}")

                # Number of runs
                number_of_runs = struct.unpack_from('<I', header, 12)[0]
                result.append(f"**Memory Runs:** {number_of_runs}")

                # Calculate total physical memory
                total_memory = 0
                for i in range(min(number_of_runs, 100)):
                    run_offset = 32 + i * 16
                    if run_offset + 16 <= len(header):
                        base_page = struct.unpack_from('<Q', header, run_offset)[0]
                        page_count = struct.unpack_from('<Q', header, run_offset + 8)[0]
                        total_memory += page_count * 4096

                result.append(f"**Physical Memory:** {_format_size(total_memory)}")
            except Exception as e:
                result.append(f"*Error parsing header: {e}*")

        elif magic == self.DMP_MAGIC_DUMP:
            result.append("**Format:** Windows Crash Dump (DUMP)")

            try:
                # Parse crash dump header
                machine = struct.unpack_from('<I', header, 12)[0]
                machine_types = {0x8664: 'x64', 0x014C: 'x86', 0xAA64: 'ARM64'}
                result.append(f"**Architecture:** {machine_types.get(machine, f'Unknown ({hex(machine)})')}")

                # Bugcheck code
                bugcheck_code = struct.unpack_from('<I', header, 16)[0]
                result.append(f"**Bugcheck Code:** {hex(bugcheck_code)}")

                # Timestamp
                ts = struct.unpack_from('<Q', header, 24)[0]
                if ts > 0:
                    try:
                        dt = datetime.fromtimestamp((ts - 116444736000000000) / 10000000)
                        result.append(f"**Crash Time:** {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                    except: pass
            except Exception as e:
                result.append(f"*Error parsing header: {e}*")

        elif magic == b'\x00\x00\x00\x00':
            result.append("**Format:** Raw Memory Dump / LiME")
            result.append("")
            result.append("*Raw memory dump detected. Analysis requires specialized tools (Volatility, Rekall).*")
            result.append("")
            result.append("## Basic Analysis")

            # Try to find strings
            try:
                with open(file_path, 'rb') as f:
                    sample = f.read(min(10*1024*1024, os.path.getsize(file_path)))

                # Look for common patterns
                import re
                urls = re.findall(rb'https?://[^\x00\x20]{5,200}', sample)
                ips = re.findall(rb'\b(?:\d{1,3}\.){3}\d{1,3}\b', sample)
                emails = re.findall(rb'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', sample)

                if urls:
                    result.append("### URLs Found in Memory")
                    seen = set()
                    for url in urls[:20]:
                        u = url.decode('ascii', errors='replace')
                        if u not in seen:
                            seen.add(u)
                            result.append(f"- `{u}`")

                if emails:
                    result.append("")
                    result.append("### Email Addresses Found")
                    seen = set()
                    for email in emails[:20]:
                        e = email.decode('ascii', errors='replace')
                        if e not in seen:
                            seen.add(e)
                            result.append(f"- `{e}`")
            except: pass

        else:
            result.append(f"**Magic:** {magic.hex()}")
            result.append("")
            result.append("*Unknown memory dump format.*")

        return "\n".join(result)


@register_extractor
class LimeExtractor(BaseExtractor):
    """Extracts metadata from LiME (Linux Memory Extractor) format dumps."""

    # LiME magic: 0x4C694D45 (LiME)
    LIME_MAGIC = b'\x45\x4d\x69\x4c'  # LiME in little-endian

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(20)
        except Exception as e:
            return f"Error: Failed to read LiME file: {e}"

        if len(header) < 20:
            return "Error: File too small to be a valid LiME dump."

        magic = header[:4]

        result = [f"# LiME Memory Dump: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        if magic == self.LIME_MAGIC:
            result.append("**Format:** LiME (Linux Memory Extractor)")

            try:
                version = struct.unpack_from('<I', header, 4)[0]
                ram_size = struct.unpack_from('<Q', header, 8)[0]
                padding = struct.unpack_from('<I', header, 16)[0]

                result.append(f"**Version:** {version}")
                result.append(f"**RAM Size:** {_format_size(ram_size)}")
            except: pass
        else:
            result.append("**Format:** Raw Linux Memory Dump")

        result.append("")
        result.append("*Full analysis requires Volatility framework.*")
        result.append("")
        result.append("## Basic Analysis")

        # Scan for interesting strings
        try:
            with open(file_path, 'rb') as f:
                sample = f.read(min(10*1024*1024, os.path.getsize(file_path)))

            import re
            # Look for process names, IPs, URLs
            ips = list(set(re.findall(rb'\b(?:\d{1,3}\.){3}\d{1,3}\b', sample)))[:20]
            urls = list(set(re.findall(rb'https?://[^\x00\x20]{5,200}', sample)))[:20]

            if ips:
                result.append("### IP Addresses Found")
                for ip in ips:
                    result.append(f"- `{ip.decode('ascii', errors='replace')}`")

            if urls:
                result.append("")
                result.append("### URLs Found")
                for url in urls:
                    result.append(f"- `{url.decode('ascii', errors='replace')}`")
        except: pass

        return "\n".join(result)


@register_extractor
class RawMemoryExtractor(BaseExtractor):
    """Extracts basic info from raw memory dumps (.raw, .mem, .bin)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()
        file_size = os.path.getsize(file_path)

        result = [f"# Raw Memory Dump: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(file_size)}")
        result.append(f"**Format:** Raw memory dump ({ext})")
        result.append("")

        # Check if it looks like a memory dump
        try:
            with open(file_path, 'rb') as f:
                header = f.read(4096)

            # Check for signatures
            if b'PAGE' in header[:64]:
                result.append("**Likely Format:** Windows memory dump")
            elif b'LiME' in header[:64]:
                result.append("**Likely Format:** LiME memory dump")
            elif b'ELF' in header[:4]:
                result.append("**Likely Format:** ELF core dump")
            else:
                result.append("**Likely Format:** Generic raw memory dump")

            result.append("")
            result.append("*Full analysis requires specialized memory forensics tools (Volatility, Rekall).*")

            # Basic string extraction
            result.append("")
            result.append("## Notable Strings (Sample)")

            import re
            # Read a sample
            sample_size = min(5*1024*1024, file_size)
            with open(file_path, 'rb') as f:
                sample = f.read(sample_size)

            # Find interesting patterns
            urls = list(set(re.findall(rb'https?://[^\x00\x20]{5,200}', sample)))[:10]
            paths = list(set(re.findall(rb'[A-Z]:\\[^\x00]{5,200}', sample)))[:10]

            if urls:
                result.append("### URLs")
                for u in urls:
                    result.append(f"- `{u.decode('ascii', errors='replace')}`")

            if paths:
                result.append("### File Paths")
                for p in paths:
                    result.append(f"- `{p.decode('ascii', errors='replace')}`")

            if not urls and not paths:
                result.append("*No notable strings found in sample.*")
        except Exception as e:
            result.append(f"*Error analyzing dump: {e}*")

        return "\n".join(result)
