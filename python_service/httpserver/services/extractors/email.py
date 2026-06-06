"""Forensic email format extractors: EML, MSG, MBOX, PST/OST."""
import logging
import os
from datetime import datetime
from typing import List, Tuple

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _decode_header_value(value: str) -> str:
    """Decode RFC 2047 encoded header values."""
    if value is None:
        return ""
    from email.header import decode_header
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or 'utf-8', errors='replace'))
        else:
            decoded.append(part)
    return ''.join(decoded)


def _extract_email_fields(msg) -> dict:
    """Extract common fields from an email.message.Message object."""
    return {
        'from': _decode_header_value(msg.get('From', '')),
        'to': _decode_header_value(msg.get('To', '')),
        'cc': _decode_header_value(msg.get('Cc', '')),
        'bcc': _decode_header_value(msg.get('Bcc', '')),
        'date': msg.get('Date', ''),
        'subject': _decode_header_value(msg.get('Subject', '')),
        'message_id': msg.get('Message-ID', ''),
        'x_mailer': msg.get('X-Mailer', ''),
        'reply_to': msg.get('Reply-To', ''),
        'in_reply_to': msg.get('In-Reply-To', ''),
    }


def _extract_body_and_attachments(msg) -> Tuple[str, List[dict]]:
    """Extract plain text body and attachment list from an email message."""
    body_parts = []
    attachments = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get('Content-Disposition', ''))

            if 'attachment' in disposition:
                filename = part.get_filename() or 'unnamed'
                payload = part.get_payload(decode=True)
                size = len(payload) if payload else 0
                attachments.append({
                    'filename': filename,
                    'content_type': content_type,
                    'size': size,
                })
            elif content_type == 'text/plain':
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    body_parts.append(payload.decode(charset, errors='replace'))
            elif content_type == 'text/html' and not body_parts:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    body_parts.append(payload.decode(charset, errors='replace'))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            body_parts.append(payload.decode(charset, errors='replace'))

    body = '\n'.join(body_parts).strip()
    return body, attachments


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


@register_extractor
class EmlExtractor(BaseExtractor):
    """Extracts content from RFC 822 EML email files."""

    async def extract_to_markdown(self, file_path: str) -> str:
        import email as email_lib
        from email import policy

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                msg = email_lib.message_from_file(f, policy=policy.default)
        except Exception as e:
            logger.error(f"Error reading EML file {file_path}: {e}")
            return f"Error: Failed to read EML file: {e}"

        fields = _extract_email_fields(msg)
        body, attachments = _extract_body_and_attachments(msg)

        result = [f"# Email Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**From:** {fields['from']}")
        result.append(f"**To:** {fields['to']}")
        if fields['cc']:
            result.append(f"**CC:** {fields['cc']}")
        result.append(f"**Date:** {fields['date']}")
        result.append(f"**Subject:** {fields['subject']}")
        result.append("")

        result.append("## Headers")
        result.append("| Header | Value |")
        result.append("| --- | --- |")
        for key in ['message_id', 'x_mailer', 'reply_to', 'in_reply_to']:
            if fields[key]:
                result.append(f"| {key.replace('_', '-').title()} | {fields[key]} |")
        result.append("")

        result.append("## Body")
        if body:
            if len(body) > 10000:
                body = body[:10000] + "\n\n... (truncated)"
            result.append(body)
        else:
            result.append("*(No text content found)*")
        result.append("")

        result.append(f"## Attachments ({len(attachments)})")
        if attachments:
            for i, att in enumerate(attachments, 1):
                size_str = _format_size(att['size'])
                result.append(f"{i}. `{att['filename']}` ({att['content_type']}, {size_str})")
        else:
            result.append("*No attachments*")

        return "\n".join(result)


