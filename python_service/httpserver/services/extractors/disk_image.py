"""Forensic disk image metadata extractors: E01 (EnCase Evidence File)."""
import logging
import os
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

EVF_SIGNATURE = b'\x45\x56\x46\x09\x0d\x0a\xff\x00'


@register_extractor
class E01MetadataExtractor(BaseExtractor):
    async def extract_to_markdown(self, file_path: str) -> str:
        pyewf_result = self._try_pyewf(file_path)
        if pyewf_result: return pyewf_result
        return self._parse_header(file_path)

    def _try_pyewf(self, file_path: str) -> str:
        try:
            import pyewf
        except ImportError: return ""

        try:
            ewf_handle = pyewf.open(file_path)
            result = [f"# E01 Forensic Image Metadata: `{os.path.basename(file_path)}`"]
            header_values = ewf_handle.get_header_values()
            if header_values:
                result.append(f"**Case Number:** {header_values.get('case_number', 'N/A')}")
                result.append(f"**Evidence Number:** {header_values.get('evidence_number', 'N/A')}")
                result.append(f"**Examiner:** {header_values.get('examiner_name', 'N/A')}")
                result.append(f"**Description:** {header_values.get('description', 'N/A')}")
                result.append("")
                result.append("## Acquisition Details")
                result.append("| Field | Value |")
                result.append("| --- | --- |")
                result.append(f"| Date | {header_values.get('acquisition_date', 'N/A')} |")
                result.append(f"| Platform | {header_values.get('platform', 'N/A')} |")
                result.append(f"| Compression | {header_values.get('compression_type', 'N/A')} |")
                result.append("")

            result.append("## Image Statistics")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            media_size = ewf_handle.get_media_size()
            result.append(f"| Media Size | {media_size / 1024 / 1024 / 1024:.2f} GB |")
            result.append(f"| File Size | {os.path.getsize(file_path):,} bytes |")
            ewf_handle.close()
            return "\n".join(result)
        except Exception as e:
            logger.warning(f"pyewf failed for {file_path}: {e}")
            return ""

    def _parse_header(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f: header = f.read(512)
        except Exception as e: return f"Error: Failed to read E01 file: {e}"

        if len(header) < 8: return "Error: File too small to be a valid E01 file."
        if header[:8] != EVF_SIGNATURE: return f"Error: Not a valid E01 file (signature: {header[:8].hex()})"

        result = [f"# E01 Forensic Image Metadata: `{os.path.basename(file_path)}`"]
        result.append("**Format:** E01 (EnCase Evidence File)")
        result.append("")

        try:
            fields_offset = struct.unpack_from('<I', header, 13)[0]
            fields_size = struct.unpack_from('<I', header, 17)[0]
            with open(file_path, 'rb') as f:
                f.seek(fields_offset)
                fields_data = f.read(min(fields_size, 4096))
            fields = {}
            try:
                fields_text = fields_data.decode('utf-8', errors='replace')
                for line in fields_text.split('\n'):
                    if '=' in line:
                        k, _, v = line.partition('=')
                        fields[k.strip()] = v.strip()
            except: pass

            if fields:
                result.append("## Case Information")
                result.append("| Field | Value |")
                result.append("| --- | --- |")
                for key in ['case_number', 'evidence_number', 'examiner_name', 'description']:
                    value = fields.get(key, 'N/A')
                    if value: result.append(f"| {key.replace('_', ' ').title()} | {value} |")
                result.append("")
        except Exception as e:
            logger.warning(f"Error parsing E01 header fields: {e}")

        result.append("## File Information")
        result.append("| Field | Value |")
        result.append("| --- | --- |")
        result.append(f"| File Path | `{file_path}` |")
        result.append(f"| File Size | {os.path.getsize(file_path):,} bytes |")
        result.append(f"| Signature | {header[:8].hex()} |")
        result.append("")
        result.append("## Extraction Status")
        result.append("*Full metadata extraction requires `pyewf` library. Only basic header information is shown.*")
        return "\n".join(result)
