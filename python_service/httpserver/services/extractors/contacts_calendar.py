"""Calendar and contact extractors: ICS, VCF."""
import logging
import os
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


@register_extractor
class IcsExtractor(BaseExtractor):
    """Extracts events from ICS (iCalendar) files."""

    def __init__(self, max_events: int = 100):
        self.max_events = max_events

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            from icalendar import Calendar
        except ImportError:
            return "Error: python-icalendar library is not installed."

        try:
            with open(file_path, 'rb') as f:
                cal = Calendar.from_ical(f.read())

            result = [f"# Calendar: `{os.path.basename(file_path)}`"]

            cal_name = cal.get('X-WR-CALNAME', '')
            if cal_name:
                result.append(f"**Calendar:** {cal_name}")

            events = []
            for component in cal.walk():
                if component.name == "VEVENT":
                    summary = str(component.get('SUMMARY', ''))
                    dtstart = component.get('DTSTART')
                    dtend = component.get('DTEND')
                    location = str(component.get('LOCATION', ''))
                    description = str(component.get('DESCRIPTION', ''))[:200]

                    start_str = ''
                    if dtstart:
                        dt = dtstart.dt
                        if isinstance(dt, datetime):
                            start_str = dt.strftime('%Y-%m-%d %H:%M')
                        else:
                            start_str = str(dt)

                    events.append({
                        'summary': summary,
                        'start': start_str,
                        'location': location,
                        'description': description,
                    })

            result.append(f"**Total Events:** {len(events)}")
            result.append("")

            if events:
                result.append(f"## Events (First {min(self.max_events, len(events))})")
                result.append("| Date | Summary | Location |")
                result.append("| --- | --- | --- |")
                for event in events[:self.max_events]:
                    loc = event['location'].replace('|', '\\|')[:50]
                    summary = event['summary'].replace('|', '\\|')[:80]
                    result.append(f"| {event['start']} | {summary} | {loc} |")

                if len(events) > self.max_events:
                    result.append(f"\n*(Showing {self.max_events} of {len(events)} events)*")
            else:
                result.append("*No events found.*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse ICS file: {e}"


@register_extractor
class VcfExtractor(BaseExtractor):
    """Extracts contacts from VCF (vCard) files."""

    def __init__(self, max_contacts: int = 100):
        self.max_contacts = max_contacts

    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import vobject
        except ImportError:
            return "Error: vobject library is not installed."

        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                vcards = list(vobject.readComponents(f))

            result = [f"# Contacts: `{os.path.basename(file_path)}`"]
            result.append(f"**Total Contacts:** {len(vcards)}")
            result.append("")

            if vcards:
                result.append(f"## Contact List (First {min(self.max_contacts, len(vcards))})")
                result.append("| Name | Phone | Email | Organization |")
                result.append("| --- | --- | --- | --- |")

                for vcard in vcards[:self.max_contacts]:
                    name = ''
                    if hasattr(vcard, 'fn'):
                        name = vcard.fn.value
                    elif hasattr(vcard, 'n'):
                        n = vcard.n.value
                        name = f"{n.given} {n.family}".strip()

                    phone = ''
                    if hasattr(vcard, 'tel'):
                        phone = vcard.tel.value

                    email = ''
                    if hasattr(vcard, 'email'):
                        email = vcard.email.value

                    org = ''
                    if hasattr(vcard, 'org'):
                        org = ' '.join(vcard.org.value)

                    name = name.replace('|', '\\|')[:50]
                    phone = phone.replace('|', '\\|')[:20]
                    email = email.replace('|', '\\|')[:40]
                    org = org.replace('|', '\\|')[:40]

                    result.append(f"| {name} | {phone} | {email} | {org} |")

                if len(vcards) > self.max_contacts:
                    result.append(f"\n*(Showing {self.max_contacts} of {len(vcards)} contacts)*")
            else:
                result.append("*No contacts found.*")

            return "\n".join(result)
        except Exception as e:
            return f"Error: Failed to parse VCF file: {e}"