@register_extractor
class MsgExtractor(BaseExtractor):
    """Extracts content from Outlook MSG files (OLE2 format)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import olefile
        except ImportError:
            return "Error: olefile library is not installed. Please install olefile to analyze MSG files."

        try:
            ole = olefile.OleFileIO(file_path)
        except Exception as e:
            logger.error(f"Error opening MSG file {file_path}: {e}")
            return f"Error: Failed to open MSG file: {e}"

        try:
            fields = self._extract_properties(ole)
            body = self._extract_body(ole)
            attachments = self._extract_attachments(ole)

            result = [f"# Email Summary: `{os.path.basename(file_path)}`"]
            result.append(f"**From:** {fields.get('sender_name', '')} <{fields.get('sender_email', '')}>")
            result.append(f"**To:** {fields.get('display_to', '')}")
            if fields.get('display_cc'):
                result.append(f"**CC:** {fields['display_cc']}")
            result.append(f"**Date:** {fields.get('delivery_time', '')}")
            result.append(f"**Subject:** {fields.get('subject', '')}")
            result.append("")

            result.append("## Body")
            if body:
                if len(body) > 10000:
                    body = body[:10000] + "\n\n... (truncated)"
                result.append(body)
            else:
                result.append("*(No text content found)*")
            result.append("")

            result.append(f"## Attachments ({len(attachments)})")
            if attachments:
                for i, att in enumerate(attachments, 1):
                    size_str = _format_size(att['size'])
                    result.append(f"{i}. `{att['filename']}` ({size_str})")
            else:
                result.append("*No attachments*")

            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing MSG file {file_path}: {e}")
            return f"Error: Failed to parse MSG file: {e}"
        finally:
            ole.close()

    def _extract_properties(self, ole) -> dict:
        fields = {}
        try:
            if ole.exists('\x01Properties'):
                fields['subject'] = self._find_string_property(ole, 'Subject')
                fields['sender_name'] = self._find_string_property(ole, 'SenderName')
                fields['sender_email'] = self._find_string_property(ole, 'SenderEmailAddress')
                fields['display_to'] = self._find_string_property(ole, 'DisplayTo')
                fields['display_cc'] = self._find_string_property(ole, 'DisplayCc')
                fields['delivery_time'] = self._find_string_property(ole, 'DeliveryTime')
        except Exception as e:
            logger.warning(f"Error extracting MSG properties: {e}")
        return fields

    def _find_string_property(self, ole, name: str) -> str:
        for stream_path in ole.listdir():
            path_str = '/'.join(stream_path)
            if name.lower() in path_str.lower():
                try:
                    data = ole.openstream(stream_path).read()
                    return data.decode('utf-16-le', errors='replace').rstrip('\x00')
                except:
                    pass
        return ""

    def _extract_body(self, ole) -> str:
        for stream_name in ['\x01Body', 'Body']:
            if ole.exists(stream_name):
                try:
                    data = ole.openstream(stream_name).read()
                    return data.decode('utf-16-le', errors='replace').rstrip('\x00')
                except:
                    pass
        for stream_name in ['\x01HTMLBody', 'HTMLBody']:
            if ole.exists(stream_name):
                try:
                    data = ole.openstream(stream_name).read()
                    return data.decode('utf-8', errors='replace')
                except:
                    pass
        return ""

    def _extract_attachments(self, ole) -> list:
        attachments = []
        for stream_path in ole.listdir():
            path_str = '/'.join(stream_path)
            if 'attach' in path_str.lower() and path_str.endswith('AttachFilename'):
                try:
                    data = ole.openstream(stream_path).read()
                    filename = data.decode('utf-16-le', errors='replace').rstrip('\x00')
                    attachments.append({'filename': filename, 'size': 0})
                except:
                    pass
        return attachments


@register_extractor
class MboxExtractor(BaseExtractor):
    """Extracts content from Unix MBOX mailbox files."""

    def __init__(self, sample_size: int = 100, body_preview_chars: int = 500):
        self.sample_size = sample_size
        self.body_preview_chars = body_preview_chars

    async def extract_to_markdown(self, file_path: str) -> str:
        import mailbox

        try:
            mbox = mailbox.mbox(file_path)
        except Exception as e:
            logger.error(f"Error opening MBOX file {file_path}: {e}")
            return f"Error: Failed to open MBOX file: {e}"

        try:
            messages = list(mbox)
            total_count = len(messages)

            if total_count == 0:
                return f"# Mbox Summary: `{os.path.basename(file_path)}`\n\n*(Empty mailbox)*"

            dates = []
            for msg in messages:
                date_str = msg.get('Date', '')
                if date_str:
                    dates.append(date_str)

            result = [f"# Mbox Summary: `{os.path.basename(file_path)}`"]
            result.append(f"**Total Messages:** {total_count:,}")
            if dates:
                result.append(f"**Date Range:** {dates[0]} ~ {dates[-1]}")
            result.append("")

            sample = messages[:self.sample_size]
            result.append(f"## Message Sample (First {len(sample)})")
            result.append("")

            for i, msg in enumerate(sample, 1):
                fields = _extract_email_fields(msg)
                body, attachments = _extract_body_and_attachments(msg)

                result.append(f"### Message {i}")
                result.append(f"**From:** {fields['from']}  **Date:** {fields['date']}  **Subject:** {fields['subject']}")

                if body:
                    preview = body[:self.body_preview_chars]
                    if len(body) > self.body_preview_chars:
                        preview += "..."
                    result.append(f"\n{preview}")

                if attachments:
                    att_names = [a['filename'] for a in attachments]
                    result.append(f"\n*Attachments: {', '.join(att_names)}*")

                result.append("")

            if total_count > self.sample_size:
                result.append(f"*(Showing {self.sample_size} of {total_count:,} messages)*")

            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing MBOX file {file_path}: {e}")
            return f"Error: Failed to parse MBOX file: {e}"
        finally:
            mbox.close()


@register_extractor
class PstExtractor(BaseExtractor):
    """Extracts metadata from PST/OST files (Outlook data files)."""

    PST_MAGIC = b'!BDN'

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
        except Exception as e:
            logger.error(f"Error reading PST file {file_path}: {e}")
            return f"Error: Failed to read PST/OST file: {e}"

        if len(header) < 4:
            return "Error: File too small to be a valid PST/OST file."

        magic = header[:4]
        if magic != self.PST_MAGIC:
            return f"Error: Not a valid PST/OST file (magic bytes: {magic.hex()})"

        return self._parse_header(file_path, header)

    def _parse_header(self, file_path: str, header: bytes) -> str:
        import struct

        result = [f"# PST/OST File Summary: `{os.path.basename(file_path)}`"]
        result.append("**Format:** PST (Personal Storage Table)")

        if file_path.lower().endswith('.ost'):
            result[1] = result[1].replace('PST', 'OST (Offline Storage Table)')

        if len(header) >= 14:
            version = struct.unpack_from('<I', header, 10)[0]
            version_str = {35: "ANSI (32-bit)", 23: "Unicode (32-bit)", 49: "Unicode (64-bit)"}.get(version, f"Unknown ({version})")
            result.append(f"**Version:** {version_str}")

        if len(header) >= 222:
            enc_type = header[221]
            enc_str = {0: "None", 1: "Compressible", 2: "Strong"}.get(enc_type, f"Unknown ({enc_type})")
            result.append(f"**Encryption:** {enc_str}")

        file_size = os.path.getsize(file_path)
        result.append(f"**File Size:** {file_size / 1024 / 1024:.2f} MB")

        result.append("")
        result.append("## Extraction Status")
        result.append("*Full content extraction requires `pffexport` (libpff tools). Only header metadata is shown.*")
        result.append("")
        result.append("## Basic Metadata")
        result.append("| Field | Value |")
        result.append("| --- | --- |")
        result.append(f"| File Path | `{file_path}` |")
        result.append(f"| File Size | {file_size:,} bytes |")
        result.append(f"| Magic | {header[:4].hex()} |")

        return "\n".join(result)
