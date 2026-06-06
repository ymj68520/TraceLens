"""Android backup file (.ab) forensic extractor."""
import logging
import os
import tarfile
import zlib
import base64
from io import BytesIO

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

ANDROID_ARTIFACTS = {
    'contacts2.db': 'Contacts Database', 'mmssms.db': 'SMS/MMS Database',
    'calllog.db': 'Call Log Database', 'accounts.db': 'Accounts Database',
    'settings.db': 'Settings Database', 'wifi': 'WiFi Configuration',
}


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class AndroidBackupExtractor(BaseExtractor):
    AB_MAGIC = b'ANDROID BACKUP\n'

    def __init__(self, max_files: int = 100):
        self.max_files = max_files

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f: header_data = f.read(1024)
        except Exception as e: return f"Error: Failed to read Android backup: {e}"

        if not header_data.startswith(self.AB_MAGIC):
            return "Error: Not a valid Android backup file"

        header_text = header_data.split(b'\n', 5)
        if len(header_text) < 5: return "Error: Incomplete Android backup header"

        try:
            version = header_text[1].decode('utf-8').strip().split(':')[1].strip()
            compression = header_text[2].decode('utf-8').strip().split(':')[1].strip()
            encryption = header_text[3].decode('utf-8').strip().split(':')[1].strip()
        except:
            version = compression = encryption = "Unknown"

        result = [f"# Android Backup Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**Version:** {version}")
        result.append(f"**Compression:** {compression}")
        result.append(f"**Encryption:** {encryption}")
        result.append("")

        if encryption.lower() != 'none':
            result.append("## Encrypted Backup")
            result.append("This backup is encrypted. Content cannot be extracted without the decryption key.")
            return "\n".join(result)

        try:
            with open(file_path, 'rb') as f: content = f.read()
            header_end = content.find(b'\n\n')
            if header_end == -1: return "Error: Could not find end of backup header"

            try:
                b64_data = content[header_end:].strip()
                compressed_data = base64.b64decode(b64_data)
                tar_data = zlib.decompress(compressed_data)
            except:
                tar_data = content[header_end:].strip()

            tar_file = BytesIO(tar_data)
            with tarfile.open(fileobj=tar_file, mode='r') as tar:
                members = tar.getmembers()
                result.append(f"**Total Files:** {len(members)}")
                result.append("")

                artifacts = []
                for m in members:
                    if m.isfile():
                        for pattern, desc in ANDROID_ARTIFACTS.items():
                            if pattern in m.name.lower():
                                artifacts.append((m.name, m.size, desc))

                if artifacts:
                    result.append("## Important Android Artifacts")
                    result.append("| Path | Size | Type |")
                    result.append("| --- | --- | --- |")
                    for path, size, desc in artifacts[:50]:
                        result.append(f"| {path} | {_format_size(size)} | {desc} |")
                    result.append("")

                result.append(f"## File Listing (First {self.max_files})")
                result.append("| Path | Size |")
                result.append("| --- | --- |")
                for m in members[:self.max_files]:
                    if m.isfile():
                        result.append(f"| {m.name} | {_format_size(m.size)} |")
                if len(members) > self.max_files:
                    result.append(f"\n*(Showing {self.max_files} of {len(members)} files)*")
            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse Android backup: {e}"
