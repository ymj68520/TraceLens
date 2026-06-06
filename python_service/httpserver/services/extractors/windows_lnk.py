"""Windows LNK shortcut and Jump List forensic extractors."""
import logging
import os
import struct
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

LNK_MAGIC = b'\x4c\x00\x00\x00'
LNK_FLAG_HAS_TARGET_ID_LIST = 0x00000001
LNK_FLAG_HAS_LINK_INFO = 0x00000002
LNK_FLAG_HAS_NAME = 0x00000004
LNK_FLAG_HAS_WORKING_DIR = 0x00000010
LNK_FLAG_HAS_ARGUMENTS = 0x00000020
LNK_FLAG_HAS_ICON_LOCATION = 0x00000040

DRIVE_TYPES = {0: "Unknown", 1: "No Root Dir", 2: "Removable", 3: "Fixed", 4: "Remote", 5: "CD-ROM", 6: "RAM Disk"}


def _filetime_to_datetime(filetime: int) -> datetime:
    if filetime == 0:
        return None
    try:
        return datetime.fromtimestamp((filetime - 116444736000000000) / 10000000)
    except (ValueError, OSError, OverflowError):
        return None


def _format_datetime(dt: datetime) -> str:
    return dt.strftime('%Y-%m-%d %H:%M:%S') if dt else "N/A"


