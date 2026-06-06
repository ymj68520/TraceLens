"""Linux system log forensic extractors: auth.log, wtmp, systemd journal."""
import logging
import os
import re
import struct
from collections import Counter
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

SYSLOG_TS_RE = re.compile(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})')
SYSLOG_HOST_PROC_RE = re.compile(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+(\S+)\s+(\S+?)(?:\[(\d+)\])?\s*:\s*(.*)')
SSH_SUCCESS_RE = re.compile(r'Accepted\s+(publickey|password|keyboard-interactive)\s+for\s+(\S+)\s+from\s+(\S+)')
SSH_FAILURE_RE = re.compile(r'Failed\s+(publickey|password|keyboard-interactive)\s+for\s+(\S+)\s+from\s+(\S+)')
SUDO_RE = re.compile(r'sudo:\s+(\S+)\s*:\s*(.*?);\s*TTY=(\S+)\s*;\s*PWD=(\S+)\s*;\s*USER=(\S+)\s*;\s*COMMAND=(.*)')


@register_extractor
class AuthLogExtractor(BaseExtractor):
    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            return f"Error: Failed to read auth.log: {e}"

        if not lines:
            return f"# Authentication Log Summary: `{os.path.basename(file_path)}`\n\n*(Empty log file)*"

        entries = []
        stats = Counter()
        for line in lines:
            line = line.strip()
            if not line: continue
            entry = self._parse_line(line)
            if entry:
                entries.append(entry)
                stats[entry['event_type']] += 1

        if not entries:
            return f"# Authentication Log Summary: `{os.path.basename(file_path)}`\n\n*(No parseable entries found)*"

        result = [f"# Authentication Log Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**Total Entries:** {len(entries):,}")
        if entries:
            result.append(f"**Time Range:** {entries[0].get('timestamp', 'N/A')} ~ {entries[-1].get('timestamp', 'N/A')}")
        result.append("")

        result.append("## Authentication Statistics")
        result.append("| Event Type | Count |")
        result.append("| --- | --- |")
        for et, count in stats.most_common():
            result.append(f"| {et} | {count:,} |")
        result.append("")

        login_entries = [e for e in entries if 'Login' in e.get('event_type', '') or 'Sudo' in e.get('event_type', '')]
        if login_entries:
            result.append(f"## Login Attempts (Last {min(self.max_entries, len(login_entries))})")
            result.append("| Time | User | Source IP | Status | Service |")
            result.append("| --- | --- | --- | --- | --- |")
            for e in login_entries[:self.max_entries]:
                result.append(f"| {e.get('timestamp', '')} | {e.get('user', '')} | {e.get('source_ip', '')} | {e.get('status', '')} | {e.get('service', '')} |")
        return "\n".join(result)

    def _parse_line(self, line: str) -> dict:
        match = SYSLOG_HOST_PROC_RE.match(line)
        if not match: return None
        hostname, process, pid, message = match.groups()
        ts_match = SYSLOG_TS_RE.match(line)
        timestamp = ts_match.group(1) if ts_match else ''
        entry = {'timestamp': timestamp, 'hostname': hostname, 'process': process, 'pid': pid, 'message': message, 'event_type': 'Other', 'user': '', 'source_ip': '', 'status': '', 'service': process}

        if 'sshd' in process:
            ssh_s = SSH_SUCCESS_RE.search(message)
            ssh_f = SSH_FAILURE_RE.search(message)
            if ssh_s:
                entry.update(event_type='SSH Login Success', user=ssh_s.group(2), source_ip=ssh_s.group(3), status='SUCCESS')
            elif ssh_f:
                entry.update(event_type='SSH Login Failure', user=ssh_f.group(2), source_ip=ssh_f.group(3), status='FAILURE')
        elif 'sudo' in process:
            sudo_m = SUDO_RE.search(line)
            if sudo_m:
                entry.update(event_type='Sudo Usage', user=sudo_m.group(1), status='COMMAND', message=sudo_m.group(6)[:100])
        elif 'pam_unix' in message:
            if 'session opened' in message: entry['event_type'] = 'Session Opened'
            elif 'session closed' in message: entry['event_type'] = 'Session Closed'
            elif 'authentication failure' in message: entry['event_type'] = 'Auth Failure'
        return entry


@register_extractor
class WtmpExtractor(BaseExtractor):
    UTMP_SIZE = 384
    UT_TYPES = {0: 'EMPTY', 1: 'RUN_LVL', 2: 'BOOT_TIME', 3: 'NEW_TIME', 4: 'OLD_TIME', 5: 'INIT_PROCESS', 6: 'LOGIN_PROCESS', 7: 'USER_PROCESS', 8: 'DEAD_PROCESS', 9: 'ACCOUNTING'}

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f: data = f.read()
        except Exception as e: return f"Error: Failed to read wtmp/utmp file: {e}"

        if len(data) < self.UTMP_SIZE:
            return f"# Login Records Summary: `{os.path.basename(file_path)}`\n\n*(File too small)*"

        records = []
        type_counter = Counter()
        offset = 0
        while offset + self.UTMP_SIZE <= len(data):
            record = self._parse_record(data[offset:offset + self.UTMP_SIZE])
            if record:
                records.append(record)
                type_counter[record['type_name']] += 1
            offset += self.UTMP_SIZE

        if not records:
            return f"# Login Records Summary: `{os.path.basename(file_path)}`\n\n*(No valid records found)*"

        result = [f"# Login Records Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**Total Records:** {len(records):,}")
        timestamps = [r['timestamp'] for r in records if r['timestamp']]
        if timestamps:
            result.append(f"**Time Range:** {timestamps[-1]} ~ {timestamps[0]}")
        result.append("")

        result.append("## Login Statistics")
        result.append("| Type | Count |")
        result.append("| --- | --- |")
        for tn, count in type_counter.most_common():
            result.append(f"| {tn} | {count:,} |")
        result.append("")

        user_logins = [r for r in records if r['type_name'] == 'USER_PROCESS']
        if user_logins:
            result.append(f"## User Login History (Last {min(200, len(user_logins))})")
            result.append("| Time | User | Terminal | Host | PID |")
            result.append("| --- | --- | --- | --- | --- |")
            for r in user_logins[:200]:
                result.append(f"| {r['timestamp']} | {r['user']} | {r['terminal']} | {r['hostname']} | {r['pid']} |")

        boots = [r for r in records if r['type_name'] == 'BOOT_TIME']
        if boots:
            result.append("")
            result.append("## System Boots")
            result.append("| Time | Terminal |")
            result.append("| --- | --- |")
            for r in boots[:20]:
                result.append(f"| {r['timestamp']} | {r['terminal']} |")
        return "\n".join(result)

    def _parse_record(self, data: bytes) -> dict:
        try:
            ut_type = struct.unpack_from('<h', data, 0)[0]
            ut_pid = struct.unpack_from('<i', data, 4)[0]
            ut_user = data[8:40].split(b'\x00')[0].decode('utf-8', errors='replace')
            ut_line = data[40:44].split(b'\x00')[0].decode('utf-8', errors='replace')
            ut_host = data[44:76].split(b'\x00')[0].decode('utf-8', errors='replace')
            tv_sec = struct.unpack_from('<i', data, 280)[0]
            timestamp = ''
            if tv_sec > 0:
                try: timestamp = datetime.fromtimestamp(tv_sec).strftime('%Y-%m-%d %H:%M:%S')
                except: pass
            return {'type': ut_type, 'type_name': self.UT_TYPES.get(ut_type, f'UNKNOWN({ut_type})'), 'pid': ut_pid, 'user': ut_user, 'terminal': ut_line, 'hostname': ut_host, 'timestamp': timestamp}
        except: return None


@register_extractor
class JournalExtractor(BaseExtractor):
    JOURNAL_MAGIC = b'LPKSHHRH'

    def __init__(self, sample_size: int = 200):
        self.sample_size = sample_size

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f: header = f.read(256)
        except Exception as e: return f"Error: Failed to read journal file: {e}"

        if len(header) < 8: return "Error: File too small to be a valid journal file."
        if header[:8] != self.JOURNAL_MAGIC: return f"Error: Not a valid systemd journal file (magic: {header[:8]})"

        try:
            from systemd import journal
            return self._extract_with_systemd(file_path)
        except ImportError:
            return self._parse_header(file_path, header)

    def _extract_with_systemd(self, file_path: str) -> str:
        from systemd import journal
        j = journal.Reader()
        j.add_file(file_path)
        entries = []
        for entry in j:
            entries.append({'timestamp': entry.get('__REALTIME_TIMESTAMP', ''), 'priority': entry.get('PRIORITY', 6), 'unit': entry.get('_SYSTEMD_UNIT', entry.get('SYSLOG_IDENTIFIER', '')), 'message': entry.get('MESSAGE', '')})
            if len(entries) >= self.sample_size: break

        result = [f"# Systemd Journal Summary: `{os.path.basename(file_path)}`"]
        if not entries:
            result.append("\n*(No entries found)*")
            return "\n".join(result)

        priority_counter = Counter(e['priority'] for e in entries)
        priority_names = {0: 'Emergency', 1: 'Alert', 2: 'Critical', 3: 'Error', 4: 'Warning', 5: 'Notice', 6: 'Info', 7: 'Debug'}
        result.append(f"**Total Entries:** {len(entries):,}")
        result.append("")
        result.append("## Entry Distribution by Priority")
        result.append("| Priority | Count | Description |")
        result.append("| --- | --- | --- |")
        for p, count in priority_counter.most_common():
            result.append(f"| {p} ({priority_names.get(p, 'Unknown')}) | {count:,} | {priority_names.get(p, 'Unknown')} |")
        result.append("")
        result.append(f"## Recent Entries (Last {self.sample_size})")
        result.append("| Time | Priority | Unit | Message |")
        result.append("| --- | --- | --- | --- |")
        for e in entries[:self.sample_size]:
            ts = e['timestamp']
            if hasattr(ts, 'strftime'): ts = ts.strftime('%Y-%m-%d %H:%M:%S')
            msg = str(e['message']).replace('|', '\\|').replace('\n', ' ')
            if len(msg) > 100: msg = msg[:97] + "..."
            result.append(f"| {ts} | {e['priority']} | {e['unit'].replace('|', '\\|')} | {msg} |")
        return "\n".join(result)

    def _parse_header(self, file_path: str, header: bytes) -> str:
        import uuid
        result = [f"# Systemd Journal Summary: `{os.path.basename(file_path)}`"]
        file_id = uuid.UUID(bytes=header[8:24])
        machine_id = uuid.UUID(bytes=header[24:40])
        boot_id = uuid.UUID(bytes=header[40:56])
        file_size = os.path.getsize(file_path)
        result.append(f"**File ID:** {file_id}")
        result.append(f"**Machine ID:** {machine_id}")
        result.append(f"**Boot ID:** {boot_id}")
        result.append(f"**File Size:** {file_size / 1024 / 1024:.2f} MB")
        result.append("")
        result.append("## Extraction Status")
        result.append("*Full content extraction requires `python-systemd` library. Only header metadata is shown.*")
        result.append("")
        result.append("## Header Metadata")
        result.append("| Field | Value |")
        result.append("| --- | --- |")
        result.append(f"| File ID | {file_id} |")
        result.append(f"| Machine ID | {machine_id} |")
        result.append(f"| Boot ID | {boot_id} |")
        result.append(f"| File Size | {file_size:,} bytes |")
        result.append(f"| Magic | {header[:8]} |")
        return "\n".join(result)
