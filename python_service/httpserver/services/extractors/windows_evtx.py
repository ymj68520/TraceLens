"""Windows Event Log (EVTX) forensic extractor."""
import logging
import os
from collections import Counter
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

EVENT_ID_DESCRIPTIONS = {
    4624: "Logon Success", 4625: "Logon Failure", 4634: "Logoff",
    4647: "User Initiated Logoff", 4648: "Explicit Credential Logon",
    4672: "Special Privilege Logon", 4720: "User Account Created",
    4722: "User Account Enabled", 4725: "User Account Disabled",
    4726: "User Account Deleted", 4732: "Member Added to Local Group",
    4735: "Local Group Changed", 4756: "Member Added to Universal Group",
    4719: "System Audit Policy Changed", 4739: "Domain Policy Changed",
    4704: "User Right Assigned", 1074: "System Shutdown/Restart",
    6005: "Event Log Service Started", 6006: "Event Log Service Stopped",
    6008: "Unexpected Shutdown", 6009: "OS Version at Boot",
    6013: "System Uptime", 7034: "Service Crashed",
    7035: "Service Control Manager", 7036: "Service State Change",
    7040: "Service Start Type Changed", 4688: "New Process Created",
    4689: "Process Exited", 4656: "Handle to Object Requested",
    4658: "Handle to Object Closed", 4660: "Object Deleted",
    4663: "Object Access Attempt", 4698: "Scheduled Task Created",
    4699: "Scheduled Task Deleted", 4700: "Scheduled Task Enabled",
    4701: "Scheduled Task Disabled", 4702: "Scheduled Task Updated",
    4103: "PowerShell Module Logging", 4104: "PowerShell Script Block Logging",
    4105: "Script Block Execution Start", 4106: "Script Block Execution End",
    1116: "Malware Detected", 1117: "Malware Action Taken",
    1118: "Malware Action Failed", 1149: "RDP Connection Attempt",
    21: "RDP Session Logon", 22: "RDP Shell Start",
    23: "RDP Session Logoff", 24: "RDP Session Disconnect",
    25: "RDP Session Reconnect",
}

LEVEL_NAMES = {0: "Info", 1: "Warning", 2: "Error", 3: "Critical", 4: "Verbose"}


@register_extractor
class EvtxExtractor(BaseExtractor):
    """Extracts content from Windows Event Log (.evtx) files."""

    def __init__(self, sample_size: int = 100):
        self.sample_size = sample_size

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from Evtx.Evtx import FileHeader
            from Evtx.Views import evtx_file_xml_view
        except ImportError:
            return "Error: python-evtx library is not installed. Please install python-evtx to analyze EVTX files."

        try:
            return self._extract_with_python_evtx(file_path)
        except Exception as e:
            logger.error(f"Error parsing EVTX file {file_path}: {e}")
            return f"Error: Failed to parse EVTX file: {e}"

    def _extract_with_python_evtx(self, file_path: str) -> str:
        from Evtx.Evtx import FileHeader
        from Evtx.Views import evtx_file_xml_view
        from defusedxml import ElementTree as ET

        with open(file_path, 'rb') as f:
            fh = FileHeader(f.read())

        events = []
        event_id_counter = Counter()
        level_counter = Counter()

        for xml_string, record in evtx_file_xml_view(fh):
            try:
                root = ET.fromstring(xml_string)
                ns = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}

                system = root.find('.//e:System', ns)
                if system is None:
                    continue

                event_id_elem = system.find('e:EventID', ns)
                level_elem = system.find('e:Level', ns)
                time_elem = system.find('e:TimeCreated', ns)
                provider_elem = system.find('e:Provider', ns)
                computer_elem = system.find('e:Computer', ns)

                event_id = int(event_id_elem.text) if event_id_elem is not None else 0
                level = int(level_elem.text) if level_elem is not None else 0
                timestamp = time_elem.get('SystemTime', '') if time_elem is not None else ''
                provider = provider_elem.get('Name', '') if provider_elem is not None else ''
                computer = computer_elem.text if computer_elem is not None else ''

                event_data = root.find('.//e:EventData', ns)
                message = ''
                if event_data is not None:
                    data_parts = []
                    for data in event_data.findall('e:Data', ns):
                        if data.text:
                            data_parts.append(data.text)
                    message = ' | '.join(data_parts[:3])

                event_id_counter[event_id] += 1
                level_counter[LEVEL_NAMES.get(level, f"Unknown({level})")] += 1

                events.append({
                    'timestamp': timestamp, 'event_id': event_id,
                    'level': LEVEL_NAMES.get(level, f"Unknown({level})"),
                    'provider': provider, 'computer': computer,
                    'message': message[:200],
                })
            except Exception as e:
                logger.warning(f"Error parsing EVTX record: {e}")
                continue

        if not events:
            return f"# Windows Event Log Summary: `{os.path.basename(file_path)}`\n\n*(No events found or file is empty)*"

        result = [f"# Windows Event Log Summary: `{os.path.basename(file_path)}`"]
        computers = set(e['computer'] for e in events if e['computer'])
        result.append(f"**Computer:** {', '.join(computers) if computers else 'Unknown'}")
        result.append(f"**Total Records:** {len(events):,}")
        timestamps = [e['timestamp'] for e in events if e['timestamp']]
        if timestamps:
            result.append(f"**Time Range:** {timestamps[-1]} ~ {timestamps[0]}")
        result.append("")

        result.append("## Event Distribution (Top 20)")
        result.append("| Event ID | Count | Level | Description |")
        result.append("| --- | --- | --- | --- |")
        for event_id, count in event_id_counter.most_common(20):
            desc = EVENT_ID_DESCRIPTIONS.get(event_id, "")
            level = next((e['level'] for e in events if e['event_id'] == event_id), "Info")
            result.append(f"| {event_id} | {count:,} | {level} | {desc} |")
        result.append("")

        result.append("## Level Distribution")
        result.append("| Level | Count |")
        result.append("| --- | --- |")
        for level, count in level_counter.most_common():
            result.append(f"| {level} | {count:,} |")
        result.append("")

        result.append(f"## Recent Events (Last {self.sample_size})")
        result.append("| Time | ID | Level | Provider | Message |")
        result.append("| --- | --- | --- | --- | --- |")
        for event in events[:self.sample_size]:
            ts = event['timestamp'][:19] if event['timestamp'] else ''
            msg = event['message'].replace('|', '\\|').replace('\n', ' ')
            if len(msg) > 100:
                msg = msg[:97] + "..."
            result.append(f"| {ts} | {event['event_id']} | {event['level']} | {event['provider']} | {msg} |")

        if len(events) > self.sample_size:
            result.append(f"\n*(Showing {self.sample_size} of {len(events):,} events)*")

        return "\n".join(result)