@register_extractor
class LnkExtractor(BaseExtractor):
    """Extracts content from Windows LNK shortcut files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read LNK file: {e}"

        if len(data) < 76:
            return "Error: File too small to be a valid LNK file."
        if data[:4] != LNK_MAGIC:
            return f"Error: Not a valid LNK file (magic: {data[:4].hex()})"

        try:
            return self._parse_lnk(file_path, data)
        except Exception as e:
            return f"Error: Failed to parse LNK file: {e}"

    def _parse_lnk(self, file_path: str, data: bytes) -> str:
        flags = struct.unpack_from('<I', data, 20)[0]
        creation_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 28)[0])
        access_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 36)[0])
        modification_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 44)[0])
        file_size = struct.unpack_from('<I', data, 52)[0]

        target_path = volume_serial = drive_type = machine_id = mac_address = ""

        if flags & LNK_FLAG_HAS_LINK_INFO:
            link_info_offset = struct.unpack_from('<I', data, 24)[0]
            if link_info_offset < len(data):
                target_path, volume_serial, drive_type = self._parse_link_info(data, link_info_offset)

        working_dir = arguments = description = icon_location = ""
        offset = 76

        if flags & LNK_FLAG_HAS_TARGET_ID_LIST:
            id_list_size = struct.unpack_from('<H', data, offset)[0]
            offset += 2 + id_list_size
        if flags & LNK_FLAG_HAS_LINK_INFO:
            link_info_size = struct.unpack_from('<I', data, offset)[0]
            offset += link_info_size

        for flag, name in [(LNK_FLAG_HAS_NAME, 'description'), (LNK_FLAG_HAS_WORKING_DIR, 'working_dir'),
                           (LNK_FLAG_HAS_ARGUMENTS, 'arguments'), (LNK_FLAG_HAS_ICON_LOCATION, 'icon_location')]:
            if flags & flag:
                count = struct.unpack_from('<I', data, offset)[0]
                offset += 4
                if flags & 0x00000008:
                    val = data[offset:offset + count * 2].decode('utf-16-le', errors='replace').rstrip('\x00')
                    offset += count * 2
                else:
                    val = data[offset:offset + count].decode('cp1252', errors='replace').rstrip('\x00')
                    offset += count
                locals()[name] = val

        machine_id, mac_address = self._parse_extra_data(data, offset)

        result = [f"# Windows Shortcut Analysis: `{os.path.basename(file_path)}`"]
        result.append(f"**Target Path:** {target_path or 'N/A'}")
        if working_dir: result.append(f"**Working Directory:** {working_dir}")
        if arguments: result.append(f"**Arguments:** {arguments}")
        if description: result.append(f"**Description:** {description}")
        result.append("")

        result.append("## Timestamps")
        result.append("| Type | Timestamp |")
        result.append("| --- | --- |")
        result.append(f"| Created | {_format_datetime(creation_time)} |")
        result.append(f"| Modified | {_format_datetime(modification_time)} |")
        result.append(f"| Accessed | {_format_datetime(access_time)} |")
        result.append("")

        result.append("## Target Information")
        if drive_type: result.append(f"**Drive Type:** {drive_type}")
        if volume_serial: result.append(f"**Volume Serial:** {volume_serial}")
        result.append(f"**File Size:** {file_size:,} bytes")
        result.append("")

        if machine_id or mac_address:
            result.append("## Machine Info")
            if machine_id: result.append(f"**Machine ID:** {machine_id}")
            if mac_address: result.append(f"**MAC Address:** {mac_address}")

        return "\n".join(result)

    def _parse_link_info(self, data: bytes, offset: int) -> tuple:
        target_path = volume_serial = drive_type = ""
        try:
            flags = struct.unpack_from('<I', data, offset + 8)[0]
            if flags & 0x00000001:
                volume_id_offset = struct.unpack_from('<I', data, offset + 16)[0]
                local_base_path_offset = struct.unpack_from('<I', data, offset + 20)[0]
                if volume_id_offset > 0:
                    vol_offset = offset + volume_id_offset
                    drive_type = DRIVE_TYPES.get(struct.unpack_from('<I', data, vol_offset + 4)[0], "Unknown")
                    volume_serial = f"{struct.unpack_from('<I', data, vol_offset + 8)[0]:08X}"
                if local_base_path_offset > 0:
                    path_offset = offset + local_base_path_offset
                    end = data.find(b'\x00', path_offset)
                    if end > path_offset:
                        target_path = data[path_offset:end].decode('cp1252', errors='replace')
        except Exception as e:
            logger.warning(f"Error parsing LinkInfo: {e}")
        return target_path, volume_serial, drive_type

    def _parse_extra_data(self, data: bytes, offset: int) -> tuple:
        machine_id = mac_address = ""
        try:
            while offset + 8 < len(data):
                size = struct.unpack_from('<I', data, offset)[0]
                if size < 4: break
                sig = struct.unpack_from('<I', data, offset + 4)[0]
                if sig == 0xA0000004 and size >= 32:
                    machine_id = data[offset + 16:offset + 32].decode('cp1252', errors='replace').rstrip('\x00')
                    if size >= 38:
                        mac_bytes = struct.unpack_from('6B', data, offset + 32)
                        mac_address = ':'.join(f'{b:02X}' for b in mac_bytes)
                offset += size
        except Exception as e:
            logger.warning(f"Error parsing ExtraData: {e}")
        return machine_id, mac_address


@register_extractor
class JumplistExtractor(BaseExtractor):
    """Extracts content from Windows Jump List files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile
        except ImportError:
            return "Error: olefile library is not installed."

        filename = os.path.basename(file_path)
        if file_path.endswith('.automaticDestinations-ms'):
            return self._parse_automatic(file_path, filename)
        elif file_path.endswith('.customDestinations-ms'):
            return self._parse_custom(file_path, filename)
        return "Error: Unknown Jump List format."

    def _parse_automatic(self, file_path: str, filename: str) -> str:
        import olefile
        try:
            ole = olefile.OleFileIO(file_path)
        except Exception as e:
            return f"Error: Failed to open Jump List: {e}"

        try:
            app_id = filename.split('.')[0]
            result = [f"# Jump List Analysis: `{filename}`"]
            result.append(f"**Application ID:** {app_id}")
            result.append("**Type:** Automatic Destination")
            result.append("")

            lnk_entries = []
            for stream in ole.listdir():
                if '/'.join(stream).startswith('DestList'):
                    continue
                try:
                    data = ole.openstream(stream).read()
                    if len(data) >= 4 and data[:4] == LNK_MAGIC:
                        entry = self._parse_lnk_data(data)
                        if entry: lnk_entries.append(entry)
                except: pass

            result.append(f"**Entry Count:** {len(lnk_entries)}")
            result.append("")
            if lnk_entries:
                result.append("## Recent Documents")
                result.append("| # | Target Path | Last Modified |")
                result.append("| --- | --- | --- |")
                for i, entry in enumerate(lnk_entries[:50], 1):
                    result.append(f"| {i} | {entry.get('target_path', 'N/A')} | {_format_datetime(entry.get('modification_time'))} |")
            else:
                result.append("*No LNK entries found.*")
            return "\n".join(result)
        finally:
            ole.close()

    def _parse_custom(self, file_path: str, filename: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read Jump List: {e}"

        result = [f"# Jump List Analysis: `{filename}`"]
        result.append("**Type:** Custom Destination")
        result.append("")

        lnk_entries = []
        offset = 0
        while offset < len(data) - 4:
            idx = data.find(LNK_MAGIC, offset)
            if idx == -1: break
            try:
                entry = self._parse_lnk_data(data[idx:])
                if entry: lnk_entries.append(entry)
            except: pass
            offset = idx + 4

        result.append(f"**Entry Count:** {len(lnk_entries)}")
        result.append("")
        if lnk_entries:
            result.append("## Recent Documents")
            result.append("| # | Target Path | Last Modified |")
            result.append("| --- | --- | --- |")
            for i, entry in enumerate(lnk_entries[:50], 1):
                result.append(f"| {i} | {entry.get('target_path', 'N/A')} | {_format_datetime(entry.get('modification_time'))} |")
        else:
            result.append("*No LNK entries found.*")
        return "\n".join(result)

    def _parse_lnk_data(self, data: bytes) -> dict:
        if len(data) < 76: return None
        try:
            flags = struct.unpack_from('<I', data, 20)[0]
            modification_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 44)[0])
            target_path = ""
            if flags & LNK_FLAG_HAS_LINK_INFO:
                link_info_offset = struct.unpack_from('<I', data, 24)[0]
                if link_info_offset < len(data):
                    target_path, _, _ = LnkExtractor()._parse_link_info(data, link_info_offset)
            return {'target_path': target_path, 'modification_time': modification_time}
        except: return None
