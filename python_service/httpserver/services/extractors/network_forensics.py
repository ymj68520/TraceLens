"""Network forensics extractors: PCAP/PCAPNG."""
import logging
import os
import struct
from collections import Counter, defaultdict
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024: return f"{size_bytes} B"
    elif size_bytes < 1024*1024: return f"{size_bytes/1024:.1f} KB"
    elif size_bytes < 1024*1024*1024: return f"{size_bytes/1024/1024:.2f} MB"
    else: return f"{size_bytes/1024/1024/1024:.2f} GB"


@register_extractor
class PcapExtractor(BaseExtractor):
    """Extracts metadata and connections from PCAP/PCAPNG network captures."""

    # PCAP magic: 0xA1B2C3D4 or 0xD4C3B2A1 (swapped)
    PCAP_MAGIC = b'\xd4\xc3\xb2\xa1'
    PCAP_MAGIC_SWAPPED = b'\xa1\xb2\xc3\xd4'
    PCAPNG_MAGIC = b'\x0a\x0d\x0d\x0a'

    def __init__(self, max_packets: int = 1000):
        self.max_packets = max_packets

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(24)
        except Exception as e:
            return f"Error: Failed to read PCAP file: {e}"

        if len(header) < 4:
            return "Error: File too small."

        magic = header[:4]

        if magic == self.PCAP_MAGIC or magic == self.PCAP_MAGIC_SWAPPED:
            return self._parse_pcap(file_path, header, swapped=(magic == self.PCAP_MAGIC_SWAPPED))
        elif magic == self.PCAPNG_MAGIC:
            return self._parse_pcapng(file_path, header)
        else:
            return f"Error: Not a valid PCAP/PCAPNG file (magic: {magic.hex()})"

    def _parse_pcap(self, file_path: str, header: bytes, swapped: bool) -> str:
        endian = '>' if swapped else '<'

        # Parse global header
        version_major = struct.unpack_from(endian + 'H', header, 4)[0]
        version_minor = struct.unpack_from(endian + 'H', header, 6)[0]
        snaplen = struct.unpack_from(endian + 'I', header, 16)[0]
        link_type = struct.unpack_from(endian + 'I', header, 20)[0]

        link_types = {0: 'NULL', 1: 'ETHERNET', 6: 'TOKEN_RING', 108: 'LOOP', 113: 'LINUX_SLL', 228: 'RAW_IP', 229: 'RAW_IP6'}

        result = [f"# PCAP Analysis: `{os.path.basename(file_path)}`"]
        result.append(f"**Format:** PCAP {version_major}.{version_minor}")
        result.append(f"**Link Type:** {link_types.get(link_type, f'Unknown ({link_type})')}")
        result.append(f"**Snap Length:** {snaplen:,}")
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")

        # Parse packets
        protocols = Counter()
        src_ips = Counter()
        dst_ips = Counter()
        connections = set()
        dns_queries = []
        packet_count = 0
        total_bytes = 0

        try:
            with open(file_path, 'rb') as f:
                f.seek(24)  # Skip global header

                while packet_count < self.max_packets:
                    # Read packet header
                    pkt_header = f.read(16)
                    if len(pkt_header) < 16:
                        break

                    ts_sec = struct.unpack_from(endian + 'I', pkt_header, 0)[0]
                    ts_usec = struct.unpack_from(endian + 'I', pkt_header, 4)[0]
                    incl_len = struct.unpack_from(endian + 'I', pkt_header, 8)[0]

                    # Read packet data
                    pkt_data = f.read(incl_len)
                    if len(pkt_data) < incl_len:
                        break

                    total_bytes += incl_len
                    packet_count += 1

                    # Parse Ethernet frame
                    if link_type == 1 and len(pkt_data) >= 14:
                        eth_type = struct.unpack_from('!H', pkt_data, 12)[0]

                        if eth_type == 0x0800 and len(pkt_data) >= 34:  # IPv4
                            protocols['IPv4'] += 1
                            ip_header = pkt_data[14:34]
                            src_ip = '.'.join(str(b) for b in ip_header[12:16])
                            dst_ip = '.'.join(str(b) for b in ip_header[16:20])
                            protocol = ip_header[9]

                            src_ips[src_ip] += 1
                            dst_ips[dst_ip] += 1

                            if protocol == 6:  # TCP
                                protocols['TCP'] += 1
                                tcp_offset = 14 + (ip_header[0] & 0x0F) * 4
                                if len(pkt_data) > tcp_offset + 4:
                                    src_port = struct.unpack_from('!H', pkt_data, tcp_offset)[0]
                                    dst_port = struct.unpack_from('!H', pkt_data, tcp_offset + 2)[0]
                                    connections.add((src_ip, src_port, dst_ip, dst_port))

                                    # HTTP detection
                                    if dst_port == 80 or src_port == 80:
                                        protocols['HTTP'] += 1
                                    elif dst_port == 443 or src_port == 443:
                                        protocols['HTTPS/TLS'] += 1
                            elif protocol == 17:  # UDP
                                protocols['UDP'] += 1
                                udp_offset = 14 + (ip_header[0] & 0x0F) * 4
                                if len(pkt_data) > udp_offset + 8:
                                    src_port = struct.unpack_from('!H', pkt_data, udp_offset)[0]
                                    dst_port = struct.unpack_from('!H', pkt_data, udp_offset + 2)[0]

                                    if dst_port == 53 or src_port == 53:  # DNS
                                        protocols['DNS'] += 1
                                        # Parse DNS query
                                        dns_offset = udp_offset + 8
                                        if len(pkt_data) > dns_offset + 12:
                                            try:
                                                qdcount = struct.unpack_from('!H', pkt_data, dns_offset + 4)[0]
                                                if qdcount > 0:
                                                    name_parts = []
                                                    pos = dns_offset + 12
                                                    while pos < len(pkt_data) and pkt_data[pos] != 0:
                                                        length = pkt_data[pos]
                                                        if length > 63:
                                                            break
                                                        pos += 1
                                                        name_parts.append(pkt_data[pos:pos+length].decode('ascii', errors='replace'))
                                                        pos += length
                                                    if name_parts:
                                                        dns_queries.append('.'.join(name_parts))
                                            except: pass
                            elif protocol == 1:
                                protocols['ICMP'] += 1
                        elif eth_type == 0x0806:  # ARP
                            protocols['ARP'] += 1
                        elif eth_type == 0x86DD:  # IPv6
                            protocols['IPv6'] += 1
        except Exception as e:
            logger.warning(f"Error parsing PCAP packets: {e}")

        # Build results
        result.append(f"**Packets Analyzed:** {packet_count:,}")
        result.append(f"**Total Data:** {_format_size(total_bytes)}")
        result.append("")

        if protocols:
            result.append("## Protocol Distribution")
            result.append("| Protocol | Count |")
            result.append("| --- | --- |")
            for proto, count in protocols.most_common():
                result.append(f"| {proto} | {count:,} |")
            result.append("")

        if src_ips:
            result.append("## Top Source IPs")
            result.append("| IP Address | Packets |")
            result.append("| --- | --- |")
            for ip, count in src_ips.most_common(20):
                result.append(f"| {ip} | {count:,} |")
            result.append("")

        if dst_ips:
            result.append("## Top Destination IPs")
            result.append("| IP Address | Packets |")
            result.append("| --- | --- |")
            for ip, count in dst_ips.most_common(20):
                result.append(f"| {ip} | {count:,} |")
            result.append("")

        if dns_queries:
            result.append("## DNS Queries")
            result.append("| Domain |")
            result.append("| --- |")
            seen = set()
            for q in dns_queries[:100]:
                if q not in seen:
                    seen.add(q)
                    result.append(f"| {q} |")
            if len(dns_queries) > 100:
                result.append(f"\n*(Showing first 100 of {len(dns_queries)} queries)*")
            result.append("")

        if connections:
            result.append(f"## Connections ({len(connections):,})")
            result.append("| Source | Source Port | Destination | Dest Port |")
            result.append("| --- | --- | --- | --- |")
            for src, sp, dst, dp in sorted(connections)[:100]:
                result.append(f"| {src} | {sp} | {dst} | {dp} |")
            if len(connections) > 100:
                result.append(f"\n*(Showing first 100 of {len(connections):,} connections)*")

        return "\n".join(result)

    def _parse_pcapng(self, file_path: str, header: bytes) -> str:
        result = [f"# PCAPNG Analysis: `{os.path.basename(file_path)}`"]
        result.append(f"**Format:** PCAPNG")
        result.append(f"**File Size:** {_format_size(os.path.getsize(file_path))}")
        result.append("")

        # PCAPNG is more complex - parse block by block
        try:
            with open(file_path, 'rb') as f:
                block_count = 0
                pkt_count = 0

                while block_count < 1000:
                    block_header = f.read(8)
                    if len(block_header) < 8:
                        break

                    block_type = struct.unpack_from('<I', block_header, 0)[0]
                    block_len = struct.unpack_from('<I', block_header, 4)[0]

                    if block_len < 12 or block_len > 100*1024*1024:
                        break

                    block_data = f.read(block_len - 12)
                    if len(block_data) < block_len - 12:
                        break

                    # Read block trailer
                    f.read(4)

                    if block_type == 0x00000001:  # Section Header
                        result.append("**Section Header Block found**")
                    elif block_type == 0x00000006:  # Enhanced Packet Block
                        pkt_count += 1

                    block_count += 1

                result.append(f"**Blocks Parsed:** {block_count}")
                result.append(f"**Packet Blocks:** {pkt_count}")
                result.append("")
                result.append("*Full PCAPNG parsing requires specialized tools like tshark or scapy.*")
        except Exception as e:
            result.append(f"*Error parsing PCAPNG: {e}*")

        return "\n".join(result)
