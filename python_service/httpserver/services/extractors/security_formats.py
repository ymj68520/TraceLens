"""Security format extractors: KeePass, GPG/PGP, Certificates."""
import logging
import os
import struct
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    else: return f"{size_bytes/1024/1024:.2f} MB"


@register_extractor
class KeePassExtractor(BaseExtractor):
    """Extracts metadata from KeePass database files (.kdbx)."""

    # KeePass2 magic: 0x9AA2D903
    KDBX_MAGIC = b'\x03\xd9\xa2\x9a'

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(124)
        except Exception as e:
            return f"Error: Failed to read KeePass file: {e}"

        if len(header) < 12:
            return "Error: File too small to be a valid KeePass database."

        magic = header[:4]
        if magic != self.KDBX_MAGIC:
            return f"Error: Not a valid KeePass database (magic: {magic.hex()})"

        try:
            sig2 = struct.unpack_from('<I', header, 4)[0]
            version = struct.unpack_from('<I', header, 8)[0]

            result = [f"# KeePass Database: `{os.path.basename(file_path)}`"]
            result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
            result.append(f"**Format:** KeePass 2.x (KDBX)")
            result.append(f"**Version:** {version >> 16}.{version & 0xFFFF}")
            result.append("")

            # Parse header fields
            result.append("## Database Properties")
            result.append("| Property | Value |")
            result.append("| --- | --- |")

            offset = 12
            while offset < len(header) - 3:
                field_id = header[offset]
                field_len = struct.unpack_from('<H', header, offset + 1)[0]

                if field_len > 0 and offset + 3 + field_len <= len(header):
                    field_data = header[offset + 3:offset + 3 + field_len]

                    field_names = {
                        0: 'End of Header',
                        1: 'Comment',
                        2: 'Cipher ID',
                        3: 'Compression',
                        4: 'Master Seed',
                        5: 'Transform Seed',
                        6: 'Transform Rounds',
                        7: 'Encryption IV',
                        8: 'Protected Stream Key',
                        9: 'Stream Start Bytes',
                        10: 'Inner Random Stream ID',
                    }

                    field_name = field_names.get(field_id, f'Field {field_id}')

                    if field_id == 3:  # Compression
                        comp = struct.unpack_from('<I', field_data, 0)[0]
                        comp_names = {0: 'None', 1: 'GZip'}
                        result.append(f"| {field_name} | {comp_names.get(comp, f'Unknown ({comp})')} |")
                    elif field_id == 6:  # Transform Rounds
                        rounds = struct.unpack_from('<Q', field_data, 0)[0]
                        result.append(f"| {field_name} | {rounds:,} |")
                    elif field_id == 2:  # Cipher ID
                        cipher = field_data.hex()
                        result.append(f"| {field_name} | {cipher} |")
                    elif field_id == 0:  # End of header
                        break
                    else:
                        result.append(f"| {field_name} | ({field_len} bytes) |")

                offset += 3 + field_len

            result.append("")
            result.append("*KeePass databases are encrypted. Full content extraction requires the master password.*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse KeePass database: {e}"


@register_extractor
class GpgKeyExtractor(BaseExtractor):
    """Extracts metadata from GPG/PGP key files (.gpg, .asc, .pgp)."""

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == '.asc':
            return self._parse_armor(file_path)
        else:
            return self._parse_binary(file_path)

    def _parse_armor(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        result = [f"# GPG/PGP Key: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** ASCII Armor")
        result.append("")

        import re

        # Count keys
        pub_keys = len(re.findall(r'-----BEGIN PGP PUBLIC KEY BLOCK-----', content))
        priv_keys = len(re.findall(r'-----BEGIN PGP PRIVATE KEY BLOCK-----', content))
        sigs = len(re.findall(r'-----BEGIN PGP SIGNATURE-----', content))
        messages = len(re.findall(r'-----BEGIN PGP MESSAGE-----', content))

        result.append("## Content Summary")
        result.append("| Type | Count |")
        result.append("| --- | --- |")
        if pub_keys: result.append(f"| Public Keys | {pub_keys} |")
        if priv_keys: result.append(f"| Private Keys | {priv_keys} |")
        if sigs: result.append(f"| Signatures | {sigs} |")
        if messages: result.append(f"| Encrypted Messages | {messages} |")

        # Extract key IDs from armor headers
        key_ids = re.findall(r'KeyID: ([A-F0-9]+)', content, re.IGNORECASE)
        if key_ids:
            result.append("")
            result.append("## Key IDs")
            for kid in set(key_ids):
                result.append(f"- `{kid}`")

        # Extract user IDs
        uids = re.findall(r'uid: (.+)', content)
        if uids:
            result.append("")
            result.append("## User IDs")
            for uid in set(uids):
                result.append(f"- {uid}")

        if pub_keys == 0 and priv_keys == 0 and sigs == 0 and messages == 0:
            result.append("*No PGP blocks found in file.*")

        return "\n".join(result)

    def _parse_binary(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read(min(4096, os.path.getsize(file_path)))
        except Exception as e:
            return f"Error: Failed to read file: {e}"

        result = [f"# GPG/PGP Key: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append(f"**Format:** Binary")

        # Check PGP packet header
        if len(data) >= 2 and (data[0] & 0x80):
            tag = (data[0] & 0x7C) >> 2
            tag_names = {
                1: 'Public-Key Encrypted Session Key',
                2: 'Signature',
                3: 'Symmetric-Key Encrypted Session Key',
                4: 'One-Pass Signature',
                5: 'Secret Key',
                6: 'Public Key',
                7: 'Secret Subkey',
                8: 'Compressed Data',
                9: 'Symmetrically Encrypted Data',
                10: 'Marker',
                11: 'Literal Data',
                12: 'Trust',
                13: 'User ID',
                14: 'Public Subkey',
                17: 'User Attribute',
            }

            result.append(f"**First Packet Type:** {tag_names.get(tag, f'Unknown ({tag})')}")

            # Try to extract key version
            if tag in (5, 6) and len(data) > 3:
                version = data[2] if (data[0] & 0x40) == 0 else data[1]
                result.append(f"**Key Version:** {version}")

                if version == 4 and len(data) > 10:
                    algo = data[8] if (data[0] & 0x40) == 0 else data[7]
                    algo_names = {1: 'RSA', 17: 'DSA', 18: 'ECDH', 19: 'ECDSA', 22: 'EdDSA'}
                    result.append(f"**Algorithm:** {algo_names.get(algo, f'Unknown ({algo})')}")

        result.append("")
        result.append("*Binary PGP keys. Use `gpg --import` to import, or `gpg --list-packets` to inspect.*")

        return "\n".join(result)


@register_extractor
class CertificateExtractor(BaseExtractor):
    """Extracts metadata from X.509 certificate files (.pem, .crt, .cer, .der)."""

    CERT_EXTENSIONS = {'.pem', '.crt', '.cer', '.der', '.p12', '.pfx', '.p7b', '.p7c'}

    async def extract_to_markdown(self, file_path: str) -> str:
        ext = os.path.splitext(file_path)[1].lower()

        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read certificate file: {e}"

        result = [f"# Certificate File: `{os.path.basename(file_path)}`"]
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")

        # Check if PEM format
        if b'-----BEGIN' in data:
            result.append("**Format:** PEM (Base64 encoded)")
            result.append("")

            import re
            cert_types = re.findall(rb'-----BEGIN ([A-Z ]+)-----', data)

            result.append("## Certificate Contents")
            result.append("| Type | Count |")
            result.append("| --- | --- |")

            type_counts = {}
            for ct in cert_types:
                ct_str = ct.decode('ascii')
                type_counts[ct_str] = type_counts.get(ct_str, 0) + 1

            for ct, count in type_counts.items():
                result.append(f"| {ct} | {count} |")

            # Try to parse with subprocess openssl
            result.append("")
            result.append("## Certificate Details")
            try:
                import subprocess
                tmp_path = file_path + '.tmp.pem'
                with open(tmp_path, 'wb') as f:
                    f.write(data)

                proc = subprocess.run(
                    ['openssl', 'x509', '-in', tmp_path, '-text', '-noout'],
                    capture_output=True, text=True, timeout=10
                )

                if proc.returncode == 0:
                    output = proc.stdout
                    # Extract key fields
                    for line in output.split('\n'):
                        line = line.strip()
                        if 'Issuer:' in line:
                            result.append(f"**Issuer:** {line.split('Issuer:')[1].strip()}")
                        elif 'Subject:' in line:
                            result.append(f"**Subject:** {line.split('Subject:')[1].strip()}")
                        elif 'Not Before:' in line:
                            result.append(f"**Valid From:** {line.split('Not Before:')[1].strip()}")
                        elif 'Not After :' in line:
                            result.append(f"**Valid Until:** {line.split('Not After :')[1].strip()}")

                os.unlink(tmp_path)
            except FileNotFoundError:
                result.append("*OpenSSL not available for detailed certificate parsing.*")
            except: pass

        elif data[:2] == b'0\x82' or data[:2] == b'0\x80':
            result.append("**Format:** DER (Binary)")
            result.append("")
            result.append("*DER-encoded certificate. Convert to PEM for detailed analysis: `openssl x509 -inform DER -in file.der -out file.pem`*")

        elif data[:4] == b'\x30\x82':
            result.append("**Format:** PKCS#12 / DER Binary")
            result.append("")
            result.append("*Binary certificate detected. May be PKCS#12 (.p12/.pfx) or DER-encoded.*")

        else:
            result.append(f"**Format:** Unknown")

        return "\n".join(result)
