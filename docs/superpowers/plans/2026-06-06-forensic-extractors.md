# Forensic File Type Extractors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 15 Python extractor classes for forensically common file types (email, Windows artifacts, browser history, Linux logs, Android backup, E01 metadata) following the existing BaseExtractor plugin architecture.

**Architecture:** Each extractor is an independent Python class implementing `BaseExtractor.extract_to_markdown()`. Extractors are registered via `@register_extractor` decorator and routed by extension (via `extractor_mapping.json`) or by filename (via new `_filename_routes` mechanism). All output is Markdown consistent with existing extractors.

**Tech Stack:** Python 3.10+, standard library (email, mailbox, sqlite3, struct, zlib, tarfile), python-evtx, python-registry, olefile, optional pyewf

---

## File Structure

```
python_service/
├── httpserver/
│   ├── services/
│   │   ├── extractors/
│   │   │   ├── __init__.py              # MODIFY: add filename_routes support
│   │   │   ├── base.py                  # EXISTING: no changes
│   │   │   ├── email.py                 # CREATE: EmlExtractor, MsgExtractor, MboxExtractor, PstExtractor
│   │   │   ├── windows_evtx.py          # CREATE: EvtxExtractor
│   │   │   ├── windows_registry.py      # CREATE: RegistryExtractor
│   │   │   ├── windows_lnk.py           # CREATE: LnkExtractor, JumplistExtractor
│   │   │   ├── browser_history.py       # CREATE: ChromeHistoryExtractor, FirefoxHistoryExtractor
│   │   │   ├── linux_journal.py         # CREATE: JournalExtractor, AuthLogExtractor, WtmpExtractor
│   │   │   ├── android_backup.py        # CREATE: AndroidBackupExtractor
│   │   │   └── disk_image.py            # CREATE: E01MetadataExtractor
│   │   └── document_extractor.py        # MODIFY: add filename-based routing
│   └── config/
│       └── extractor_mapping.json       # MODIFY: add new extractors + _filename_routes
├── tests/
│   └── unit/
│       └── test_forensic_extractors.py  # CREATE: unit tests for all new extractors
└── httpserver/
    └── requirements.txt                 # MODIFY: add python-evtx, python-registry, olefile
```

---

## Task 1: Update Dependencies

**Files:**
- Modify: `python_service/httpserver/requirements.txt`

- [ ] **Step 1: Add forensic parsing libraries to requirements.txt**

Append the following to `python_service/httpserver/requirements.txt`:

```python
# Forensic Format Parsing
python-evtx>=0.8.0        # Windows Event Log (.evtx)
python-registry>=1.3.0    # Windows Registry hives
olefile>=0.47             # OLE2 format (.msg, jump lists)
defusedxml>=0.7.1         # Safe XML parsing (XXE protection)
```

- [ ] **Step 2: Install new dependencies**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject && pip install python-evtx python-registry olefile defusedxml`

Expected: Successfully installed packages

- [ ] **Step 3: Verify imports work**

Run: `python -c "import Evtx.Evtx; import Registry; import olefile; import defusedxml; print('All imports OK')"`

Expected: `All imports OK`

- [ ] **Step 4: Commit**

```bash
git add python_service/httpserver/requirements.txt
git commit -m "deps: add python-evtx, python-registry, olefile, defusedxml for forensic extractors"
```

---

## Task 2: Extend Routing Mechanism

**Files:**
- Modify: `python_service/httpserver/services/extractors/__init__.py`
- Modify: `python_service/httpserver/services/document_extractor.py`

- [ ] **Step 1: Read current __init__.py**

Read `python_service/httpserver/services/extractors/__init__.py` to understand current loader.

- [ ] **Step 2: Add filename_routes support to __init__.py**

In `python_service/httpserver/services/extractors/__init__.py`, add a `filename_extractor_registry` dict and modify `load_plugins()` to read `_filename_routes`:

```python
# After line 18 (extractor_registry = {})
filename_extractor_registry = {}

# In load_plugins(), after building extractor_registry, add:
# 4. Build filename-based registry
filename_routes = mapping.get("_filename_routes", {})
for filename, class_name in filename_routes.items():
    if class_name in registered_extractor_classes:
        cls = registered_extractor_classes[class_name]
        if class_name not in instances:
            try:
                instances[class_name] = cls()
            except Exception as e:
                logger.error(f"Failed to instantiate {class_name}: {e}")
                continue
        filename_extractor_registry[filename] = instances[class_name]
        logger.info(f"Filename route: '{filename}' -> {class_name}")
    else:
        logger.warning(f"Filename route class '{class_name}' not found in plugins.")
```

Add a new function after `get_extractor()`:

```python
def get_extractor_by_filename(filename: str):
    """Retrieves an extractor by exact filename match, returning None if unsupported."""
    return filename_extractor_registry.get(filename)
```

- [ ] **Step 3: Modify document_extractor.py to support filename routing**

In `python_service/httpserver/services/document_extractor.py`, update the import and `get_extractor` method:

```python
from .extractors import get_extractor, get_extractor_by_filename

class ExtractorLocator:
    def __init__(self):
        pass
        
    def get_extractor(self, file_path: str) -> Optional[BaseExtractor]:
        """Locates the appropriate extractor for the given file path."""
        path = Path(file_path)
        
        # Special fallback for LevelDB directories
        if path.is_dir() and (path / "CURRENT").exists():
            ext = "leveldb"
        else:
            ext = path.suffix.lower()

        # Try filename-based routing first (for auth.log, wtmp, SAM, etc.)
        extractor = get_extractor_by_filename(path.name)
        if extractor:
            logger.info(f"Routed '{path.name}' to {extractor.__class__.__name__} (by filename)")
            return extractor

        # Fall back to extension-based routing
        extractor = get_extractor(ext)
        if extractor:
            logger.info(f"Routed {ext} to {extractor.__class__.__name__}")
        else:
            logger.warning(f"No extractor available for {ext}")
            
        return extractor
```

- [ ] **Step 4: Commit**

```bash
git add python_service/httpserver/services/extractors/__init__.py python_service/httpserver/services/document_extractor.py
git commit -m "feat: extend extractor routing with filename-based lookup"
```

---

## Task 3: EmlExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/email.py`
- Test: `python_service/tests/unit/test_forensic_extractors.py`

- [ ] **Step 1: Write the failing test**

Create `python_service/tests/unit/test_forensic_extractors.py`:

```python
"""Unit tests for forensic file type extractors."""
import pytest
import os
import tempfile
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


@pytest.fixture
def sample_eml_file():
    """Create a sample EML file for testing."""
    msg = MIMEMultipart()
    msg['From'] = 'sender@example.com'
    msg['To'] = 'recipient@example.com'
    msg['Date'] = 'Mon, 15 Jan 2024 10:30:00 +0000'
    msg['Subject'] = 'Test Email Subject'
    msg['Message-ID'] = '<test123@example.com>'
    msg['X-Mailer'] = 'TestMailer 1.0'
    
    msg.attach(MIMEText('This is the email body text.', 'plain'))
    
    # Add attachment
    attachment = MIMEBase('application', 'pdf')
    attachment.set_payload(b'fake pdf content')
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', 'attachment', filename='document.pdf')
    msg.attach(attachment)
    
    with tempfile.NamedTemporaryFile(suffix='.eml', delete=False, mode='w') as f:
        f.write(msg.as_string())
        return f.name


@pytest.mark.asyncio
async def test_eml_extractor_basic(sample_eml_file):
    """Test EML extractor returns correct markdown structure."""
    from httpserver.services.extractors.email import EmlExtractor
    
    extractor = EmlExtractor()
    result = await extractor.extract_to_markdown(sample_eml_file)
    
    assert '# Email Summary' in result
    assert 'sender@example.com' in result
    assert 'recipient@example.com' in result
    assert 'Test Email Subject' in result
    assert 'This is the email body text.' in result
    assert 'document.pdf' in result
    
    os.unlink(sample_eml_file)


@pytest.mark.asyncio
async def test_eml_extractor_nonexistent_file():
    """Test EML extractor handles missing files gracefully."""
    from httpserver.services.extractors.email import EmlExtractor
    
    extractor = EmlExtractor()
    result = await extractor.extract_to_markdown('/nonexistent/file.eml')
    
    assert 'Error' in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_eml_extractor_basic -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'httpserver.services.extractors.email'`

- [ ] **Step 3: Write EmlExtractor implementation**

Create `python_service/httpserver/services/extractors/email.py`:

```python
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
                # Fallback to HTML if no plain text found
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
        
        # Headers table
        result.append("## Headers")
        result.append("| Header | Value |")
        result.append("| --- | --- |")
        for key in ['message_id', 'x_mailer', 'reply_to', 'in_reply_to']:
            if fields[key]:
                result.append(f"| {key.replace('_', '-').title()} | {fields[key]} |")
        result.append("")
        
        # Body
        result.append("## Body")
        if body:
            # Truncate very long bodies
            if len(body) > 10000:
                body = body[:10000] + "\n\n... (truncated)"
            result.append(body)
        else:
            result.append("*(No text content found)*")
        result.append("")
        
        # Attachments
        result.append(f"## Attachments ({len(attachments)})")
        if attachments:
            for i, att in enumerate(attachments, 1):
                size_str = _format_size(att['size'])
                result.append(f"{i}. `{att['filename']}` ({att['content_type']}, {size_str})")
        else:
            result.append("*No attachments*")
        
        return "\n".join(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_eml_extractor_basic tests/unit/test_forensic_extractors.py::test_eml_extractor_nonexistent_file -v`

Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/services/extractors/email.py python_service/tests/unit/test_forensic_extractors.py
git commit -m "feat: add EmlExtractor for RFC 822 email files"
```

---

## Task 4: MsgExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/email.py`
- Modify: `python_service/tests/unit/test_forensic_extractors.py`

- [ ] **Step 1: Write the failing test**

Append to `python_service/tests/unit/test_forensic_extractors.py`:

```python
@pytest.fixture
def sample_msg_file():
    """Create a minimal OLE2 MSG file for testing using olefile."""
    import olefile
    import struct
    import tempfile
    
    # Create a minimal MSG file structure
    # This is a simplified MSG - real MSG files are more complex
    tmp = tempfile.NamedTemporaryFile(suffix='.msg', delete=False)
    tmp.close()
    
    # Use olefile to create a minimal OLE2 file
    # For testing, we'll create a very basic structure
    ole = olefile.OleFileIO.new()
    
    # Add version stream
    ole.write_stream('\x01Version', struct.pack('<I', 0x00000300))
    
    # Add properties stream with basic MSG properties
    # Property tags for MSG:
    # 0x0037001F = Subject (Unicode string)
    # 0x0C1A001F = SenderName (Unicode string)  
    # 0x0E040003 = DisplayTo (Unicode string)
    # 0x00470102 = MessageDeliveryTime (FILETIME)
    props = struct.pack('<I', 0x0037001F)  # Subject property tag
    props += struct.pack('<I', 0)  # Reserved
    props += 'Test Subject\x00'.encode('utf-16-le')
    
    ole.write_stream('\x01Properties', props)
    
    # Add body stream
    ole.write_stream('\x01Body', 'Test MSG body content.'.encode('utf-16-le'))
    
    ole.save(tmp.name)
    ole.close()
    
    return tmp.name


@pytest.mark.asyncio
async def test_msg_extractor_basic(sample_msg_file):
    """Test MSG extractor returns correct markdown structure."""
    from httpserver.services.extractors.email import MsgExtractor
    
    extractor = MsgExtractor()
    result = await extractor.extract_to_markdown(sample_msg_file)
    
    assert '# Email Summary' in result
    assert 'Body' in result
    
    os.unlink(sample_msg_file)


@pytest.mark.asyncio
async def test_msg_extractor_nonexistent_file():
    """Test MSG extractor handles missing files gracefully."""
    from httpserver.services.extractors.email import MsgExtractor
    
    extractor = MsgExtractor()
    result = await extractor.extract_to_markdown('/nonexistent/file.msg')
    
    assert 'Error' in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_msg_extractor_basic -v`

Expected: FAIL (MsgExtractor not yet defined)

- [ ] **Step 3: Write MsgExtractor implementation**

Append to `python_service/httpserver/services/extractors/email.py`:

```python
@register_extractor
class MsgExtractor(BaseExtractor):
    """Extracts content from Outlook MSG files (OLE2 format)."""
    
    # MSG property tags
    PROP_SUBJECT = 0x0037
    PROP_SENDER_NAME = 0x0C1A
    PROP_SENDER_EMAIL = 0x0C1F
    PROP_DISPLAY_TO = 0x0E04
    PROP_DISPLAY_CC = 0x0E03
    PROP_DELIVERY_TIME = 0x0047
    PROP_BODY = 0x1000
    PROP_HTML_BODY = 0x1013
    
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
        """Extract named properties from the MSG properties stream."""
        fields = {}
        try:
            if ole.exists('\x01Properties'):
                data = ole.openstream('\x01Properties').read()
                # Parse properties stream (simplified)
                # Real MSG property parsing is more complex
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
        """Try to find a named string property in the OLE streams."""
        # Try common stream paths for named properties
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
        """Extract body text from MSG file."""
        # Try plain text body first
        for stream_name in ['\x01Body', 'Body']:
            if ole.exists(stream_name):
                try:
                    data = ole.openstream(stream_name).read()
                    return data.decode('utf-16-le', errors='replace').rstrip('\x00')
                except:
                    pass
        
        # Fallback to HTML body
        for stream_name in ['\x01HTMLBody', 'HTMLBody']:
            if ole.exists(stream_name):
                try:
                    data = ole.openstream(stream_name).read()
                    return data.decode('utf-8', errors='replace')
                except:
                    pass
        
        return ""
    
    def _extract_attachments(self, ole) -> list:
        """Extract attachment information from MSG file."""
        attachments = []
        # MSG attachments are stored in __attach_version1.0 streams
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_msg_extractor_basic tests/unit/test_forensic_extractors.py::test_msg_extractor_nonexistent_file -v`

Expected: Both tests PASS

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/services/extractors/email.py python_service/tests/unit/test_forensic_extractors.py
git commit -m "feat: add MsgExtractor for Outlook MSG files"
```

---

## Task 5: MboxExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/email.py`
- Modify: `python_service/tests/unit/test_forensic_extractors.py`

- [ ] **Step 1: Write the failing test**

Append to `python_service/tests/unit/test_forensic_extractors.py`:

```python
@pytest.fixture
def sample_mbox_file():
    """Create a sample MBOX file for testing."""
    import tempfile
    
    content = """From sender@example.com Mon Jan 15 10:30:00 2024
From: sender@example.com
To: recipient@example.com
Date: Mon, 15 Jan 2024 10:30:00 +0000
Subject: First Message

This is the first message body.

From another@example.com Mon Jan 15 11:00:00 2024
From: another@example.com
To: recipient@example.com
Date: Mon, 15 Jan 2024 11:00:00 +0000
Subject: Second Message

This is the second message body.
"""
    
    with tempfile.NamedTemporaryFile(suffix='.mbox', delete=False, mode='w') as f:
        f.write(content)
        return f.name


@pytest.mark.asyncio
async def test_mbox_extractor_basic(sample_mbox_file):
    """Test Mbox extractor returns correct markdown structure."""
    from httpserver.services.extractors.email import MboxExtractor
    
    extractor = MboxExtractor()
    result = await extractor.extract_to_markdown(sample_mbox_file)
    
    assert '# Mbox Summary' in result
    assert 'Total Messages' in result
    assert 'First Message' in result or 'sender@example.com' in result
    
    os.unlink(sample_mbox_file)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_mbox_extractor_basic -v`

Expected: FAIL (MboxExtractor not yet defined)

- [ ] **Step 3: Write MboxExtractor implementation**

Append to `python_service/httpserver/services/extractors/email.py`:

```python
@register_extractor
class MboxExtractor(BaseExtractor):
    """Extracts content from Unix MBOX mailbox files."""
    
    def __init__(self, sample_size: int = 100, body_preview_chars: int = 500):
        self.sample_size = sample_size
        self.body_preview_chars = body_preview_chars
    
    async def extract_to_markdown(self, file_path: str) -> str:
        import mailbox
        from datetime import datetime
        
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
            
            # Find date range
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
            
            # Sample messages
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_mbox_extractor_basic -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/services/extractors/email.py python_service/tests/unit/test_forensic_extractors.py
git commit -m "feat: add MboxExtractor for Unix MBOX mailbox files"
```

---

## Task 6: PstExtractor

**Files:**
- Modify: `python_service/httpserver/services/extractors/email.py`

- [ ] **Step 1: Write PstExtractor implementation**

Append to `python_service/httpserver/services/extractors/email.py`:

```python
@register_extractor
class PstExtractor(BaseExtractor):
    """Extracts metadata from PST/OST files (Outlook data files)."""
    
    # PST magic bytes
    PST_MAGIC = b'!BDN'
    OST_MAGIC = b'!BDN'
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
        except Exception as e:
            logger.error(f"Error reading PST file {file_path}: {e}")
            return f"Error: Failed to read PST/OST file: {e}"
        
        if len(header) < 4:
            return "Error: File too small to be a valid PST/OST file."
        
        # Check magic bytes
        magic = header[:4]
        if magic != self.PST_MAGIC:
            return f"Error: Not a valid PST/OST file (magic bytes: {magic.hex()})"
        
        # Try full extraction with pffexport
        pffexport_result = self._try_pffexport(file_path)
        if pffexport_result:
            return pffexport_result
        
        # Fallback: header-only parsing
        return self._parse_header(file_path, header)
    
    def _try_pffexport(self, file_path: str) -> str:
        """Try using pffexport CLI tool for full extraction."""
        import subprocess
        
        try:
            result = subprocess.run(
                ['pffexport', '-t', '/tmp/pst_export', file_path],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0:
                # Parse export output
                return self._parse_pffexport_output('/tmp/pst_export')
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return ""
    
    def _parse_pffexport_output(self, export_dir: str) -> str:
        """Parse pffexport output directory."""
        import os
        
        if not os.path.exists(export_dir):
            return ""
        
        result = ["# PST/OST Export Summary"]
        result.append(f"**Export Directory:** {export_dir}")
        result.append("")
        
        # Count exported items
        total_files = 0
        for root, dirs, files in os.walk(export_dir):
            total_files += len(files)
        
        result.append(f"**Total Exported Items:** {total_files}")
        return "\n".join(result)
    
    def _parse_header(self, file_path: str, header: bytes) -> str:
        """Parse PST header for basic metadata."""
        import struct
        
        result = [f"# PST/OST File Summary: `{os.path.basename(file_path)}`"]
        result.append("**Format:** PST (Personal Storage Table)")
        
        # Check if OST based on file extension
        if file_path.lower().endswith('.ost'):
            result[1] = result[1].replace('PST', 'OST (Offline Storage Table)')
        
        # Parse basic header fields
        # Offset 10: version (4 bytes, little-endian)
        if len(header) >= 14:
            version = struct.unpack_from('<I', header, 10)[0]
            version_str = {35: "ANSI (32-bit)", 23: "Unicode (32-bit)", 49: "Unicode (64-bit)"}.get(version, f"Unknown ({version})")
            result.append(f"**Version:** {version_str}")
        
        # Encryption type at offset 221
        if len(header) >= 222:
            enc_type = header[221]
            enc_str = {0: "None", 1: "Compressible", 2: "Strong"}.get(enc_type, f"Unknown ({enc_type})")
            result.append(f"**Encryption:** {enc_str}")
        
        # File size
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
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/email.py
git commit -m "feat: add PstExtractor for PST/OST Outlook data files"
```

---

## Task 7: EvtxExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/windows_evtx.py`
- Modify: `python_service/tests/unit/test_forensic_extractors.py`

- [ ] **Step 1: Write the failing test**

Append to `python_service/tests/unit/test_forensic_extractors.py`:

```python
@pytest.mark.asyncio
async def test_evtx_extractor_nonexistent_file():
    """Test EVTX extractor handles missing files gracefully."""
    from httpserver.services.extractors.windows_evtx import EvtxExtractor
    
    extractor = EvtxExtractor()
    result = await extractor.extract_to_markdown('/nonexistent/file.evtx')
    
    assert 'Error' in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_evtx_extractor_nonexistent_file -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write EvtxExtractor implementation**

Create `python_service/httpserver/services/extractors/windows_evtx.py`:

```python
"""Windows Event Log (EVTX) forensic extractor."""
import logging
import os
from collections import Counter
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# Common Windows Event IDs for forensic analysis
EVENT_ID_DESCRIPTIONS = {
    # Logon/Logoff
    4624: "Logon Success",
    4625: "Logon Failure",
    4634: "Logoff",
    4647: "User Initiated Logoff",
    4648: "Explicit Credential Logon",
    4672: "Special Privilege Logon",
    # Account Management
    4720: "User Account Created",
    4722: "User Account Enabled",
    4725: "User Account Disabled",
    4726: "User Account Deleted",
    4732: "Member Added to Local Group",
    4735: "Local Group Changed",
    4756: "Member Added to Universal Group",
    # Policy Changes
    4719: "System Audit Policy Changed",
    4739: "Domain Policy Changed",
    4704: "User Right Assigned",
    # System Events
    1074: "System Shutdown/Restart",
    6005: "Event Log Service Started",
    6006: "Event Log Service Stopped",
    6008: "Unexpected Shutdown",
    6009: "OS Version at Boot",
    6013: "System Uptime",
    7034: "Service Crashed",
    7035: "Service Control Manager",
    7036: "Service State Change",
    7040: "Service Start Type Changed",
    # Process Creation
    4688: "New Process Created",
    4689: "Process Exited",
    # File/Object Access
    4656: "Handle to Object Requested",
    4658: "Handle to Object Closed",
    4660: "Object Deleted",
    4663: "Object Access Attempt",
    # Scheduled Tasks
    4698: "Scheduled Task Created",
    4699: "Scheduled Task Deleted",
    4700: "Scheduled Task Enabled",
    4701: "Scheduled Task Disabled",
    4702: "Scheduled Task Updated",
    # PowerShell
    4103: "PowerShell Module Logging",
    4104: "PowerShell Script Block Logging",
    4105: "Script Block Execution Start",
    4106: "Script Block Execution End",
    # Windows Defender
    1116: "Malware Detected",
    1117: "Malware Action Taken",
    1118: "Malware Action Failed",
    # RDP
    1149: "RDP Connection Attempt",
    21: "RDP Session Logon",
    22: "RDP Shell Start",
    23: "RDP Session Logoff",
    24: "RDP Session Disconnect",
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
        
        # Collect all events
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
                
                # Extract message from EventData
                event_data = root.find('.//e:EventData', ns)
                message = ''
                if event_data is not None:
                    data_parts = []
                    for data in event_data.findall('e:Data', ns):
                        if data.text:
                            data_parts.append(data.text)
                    message = ' | '.join(data_parts[:3])  # First 3 data items
                
                event_id_counter[event_id] += 1
                level_counter[LEVEL_NAMES.get(level, f"Unknown({level})")] += 1
                
                events.append({
                    'timestamp': timestamp,
                    'event_id': event_id,
                    'level': LEVEL_NAMES.get(level, f"Unknown({level})"),
                    'provider': provider,
                    'computer': computer,
                    'message': message[:200],  # Truncate long messages
                })
            except Exception as e:
                logger.warning(f"Error parsing EVTX record: {e}")
                continue
        
        if not events:
            return f"# Windows Event Log Summary: `{os.path.basename(file_path)}`\n\n*(No events found or file is empty)*"
        
        # Build markdown
        result = [f"# Windows Event Log Summary: `{os.path.basename(file_path)}`"]
        
        # Metadata
        computers = set(e['computer'] for e in events if e['computer'])
        result.append(f"**Computer:** {', '.join(computers) if computers else 'Unknown'}")
        result.append(f"**Total Records:** {len(events):,}")
        
        # Time range
        timestamps = [e['timestamp'] for e in events if e['timestamp']]
        if timestamps:
            result.append(f"**Time Range:** {timestamps[-1]} ~ {timestamps[0]}")
        result.append("")
        
        # Event Distribution (Top 20)
        result.append("## Event Distribution (Top 20)")
        result.append("| Event ID | Count | Level | Description |")
        result.append("| --- | --- | --- | --- |")
        for event_id, count in event_id_counter.most_common(20):
            desc = EVENT_ID_DESCRIPTIONS.get(event_id, "")
            # Find the most common level for this event ID
            level = next((e['level'] for e in events if e['event_id'] == event_id), "Info")
            result.append(f"| {event_id} | {count:,} | {level} | {desc} |")
        result.append("")
        
        # Level Distribution
        result.append("## Level Distribution")
        result.append("| Level | Count |")
        result.append("| --- | --- |")
        for level, count in level_counter.most_common():
            result.append(f"| {level} | {count:,} |")
        result.append("")
        
        # Recent Events (sample)
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py::test_evtx_extractor_nonexistent_file -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/services/extractors/windows_evtx.py python_service/tests/unit/test_forensic_extractors.py
git commit -m "feat: add EvtxExtractor for Windows Event Log files"
```

---

## Task 8: RegistryExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/windows_registry.py`

- [ ] **Step 1: Write RegistryExtractor implementation**

Create `python_service/httpserver/services/extractors/windows_registry.py`:

```python
"""Windows Registry hive forensic extractor."""
import logging
import os
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# Registry hive magic bytes
REGF_MAGIC = b'regf'

# Forensically important registry key paths
IMPORTANT_KEYS = {
    'SAM': [
        r'SAM\Domains\Account\Users',
        r'SAM\Domains\Account\Users\Names',
    ],
    'SYSTEM': [
        r'Select',
        r'ControlSet001\Control\ComputerName\ComputerName',
        r'ControlSet001\Services',
        r'ControlSet001\Control\Session Manager\Environment',
    ],
    'SOFTWARE': [
        r'Microsoft\Windows\CurrentVersion\Run',
        r'Microsoft\Windows\CurrentVersion\RunOnce',
        r'Microsoft\Windows NT\CurrentVersion',
        r'Microsoft\Windows\CurrentVersion\Uninstall',
    ],
    'NTUSER': [
        r'Software\Microsoft\Windows\CurrentVersion\Explorer\RecentDocs',
        r'Software\Microsoft\Windows\CurrentVersion\Explorer\RunMRU',
        r'Software\Microsoft\Windows\CurrentVersion\Explorer\TypedPaths',
        r'Software\Microsoft\Windows\CurrentVersion\Explorer\ComDlg32\OpenSavePidlMRU',
        r'Software\Microsoft\Internet Explorer\Main',
        r'Software\Microsoft\Windows\CurrentVersion\Internet Settings',
        r'Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders',
    ],
}


def _detect_hive_type(file_path: str, reg) -> str:
    """Detect the registry hive type from filename and root key name."""
    name = os.path.basename(file_path).upper()
    if 'SAM' in name:
        return 'SAM'
    elif 'SYSTEM' in name:
        return 'SYSTEM'
    elif 'SOFTWARE' in name:
        return 'SOFTWARE'
    elif 'SECURITY' in name:
        return 'SECURITY'
    elif 'NTUSER' in name:
        return 'NTUSER'
    elif 'USRCLASS' in name:
        return 'UsrClass'
    elif 'DEFAULT' in name:
        return 'DEFAULT'
    else:
        # Try to detect from root key name
        try:
            root = reg.root()
            root_name = root.name() if root else "Unknown"
            return f"Unknown ({root_name})"
        except:
            return "Unknown"


def _format_timestamp(timestamp) -> str:
    """Format a registry timestamp to human-readable string."""
    if timestamp is None:
        return ""
    try:
        if isinstance(timestamp, datetime):
            return timestamp.strftime('%Y-%m-%d %H:%M:%S')
        return str(timestamp)
    except:
        return str(timestamp)


@register_extractor
class RegistryExtractor(BaseExtractor):
    """Extracts content from Windows Registry hive files."""
    
    def __init__(self, max_keys: int = 500):
        self.max_keys = max_keys
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            import Registry
        except ImportError:
            return "Error: python-registry library is not installed. Please install python-registry to analyze Registry hive files."
        
        # Check magic bytes first
        try:
            with open(file_path, 'rb') as f:
                magic = f.read(4)
            if magic != REGF_MAGIC:
                return f"Error: Not a valid Registry hive file (magic bytes: {magic.hex()}, expected: {REGF_MAGIC.hex()})"
        except Exception as e:
            return f"Error: Failed to read file: {e}"
        
        try:
            reg = Registry.Registry(file_path)
        except Exception as e:
            logger.error(f"Error opening Registry hive {file_path}: {e}")
            return f"Error: Failed to open Registry hive: {e}"
        
        try:
            hive_type = _detect_hive_type(file_path, reg)
            root = reg.root()
            
            # Count total keys
            total_keys = self._count_keys(root)
            
            result = [f"# Windows Registry Summary: `{os.path.basename(file_path)}`"]
            result.append(f"**Hive Type:** {hive_type}")
            result.append(f"**Root Key:** {root.name()}")
            result.append(f"**Total Keys:** {total_keys:,}")
            result.append("")
            
            # Extract forensically important keys
            result.append("## Forensically Important Keys")
            result.append("")
            
            important_paths = IMPORTANT_KEYS.get(hive_type, [])
            if not important_paths:
                # Try all hive types for generic hives
                for paths in IMPORTANT_KEYS.values():
                    important_paths.extend(paths)
            
            found_important = False
            for key_path in important_paths:
                try:
                    key = reg.open(key_path)
                    if key:
                        found_important = True
                        result.append(f"### `{key_path}`")
                        
                        # Values
                        values = list(key.values())
                        if values:
                            result.append("| Name | Type | Data |")
                            result.append("| --- | --- | --- |")
                            for v in values[:20]:  # Limit values per key
                                vtype = v.type_str()
                                vdata = str(v.value())
                                if len(vdata) > 100:
                                    vdata = vdata[:97] + "..."
                                vdata = vdata.replace('|', '\\|').replace('\n', ' ')
                                result.append(f"| {v.name()} | {vtype} | {vdata} |")
                        
                        # Subkeys
                        subkeys = list(key.subkeys())
                        if subkeys:
                            result.append(f"\n*Subkeys: {', '.join(sk.name() for sk in subkeys[:10])}*")
                            if len(subkeys) > 10:
                                result.append(f"*... and {len(subkeys) - 10} more*")
                        result.append("")
                except Registry.RegistryKeyNotFoundException:
                    pass
                except Exception as e:
                    logger.warning(f"Error reading registry key {key_path}: {e}")
            
            if not found_important:
                result.append("*No forensically important keys found for this hive type.*\n")
            
            # Key tree sample
            result.append("## Key Tree (Sample)")
            result.append("```")
            self._render_tree(root, result, depth=0, max_depth=3, max_children=5)
            result.append("```")
            
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing Registry hive {file_path}: {e}")
            return f"Error: Failed to parse Registry hive: {e}"
    
    def _count_keys(self, key) -> int:
        """Count total number of registry keys recursively."""
        count = 1
        try:
            for subkey in key.subkeys():
                count += self._count_keys(subkey)
        except:
            pass
        return count
    
    def _render_tree(self, key, result: list, depth: int, max_depth: int, max_children: int):
        """Render registry key tree as text."""
        if depth > max_depth:
            return
        
        indent = "  " * depth
        result.append(f"{indent}{key.name()}/")
        
        try:
            subkeys = list(key.subkeys())
            for i, subkey in enumerate(subkeys):
                if i >= max_children:
                    result.append(f"{indent}  ... ({len(subkeys) - max_children} more subkeys)")
                    break
                self._render_tree(subkey, result, depth + 1, max_depth, max_children)
        except:
            pass
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/windows_registry.py
git commit -m "feat: add RegistryExtractor for Windows Registry hive files"
```

---

## Task 9: LnkExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/windows_lnk.py`

- [ ] **Step 1: Write LnkExtractor implementation**

Create `python_service/httpserver/services/extractors/windows_lnk.py`:

```python
"""Windows LNK shortcut and Jump List forensic extractors."""
import logging
import os
import struct
from datetime import datetime, timedelta

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# LNK file magic bytes
LNK_MAGIC = b'\x4c\x00\x00\x00'  # LNK header magic

# LNK flags
LNK_FLAG_HAS_TARGET_ID_LIST = 0x00000001
LNK_FLAG_HAS_LINK_INFO = 0x00000002
LNK_FLAG_HAS_NAME = 0x00000004
LNK_FLAG_HAS_WORKING_DIR = 0x00000010
LNK_FLAG_HAS_ARGUMENTS = 0x00000020
LNK_FLAG_HAS_ICON_LOCATION = 0x00000040

# Drive types
DRIVE_TYPES = {
    0: "Unknown",
    1: "No Root Dir",
    2: "Removable",
    3: "Fixed",
    4: "Remote",
    5: "CD-ROM",
    6: "RAM Disk",
}


def _filetime_to_datetime(filetime: int) -> datetime:
    """Convert Windows FILETIME to Python datetime."""
    if filetime == 0:
        return None
    # FILETIME is 100-nanosecond intervals since 1601-01-01
    epoch_diff = 116444736000000000  # Difference between 1601 and 1970 in 100ns intervals
    try:
        timestamp = (filetime - epoch_diff) / 10000000
        return datetime.fromtimestamp(timestamp)
    except (ValueError, OSError, OverflowError):
        return None


def _format_datetime(dt: datetime) -> str:
    """Format datetime to string."""
    if dt is None:
        return "N/A"
    return dt.strftime('%Y-%m-%d %H:%M:%S')


@register_extractor
class LnkExtractor(BaseExtractor):
    """Extracts content from Windows LNK shortcut files."""
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            logger.error(f"Error reading LNK file {file_path}: {e}")
            return f"Error: Failed to read LNK file: {e}"
        
        if len(data) < 76:
            return "Error: File too small to be a valid LNK file."
        
        # Check magic
        if data[:4] != LNK_MAGIC:
            return f"Error: Not a valid LNK file (magic: {data[:4].hex()})"
        
        try:
            return self._parse_lnk(file_path, data)
        except Exception as e:
            logger.error(f"Error parsing LNK file {file_path}: {e}")
            return f"Error: Failed to parse LNK file: {e}"
    
    def _parse_lnk(self, file_path: str, data: bytes) -> str:
        # Parse header
        flags = struct.unpack_from('<I', data, 20)[0]
        
        # Parse timestamps (FILETIME at offsets 28, 36, 44)
        creation_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 28)[0])
        access_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 36)[0])
        modification_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 44)[0])
        
        # File size at offset 52
        file_size = struct.unpack_from('<I', data, 52)[0]
        
        # Parse LinkInfo if present
        target_path = ""
        volume_serial = ""
        drive_type = ""
        machine_id = ""
        mac_address = ""
        
        if flags & LNK_FLAG_HAS_LINK_INFO:
            link_info_offset = struct.unpack_from('<I', data, 24)[0]
            if link_info_offset < len(data):
                target_path, volume_serial, drive_type = self._parse_link_info(data, link_info_offset)
        
        # Parse string data
        working_dir = ""
        arguments = ""
        description = ""
        icon_location = ""
        
        offset = 76  # After header
        
        # Skip ID list if present
        if flags & LNK_FLAG_HAS_TARGET_ID_LIST:
            id_list_size = struct.unpack_from('<H', data, offset)[0]
            offset += 2 + id_list_size
        
        # Skip LinkInfo if present
        if flags & LNK_FLAG_HAS_LINK_INFO:
            link_info_size = struct.unpack_from('<I', data, offset)[0]
            offset += link_info_size
        
        # Parse string data
        if flags & LNK_FLAG_HAS_NAME:
            count = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            if flags & 0x00000008:  # Unicode
                description = data[offset:offset + count * 2].decode('utf-16-le', errors='replace').rstrip('\x00')
                offset += count * 2
            else:
                description = data[offset:offset + count].decode('cp1252', errors='replace').rstrip('\x00')
                offset += count
        
        if flags & LNK_FLAG_HAS_WORKING_DIR:
            count = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            if flags & 0x00000008:
                working_dir = data[offset:offset + count * 2].decode('utf-16-le', errors='replace').rstrip('\x00')
                offset += count * 2
            else:
                working_dir = data[offset:offset + count].decode('cp1252', errors='replace').rstrip('\x00')
                offset += count
        
        if flags & LNK_FLAG_HAS_ARGUMENTS:
            count = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            if flags & 0x00000008:
                arguments = data[offset:offset + count * 2].decode('utf-16-le', errors='replace').rstrip('\x00')
                offset += count * 2
            else:
                arguments = data[offset:offset + count].decode('cp1252', errors='replace').rstrip('\x00')
                offset += count
        
        if flags & LNK_FLAG_HAS_ICON_LOCATION:
            count = struct.unpack_from('<I', data, offset)[0]
            offset += 4
            if flags & 0x00000008:
                icon_location = data[offset:offset + count * 2].decode('utf-16-le', errors='replace').rstrip('\x00')
            else:
                icon_location = data[offset:offset + count].decode('cp1252', errors='replace').rstrip('\x00')
        
        # Extract machine ID and MAC from ExtraData
        machine_id, mac_address = self._parse_extra_data(data, offset)
        
        # Build markdown
        result = [f"# Windows Shortcut Analysis: `{os.path.basename(file_path)}`"]
        result.append(f"**Target Path:** {target_path or 'N/A'}")
        if working_dir:
            result.append(f"**Working Directory:** {working_dir}")
        if arguments:
            result.append(f"**Arguments:** {arguments}")
        if description:
            result.append(f"**Description:** {description}")
        if icon_location:
            result.append(f"**Icon Location:** {icon_location}")
        result.append("")
        
        result.append("## Timestamps")
        result.append("| Type | Timestamp |")
        result.append("| --- | --- |")
        result.append(f"| Created | {_format_datetime(creation_time)} |")
        result.append(f"| Modified | {_format_datetime(modification_time)} |")
        result.append(f"| Accessed | {_format_datetime(access_time)} |")
        result.append("")
        
        result.append("## Target Information")
        if drive_type:
            result.append(f"**Drive Type:** {drive_type}")
        if volume_serial:
            result.append(f"**Volume Serial:** {volume_serial}")
        result.append(f"**File Size:** {file_size:,} bytes")
        result.append("")
        
        if machine_id or mac_address:
            result.append("## Machine Info")
            if machine_id:
                result.append(f"**Machine ID:** {machine_id}")
            if mac_address:
                result.append(f"**MAC Address:** {mac_address}")
        
        return "\n".join(result)
    
    def _parse_link_info(self, data: bytes, offset: int) -> tuple:
        """Parse LinkInfo structure."""
        target_path = ""
        volume_serial = ""
        drive_type = ""
        
        try:
            link_info_size = struct.unpack_from('<I', data, offset)[0]
            link_info_header_size = struct.unpack_from('<I', data, offset + 4)[0]
            flags = struct.unpack_from('<I', data, offset + 8)[0]
            
            if flags & 0x00000001:  # VolumeIDAndLocalBasePath
                volume_id_offset = struct.unpack_from('<I', data, offset + 16)[0]
                local_base_path_offset = struct.unpack_from('<I', data, offset + 20)[0]
                
                # Parse volume ID
                if volume_id_offset > 0:
                    vol_offset = offset + volume_id_offset
                    drive_type_int = struct.unpack_from('<I', data, vol_offset + 4)[0]
                    drive_type = DRIVE_TYPES.get(drive_type_int, f"Unknown ({drive_type_int})")
                    serial = struct.unpack_from('<I', data, vol_offset + 8)[0]
                    volume_serial = f"{serial:08X}"
                
                # Parse local base path
                if local_base_path_offset > 0:
                    path_offset = offset + local_base_path_offset
                    end = data.find(b'\x00', path_offset)
                    if end > path_offset:
                        target_path = data[path_offset:end].decode('cp1252', errors='replace')
        except Exception as e:
            logger.warning(f"Error parsing LinkInfo: {e}")
        
        return target_path, volume_serial, drive_type
    
    def _parse_extra_data(self, data: bytes, offset: int) -> tuple:
        """Parse ExtraData for machine ID and MAC address."""
        machine_id = ""
        mac_address = ""
        
        try:
            while offset + 8 < len(data):
                size = struct.unpack_from('<I', data, offset)[0]
                if size < 4:
                    break
                sig = struct.unpack_from('<I', data, offset + 4)[0]
                
                if sig == 0xA0000004:  # TrackerDataBlock
                    if size >= 32:
                        machine_id_raw = data[offset + 16:offset + 32]
                        machine_id = machine_id_raw.decode('cp1252', errors='replace').rstrip('\x00')
                        # MAC address at offset 32 (6 bytes)
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
            return "Error: olefile library is not installed. Please install olefile to analyze Jump List files."
        
        filename = os.path.basename(file_path)
        
        if file_path.endswith('.automaticDestinations-ms'):
            return self._parse_automatic(file_path, filename)
        elif file_path.endswith('.customDestinations-ms'):
            return self._parse_custom(file_path, filename)
        else:
            return "Error: Unknown Jump List format."
    
    def _parse_automatic(self, file_path: str, filename: str) -> str:
        """Parse automatic Jump List (OLE2 format)."""
        import olefile
        
        try:
            ole = olefile.OleFileIO(file_path)
        except Exception as e:
            return f"Error: Failed to open Jump List file: {e}"
        
        try:
            # Extract AppID from filename
            app_id = filename.split('.')[0]
            
            result = [f"# Jump List Analysis: `{filename}`"]
            result.append(f"**Application ID:** {app_id}")
            result.append(f"**Type:** Automatic Destination")
            result.append("")
            
            # Find LNK streams
            lnk_entries = []
            for stream in ole.listdir():
                stream_path = '/'.join(stream)
                if stream_path.startswith('DestList'):
                    continue
                try:
                    data = ole.openstream(stream).read()
                    if len(data) >= 4 and data[:4] == LNK_MAGIC:
                        lnk_entry = self._parse_lnk_data(data)
                        if lnk_entry:
                            lnk_entries.append(lnk_entry)
                except:
                    pass
            
            result.append(f"**Entry Count:** {len(lnk_entries)}")
            result.append("")
            
            if lnk_entries:
                result.append("## Recent Documents")
                result.append("| # | Target Path | Last Modified |")
                result.append("| --- | --- | --- |")
                for i, entry in enumerate(lnk_entries[:50], 1):
                    ts = _format_datetime(entry.get('modification_time'))
                    path = entry.get('target_path', 'N/A')
                    result.append(f"| {i} | {path} | {ts} |")
            else:
                result.append("*No LNK entries found in Jump List.*")
            
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing automatic Jump List {file_path}: {e}")
            return f"Error: Failed to parse Jump List: {e}"
        finally:
            ole.close()
    
    def _parse_custom(self, file_path: str, filename: str) -> str:
        """Parse custom Jump List (binary format)."""
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            return f"Error: Failed to read Jump List file: {e}"
        
        result = [f"# Jump List Analysis: `{filename}`"]
        result.append(f"**Type:** Custom Destination")
        result.append("")
        
        # Find embedded LNK entries
        lnk_entries = []
        offset = 0
        while offset < len(data) - 4:
            # Look for LNK magic bytes
            idx = data.find(LNK_MAGIC, offset)
            if idx == -1:
                break
            
            # Try to parse as LNK
            try:
                entry = self._parse_lnk_data(data[idx:])
                if entry:
                    lnk_entries.append(entry)
            except:
                pass
            
            offset = idx + 4
        
        result.append(f"**Entry Count:** {len(lnk_entries)}")
        result.append("")
        
        if lnk_entries:
            result.append("## Recent Documents")
            result.append("| # | Target Path | Last Modified |")
            result.append("| --- | --- | --- |")
            for i, entry in enumerate(lnk_entries[:50], 1):
                ts = _format_datetime(entry.get('modification_time'))
                path = entry.get('target_path', 'N/A')
                result.append(f"| {i} | {path} | {ts} |")
        else:
            result.append("*No LNK entries found in Jump List.*")
        
        return "\n".join(result)
    
    def _parse_lnk_data(self, data: bytes) -> dict:
        """Parse LNK data and extract key fields."""
        if len(data) < 76:
            return None
        
        try:
            flags = struct.unpack_from('<I', data, 20)[0]
            modification_time = _filetime_to_datetime(struct.unpack_from('<Q', data, 44)[0])
            
            target_path = ""
            if flags & LNK_FLAG_HAS_LINK_INFO:
                link_info_offset = struct.unpack_from('<I', data, 24)[0]
                if link_info_offset < len(data):
                    target_path, _, _ = LnkExtractor()._parse_link_info(data, link_info_offset)
            
            return {
                'target_path': target_path,
                'modification_time': modification_time,
            }
        except:
            return None
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/windows_lnk.py
git commit -m "feat: add LnkExtractor and JumplistExtractor for Windows shortcuts"
```

---

## Task 10: ChromeHistoryExtractor and FirefoxHistoryExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/browser_history.py`

- [ ] **Step 1: Write browser history extractors**

Create `python_service/httpserver/services/extractors/browser_history.py`:

```python
"""Browser history forensic extractors for Chrome and Firefox."""
import logging
import os
import sqlite3
from datetime import datetime, timedelta

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)


def _webkit_timestamp_to_datetime(webkit_ts: int) -> datetime:
    """Convert WebKit timestamp (microseconds since 1601-01-01) to datetime."""
    if webkit_ts == 0:
        return None
    try:
        epoch_diff = 116444736000000000
        unix_ts = (webkit_ts - epoch_diff) / 10000000
        return datetime.fromtimestamp(unix_ts)
    except (ValueError, OSError, OverflowError):
        return None


def _unix_microseconds_to_datetime(us: int) -> datetime:
    """Convert Unix epoch microseconds to datetime."""
    if us == 0:
        return None
    try:
        return datetime.fromtimestamp(us / 1000000)
    except (ValueError, OSError, OverflowError):
        return None


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.2f} MB"
    else:
        return f"{size_bytes / 1024 / 1024 / 1024:.2f} GB"


@register_extractor
class ChromeHistoryExtractor(BaseExtractor):
    """Extracts browsing history from Chrome's History SQLite database."""
    
    def __init__(self, sample_size: int = 200):
        self.sample_size = sample_size
    
    async def extract_to_markdown(self, file_path: str) -> str:
        # Handle both direct file path and directory path
        if os.path.isdir(file_path):
            db_path = os.path.join(file_path, 'History')
        else:
            db_path = file_path
        
        if not os.path.exists(db_path):
            return f"Error: Chrome History database not found at {db_path}"
        
        try:
            # Copy to temp to avoid lock issues
            import tempfile
            import shutil
            tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
            tmp.close()
            shutil.copy2(db_path, tmp.name)
            
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
        except Exception as e:
            logger.error(f"Error opening Chrome History DB {db_path}: {e}")
            return f"Error: Failed to open Chrome History database: {e}"
        
        try:
            result = ["# Chrome Browser History Summary"]
            
            # Get URL count
            cursor.execute("SELECT COUNT(*) FROM urls")
            total_urls = cursor.fetchone()[0]
            
            # Get downloads count
            try:
                cursor.execute("SELECT COUNT(*) FROM downloads")
                total_downloads = cursor.fetchone()[0]
            except:
                total_downloads = 0
            
            # Get time range
            try:
                cursor.execute("SELECT MIN(last_visit_time), MAX(last_visit_time) FROM urls")
                min_ts, max_ts = cursor.fetchone()
                min_date = _webkit_timestamp_to_datetime(min_ts)
                max_date = _webkit_timestamp_to_datetime(max_ts)
                if min_date and max_date:
                    result.append(f"**Time Range:** {min_date.strftime('%Y-%m-%d')} ~ {max_date.strftime('%Y-%m-%d')}")
            except:
                pass
            
            result.append(f"**Total URLs:** {total_urls:,}")
            result.append(f"**Total Downloads:** {total_downloads:,}")
            result.append("")
            
            # Top sites by visit count
            result.append("## Top Sites (by visit count)")
            result.append("| URL | Title | Visits | Last Visit |")
            result.append("| --- | --- | --- | --- |")
            
            cursor.execute("""
                SELECT url, title, visit_count, last_visit_time 
                FROM urls 
                ORDER BY visit_count DESC 
                LIMIT 50
            """)
            for row in cursor.fetchall():
                url, title, visit_count, last_visit_ts = row
                last_visit = _webkit_timestamp_to_datetime(last_visit_ts)
                last_visit_str = last_visit.strftime('%Y-%m-%d %H:%M') if last_visit else 'N/A'
                
                # Truncate long URLs and titles
                if len(url) > 80:
                    url = url[:77] + "..."
                if title and len(title) > 60:
                    title = title[:57] + "..."
                title = (title or '').replace('|', '\\|')
                
                result.append(f"| {url} | {title} | {visit_count:,} | {last_visit_str} |")
            
            result.append("")
            
            # Recent URLs
            result.append(f"## Recent URLs (Last {self.sample_size})")
            result.append("| URL | Title | Last Visit |")
            result.append("| --- | --- | --- |")
            
            cursor.execute("""
                SELECT url, title, last_visit_time 
                FROM urls 
                ORDER BY last_visit_time DESC 
                LIMIT ?
            """, (self.sample_size,))
            for row in cursor.fetchall():
                url, title, last_visit_ts = row
                last_visit = _webkit_timestamp_to_datetime(last_visit_ts)
                last_visit_str = last_visit.strftime('%Y-%m-%d %H:%M') if last_visit else 'N/A'
                
                if len(url) > 80:
                    url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60:
                    title = title[:57] + "..."
                
                result.append(f"| {url} | {title} | {last_visit_str} |")
            
            # Downloads
            if total_downloads > 0:
                result.append("")
                result.append("## Recent Downloads")
                result.append("| File | URL | Time | Size |")
                result.append("| --- | --- | --- | --- |")
                
                try:
                    cursor.execute("""
                        SELECT target_path, url, start_time, total_bytes 
                        FROM downloads 
                        ORDER BY start_time DESC 
                        LIMIT 50
                    """)
                    for row in cursor.fetchall():
                        target_path, url, start_ts, total_bytes = row
                        start_time = _webkit_timestamp_to_datetime(start_ts)
                        start_str = start_time.strftime('%Y-%m-%d %H:%M') if start_time else 'N/A'
                        filename = os.path.basename(target_path) if target_path else 'N/A'
                        size_str = _format_size(total_bytes) if total_bytes else 'N/A'
                        
                        if len(url) > 60:
                            url = url[:57] + "..."
                        filename = filename.replace('|', '\\|')
                        
                        result.append(f"| {filename} | {url} | {start_str} | {size_str} |")
                except Exception as e:
                    logger.warning(f"Error reading downloads: {e}")
            
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing Chrome History {db_path}: {e}")
            return f"Error: Failed to parse Chrome History: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)


@register_extractor
class FirefoxHistoryExtractor(BaseExtractor):
    """Extracts browsing history from Firefox's places.sqlite database."""
    
    def __init__(self, sample_size: int = 200):
        self.sample_size = sample_size
    
    async def extract_to_markdown(self, file_path: str) -> str:
        # Handle both direct file path and directory path
        if os.path.isdir(file_path):
            db_path = os.path.join(file_path, 'places.sqlite')
        else:
            db_path = file_path
        
        if not os.path.exists(db_path):
            return f"Error: Firefox places.sqlite not found at {db_path}"
        
        try:
            import tempfile
            import shutil
            tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
            tmp.close()
            shutil.copy2(db_path, tmp.name)
            
            conn = sqlite3.connect(tmp.name)
            cursor = conn.cursor()
        except Exception as e:
            logger.error(f"Error opening Firefox places.sqlite {db_path}: {e}")
            return f"Error: Failed to open Firefox history database: {e}"
        
        try:
            result = ["# Firefox Browser History Summary"]
            
            # Get URL count
            cursor.execute("SELECT COUNT(*) FROM moz_places WHERE visit_count > 0")
            total_urls = cursor.fetchone()[0]
            
            # Get bookmark count
            try:
                cursor.execute("SELECT COUNT(*) FROM moz_bookmarks WHERE type = 1")
                total_bookmarks = cursor.fetchone()[0]
            except:
                total_bookmarks = 0
            
            # Time range
            try:
                cursor.execute("SELECT MIN(visit_date), MAX(visit_date) FROM moz_historyvisits")
                min_ts, max_ts = cursor.fetchone()
                if min_ts and max_ts:
                    min_date = _unix_microseconds_to_datetime(min_ts)
                    max_date = _unix_microseconds_to_datetime(max_ts)
                    if min_date and max_date:
                        result.append(f"**Time Range:** {min_date.strftime('%Y-%m-%d')} ~ {max_date.strftime('%Y-%m-%d')}")
            except:
                pass
            
            result.append(f"**Total URLs:** {total_urls:,}")
            result.append(f"**Total Bookmarks:** {total_bookmarks:,}")
            result.append("")
            
            # Top sites
            result.append("## Top Sites (by visit count)")
            result.append("| URL | Title | Visits | Last Visit |")
            result.append("| --- | --- | --- | --- |")
            
            cursor.execute("""
                SELECT p.url, p.title, p.visit_count, p.last_visit_date
                FROM moz_places p
                WHERE p.visit_count > 0
                ORDER BY p.visit_count DESC
                LIMIT 50
            """)
            for row in cursor.fetchall():
                url, title, visit_count, last_visit_ts = row
                last_visit = _unix_microseconds_to_datetime(last_visit_ts)
                last_visit_str = last_visit.strftime('%Y-%m-%d %H:%M') if last_visit else 'N/A'
                
                if len(url) > 80:
                    url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60:
                    title = title[:57] + "..."
                
                result.append(f"| {url} | {title} | {visit_count:,} | {last_visit_str} |")
            
            # Recent URLs
            result.append("")
            result.append(f"## Recent URLs (Last {self.sample_size})")
            result.append("| URL | Title | Last Visit |")
            result.append("| --- | --- | --- |")
            
            cursor.execute("""
                SELECT p.url, p.title, h.visit_date
                FROM moz_historyvisits h
                JOIN moz_places p ON h.place_id = p.id
                ORDER BY h.visit_date DESC
                LIMIT ?
            """, (self.sample_size,))
            for row in cursor.fetchall():
                url, title, visit_date = row
                dt = _unix_microseconds_to_datetime(visit_date)
                dt_str = dt.strftime('%Y-%m-%d %H:%M') if dt else 'N/A'
                
                if len(url) > 80:
                    url = url[:77] + "..."
                title = (title or '').replace('|', '\\|')
                if len(title) > 60:
                    title = title[:57] + "..."
                
                result.append(f"| {url} | {title} | {dt_str} |")
            
            # Bookmarks
            if total_bookmarks > 0:
                result.append("")
                result.append("## Recent Bookmarks")
                result.append("| Title | URL | Added |")
                result.append("| --- | --- | --- |")
                
                cursor.execute("""
                    SELECT b.title, p.url, b.dateAdded
                    FROM moz_bookmarks b
                    JOIN moz_places p ON b.fk = p.id
                    WHERE b.type = 1
                    ORDER BY b.dateAdded DESC
                    LIMIT 50
                """)
                for row in cursor.fetchall():
                    title, url, date_added = row
                    dt = _unix_microseconds_to_datetime(date_added)
                    dt_str = dt.strftime('%Y-%m-%d %H:%M') if dt else 'N/A'
                    
                    title = (title or '').replace('|', '\\|')
                    if len(title) > 40:
                        title = title[:37] + "..."
                    if len(url) > 60:
                        url = url[:57] + "..."
                    
                    result.append(f"| {title} | {url} | {dt_str} |")
            
            return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing Firefox history {db_path}: {e}")
            return f"Error: Failed to parse Firefox history: {e}"
        finally:
            conn.close()
            os.unlink(tmp.name)
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/browser_history.py
git commit -m "feat: add ChromeHistoryExtractor and FirefoxHistoryExtractor"
```

---

## Task 11: AuthLogExtractor and WtmpExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/linux_journal.py`

- [ ] **Step 1: Write Linux log extractors**

Create `python_service/httpserver/services/extractors/linux_journal.py`:

```python
"""Linux system log forensic extractors: auth.log, wtmp, systemd journal."""
import logging
import os
import re
import struct
from collections import Counter, defaultdict
from datetime import datetime

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# Syslog timestamp format: "Jan 15 10:30:00"
SYSLOG_TS_RE = re.compile(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})')
SYSLOG_HOST_PROC_RE = re.compile(r'^\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\s+(\S+)\s+(\S+?)(?:\[(\d+)\])?\s*:\s*(.*)')

# SSH login patterns
SSH_SUCCESS_RE = re.compile(r'Accepted\s+(publickey|password|keyboard-interactive)\s+for\s+(\S+)\s+from\s+(\S+)')
SSH_FAILURE_RE = re.compile(r'Failed\s+(publickey|password|keyboard-interactive)\s+for\s+(\S+)\s+from\s+(\S+)')
SUDO_RE = re.compile(r'sudo:\s+(\S+)\s*:\s*(.*?);\s*TTY=(\S+)\s*;\s*PWD=(\S+)\s*;\s*USER=(\S+)\s*;\s*COMMAND=(.*)')
SU_RE = re.compile(r'su\[(\d+)\]:\s+(.*?)(?:to\s+(\S+))?')


@register_extractor
class AuthLogExtractor(BaseExtractor):
    """Extracts authentication events from Linux auth.log files."""
    
    def __init__(self, max_entries: int = 500):
        self.max_entries = max_entries
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading auth.log {file_path}: {e}")
            return f"Error: Failed to read auth.log: {e}"
        
        if not lines:
            return f"# Authentication Log Summary: `{os.path.basename(file_path)}`\n\n*(Empty log file)*"
        
        # Parse entries
        entries = []
        stats = Counter()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            entry = self._parse_line(line)
            if entry:
                entries.append(entry)
                stats[entry['event_type']] += 1
        
        if not entries:
            return f"# Authentication Log Summary: `{os.path.basename(file_path)}`\n\n*(No parseable entries found)*"
        
        # Build markdown
        result = [f"# Authentication Log Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**Total Entries:** {len(entries):,}")
        
        if entries:
            result.append(f"**Time Range:** {entries[0].get('timestamp', 'N/A')} ~ {entries[-1].get('timestamp', 'N/A')}")
        result.append("")
        
        # Statistics
        result.append("## Authentication Statistics")
        result.append("| Event Type | Count |")
        result.append("| --- | --- |")
        for event_type, count in stats.most_common():
            result.append(f"| {event_type} | {count:,} |")
        result.append("")
        
        # Login attempts
        login_entries = [e for e in entries if 'Login' in e.get('event_type', '') or 'Sudo' in e.get('event_type', '')]
        if login_entries:
            result.append(f"## Login Attempts (Last {min(self.max_entries, len(login_entries))})")
            result.append("| Time | User | Source IP | Status | Service |")
            result.append("| --- | --- | --- | --- | --- |")
            for entry in login_entries[:self.max_entries]:
                result.append(f"| {entry.get('timestamp', '')} | {entry.get('user', '')} | {entry.get('source_ip', '')} | {entry.get('status', '')} | {entry.get('service', '')} |")
        
        return "\n".join(result)
    
    def _parse_line(self, line: str) -> dict:
        """Parse a single syslog line."""
        match = SYSLOG_HOST_PROC_RE.match(line)
        if not match:
            return None
        
        hostname, process, pid, message = match.groups()
        timestamp_match = SYSLOG_TS_RE.match(line)
        timestamp = timestamp_match.group(1) if timestamp_match else ''
        
        entry = {
            'timestamp': timestamp,
            'hostname': hostname,
            'process': process,
            'pid': pid,
            'message': message,
            'event_type': 'Other',
            'user': '',
            'source_ip': '',
            'status': '',
            'service': process,
        }
        
        # Detect event type
        if 'sshd' in process:
            ssh_success = SSH_SUCCESS_RE.search(message)
            ssh_failure = SSH_FAILURE_RE.search(message)
            if ssh_success:
                entry['event_type'] = 'SSH Login Success'
                entry['user'] = ssh_success.group(2)
                entry['source_ip'] = ssh_success.group(3)
                entry['status'] = 'SUCCESS'
            elif ssh_failure:
                entry['event_type'] = 'SSH Login Failure'
                entry['user'] = ssh_failure.group(2)
                entry['source_ip'] = ssh_failure.group(3)
                entry['status'] = 'FAILURE'
        elif 'sudo' in process:
            sudo_match = SUDO_RE.search(line)
            if sudo_match:
                entry['event_type'] = 'Sudo Usage'
                entry['user'] = sudo_match.group(1)
                entry['status'] = 'COMMAND'
                entry['message'] = sudo_match.group(6)[:100]
        elif 'su' in process and 'sudo' not in process:
            su_match = SU_RE.search(line)
            if su_match:
                entry['event_type'] = 'Su Usage'
                entry['user'] = su_match.group(2)
                entry['status'] = 'COMMAND'
        elif 'pam_unix' in message:
            if 'session opened' in message:
                entry['event_type'] = 'Session Opened'
            elif 'session closed' in message:
                entry['event_type'] = 'Session Closed'
            elif 'authentication failure' in message:
                entry['event_type'] = 'Auth Failure'
        
        return entry


@register_extractor
class WtmpExtractor(BaseExtractor):
    """Extracts login records from Linux wtmp/utmp/btmp binary files."""
    
    # utmp record structure (384 bytes on Linux x86_64)
    UTMP_SIZE = 384
    UTMP_STRUCT = '<hi32s4s32s256shhiiiiii256s'  # Standard utmp layout
    
    # Record types
    UT_TYPES = {
        0: 'EMPTY',
        1: 'RUN_LVL',
        2: 'BOOT_TIME',
        3: 'NEW_TIME',
        4: 'OLD_TIME',
        5: 'INIT_PROCESS',
        6: 'LOGIN_PROCESS',
        7: 'USER_PROCESS',
        8: 'DEAD_PROCESS',
        9: 'ACCOUNTING',
    }
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                data = f.read()
        except Exception as e:
            logger.error(f"Error reading wtmp file {file_path}: {e}")
            return f"Error: Failed to read wtmp/utmp file: {e}"
        
        if len(data) < self.UTMP_SIZE:
            return f"# Login Records Summary: `{os.path.basename(file_path)}`\n\n*(File too small to contain valid records)*"
        
        # Parse records
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
        
        # Build markdown
        result = [f"# Login Records Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**Total Records:** {len(records):,}")
        
        # Time range
        timestamps = [r['timestamp'] for r in records if r['timestamp']]
        if timestamps:
            result.append(f"**Time Range:** {timestamps[-1]} ~ {timestamps[0]}")
        result.append("")
        
        # Statistics
        result.append("## Login Statistics")
        result.append("| Type | Count |")
        result.append("| --- | --- |")
        for type_name, count in type_counter.most_common():
            result.append(f"| {type_name} | {count:,} |")
        result.append("")
        
        # User login history
        user_logins = [r for r in records if r['type_name'] == 'USER_PROCESS']
        if user_logins:
            result.append(f"## User Login History (Last {min(200, len(user_logins))})")
            result.append("| Time | User | Terminal | Host | PID |")
            result.append("| --- | --- | --- | --- | --- |")
            for record in user_logins[:200]:
                result.append(f"| {record['timestamp']} | {record['user']} | {record['terminal']} | {record['hostname']} | {record['pid']} |")
        
        # System boots
        boots = [r for r in records if r['type_name'] == 'BOOT_TIME']
        if boots:
            result.append("")
            result.append("## System Boots")
            result.append("| Time | Terminal |")
            result.append("| --- | --- |")
            for record in boots[:20]:
                result.append(f"| {record['timestamp']} | {record['terminal']} |")
        
        return "\n".join(result)
    
    def _parse_record(self, data: bytes) -> dict:
        """Parse a single utmp record."""
        try:
            # Unpack key fields
            ut_type = struct.unpack_from('<h', data, 0)[0]
            ut_pid = struct.unpack_from('<i', data, 4)[0]
            ut_user = data[8:40].split(b'\x00')[0].decode('utf-8', errors='replace')
            ut_line = data[40:44].split(b'\x00')[0].decode('utf-8', errors='replace')
            ut_host = data[44:76].split(b'\x00')[0].decode('utf-8', errors='replace')
            
            # Timestamp at offset 280 (tv_sec) and 284 (tv_usec)
            tv_sec = struct.unpack_from('<i', data, 280)[0]
            
            timestamp = ''
            if tv_sec > 0:
                try:
                    timestamp = datetime.fromtimestamp(tv_sec).strftime('%Y-%m-%d %H:%M:%S')
                except:
                    pass
            
            return {
                'type': ut_type,
                'type_name': self.UT_TYPES.get(ut_type, f'UNKNOWN({ut_type})'),
                'pid': ut_pid,
                'user': ut_user,
                'terminal': ut_line,
                'hostname': ut_host,
                'timestamp': timestamp,
            }
        except Exception as e:
            logger.warning(f"Error parsing utmp record: {e}")
            return None


@register_extractor
class JournalExtractor(BaseExtractor):
    """Extracts entries from systemd journal binary files."""
    
    # Journal file magic
    JOURNAL_MAGIC = b'LPKSHHRH'
    
    def __init__(self, sample_size: int = 200):
        self.sample_size = sample_size
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header = f.read(256)
        except Exception as e:
            logger.error(f"Error reading journal file {file_path}: {e}")
            return f"Error: Failed to read journal file: {e}"
        
        if len(header) < 8:
            return "Error: File too small to be a valid journal file."
        
        if header[:8] != self.JOURNAL_MAGIC:
            return f"Error: Not a valid systemd journal file (magic: {header[:8]})"
        
        # Try python-systemd first
        try:
            return self._extract_with_systemd(file_path)
        except ImportError:
            pass
        
        # Fallback: header-only parsing
        return self._parse_header(file_path, header)
    
    def _extract_with_systemd(self, file_path: str) -> str:
        """Extract using python-systemd library."""
        from systemd import journal
        
        result = [f"# Systemd Journal Summary: `{os.path.basename(file_path)}`"]
        
        # Open journal file
        j = journal.Reader()
        j.add_file(file_path)
        
        entries = []
        for entry in j:
            entries.append({
                'timestamp': entry.get('__REALTIME_TIMESTAMP', ''),
                'priority': entry.get('PRIORITY', 6),
                'unit': entry.get('_SYSTEMD_UNIT', entry.get('SYSLOG_IDENTIFIER', '')),
                'message': entry.get('MESSAGE', ''),
            })
            if len(entries) >= self.sample_size:
                break
        
        if not entries:
            result.append("\n*(No entries found)*")
            return "\n".join(result)
        
        # Priority distribution
        priority_counter = Counter(e['priority'] for e in entries)
        priority_names = {0: 'Emergency', 1: 'Alert', 2: 'Critical', 3: 'Error', 4: 'Warning', 5: 'Notice', 6: 'Info', 7: 'Debug'}
        
        result.append(f"**Total Entries:** {len(entries):,}")
        result.append("")
        
        result.append("## Entry Distribution by Priority")
        result.append("| Priority | Count | Description |")
        result.append("| --- | --- | --- |")
        for priority, count in priority_counter.most_common():
            name = priority_names.get(priority, f'Unknown({priority})')
            result.append(f"| {priority} ({name}) | {count:,} | {name} |")
        result.append("")
        
        result.append(f"## Recent Entries (Last {self.sample_size})")
        result.append("| Time | Priority | Unit | Message |")
        result.append("| --- | --- | --- | --- |")
        for entry in entries[:self.sample_size]:
            ts = entry['timestamp']
            if hasattr(ts, 'strftime'):
                ts = ts.strftime('%Y-%m-%d %H:%M:%S')
            msg = str(entry['message']).replace('|', '\\|').replace('\n', ' ')
            if len(msg) > 100:
                msg = msg[:97] + "..."
            unit = entry['unit'].replace('|', '\\|')
            result.append(f"| {ts} | {entry['priority']} | {unit} | {msg} |")
        
        return "\n".join(result)
    
    def _parse_header(self, file_path: str, header: bytes) -> str:
        """Parse journal header for basic metadata."""
        import uuid
        
        result = [f"# Systemd Journal Summary: `{os.path.basename(file_path)}`"]
        
        # Parse file ID (UUID) at offset 8
        file_id = uuid.UUID(bytes=header[8:24])
        result.append(f"**File ID:** {file_id}")
        
        # Machine ID at offset 24
        machine_id = uuid.UUID(bytes=header[24:40])
        result.append(f"**Machine ID:** {machine_id}")
        
        # Boot ID at offset 40
        boot_id = uuid.UUID(bytes=header[40:56])
        result.append(f"**Boot ID:** {boot_id}")
        
        # File size
        file_size = os.path.getsize(file_path)
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
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/linux_journal.py
git commit -m "feat: add AuthLogExtractor, WtmpExtractor, and JournalExtractor"
```

---

## Task 12: AndroidBackupExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/android_backup.py`

- [ ] **Step 1: Write Android backup extractor**

Create `python_service/httpserver/services/extractors/android_backup.py`:

```python
"""Android backup file (.ab) forensic extractor."""
import logging
import os
import struct
import tarfile
import zlib
from io import BytesIO

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# Important Android database patterns
ANDROID_ARTIFACTS = {
    'contacts2.db': 'Contacts Database',
    'mmssms.db': 'SMS/MMS Database',
    'calllog.db': 'Call Log Database',
    'accounts.db': 'Accounts Database',
    'settings.db': 'Settings Database',
    'wifi': 'WiFi Configuration',
    'bluetooth': 'Bluetooth Configuration',
}


def _format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / 1024 / 1024:.2f} MB"


@register_extractor
class AndroidBackupExtractor(BaseExtractor):
    """Extracts content from Android backup (.ab) files."""
    
    # Android backup magic
    AB_MAGIC = b'ANDROID BACKUP\n'
    
    def __init__(self, max_files: int = 100):
        self.max_files = max_files
    
    async def extract_to_markdown(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                header_data = f.read(1024)
        except Exception as e:
            logger.error(f"Error reading Android backup {file_path}: {e}")
            return f"Error: Failed to read Android backup file: {e}"
        
        # Check magic
        if not header_data.startswith(self.AB_MAGIC):
            return "Error: Not a valid Android backup file (missing ANDROID BACKUP magic)"
        
        # Parse header
        header_text = header_data.split(b'\n', 5)
        if len(header_text) < 5:
            return "Error: Incomplete Android backup header"
        
        try:
            version = header_text[1].decode('utf-8').strip().split(':')[1].strip()
            compression = header_text[2].decode('utf-8').strip().split(':')[1].strip()
            encryption = header_text[3].decode('utf-8').strip().split(':')[1].strip()
        except Exception as e:
            logger.warning(f"Error parsing backup header: {e}")
            version = "Unknown"
            compression = "Unknown"
            encryption = "Unknown"
        
        result = [f"# Android Backup Summary: `{os.path.basename(file_path)}`"]
        result.append(f"**Version:** {version}")
        result.append(f"**Compression:** {compression}")
        result.append(f"**Encryption:** {encryption}")
        result.append("")
        
        # If encrypted, we can't extract content
        if encryption.lower() != 'none':
            result.append("## ⚠️ Encrypted Backup")
            result.append("This backup is encrypted. Content cannot be extracted without the decryption key.")
            result.append("")
            result.append("## Basic Information")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            result.append(f"| Version | {version} |")
            result.append(f"| Compression | {compression} |")
            result.append(f"| Encryption | {encryption} |")
            result.append(f"| File Size | {os.path.getsize(file_path):,} bytes |")
            return "\n".join(result)
        
        # Try to decompress and parse tar
        try:
            return self._parse_uncompressed(file_path, header_data, result)
        except Exception as e:
            logger.error(f"Error parsing Android backup {file_path}: {e}")
            return f"Error: Failed to parse Android backup: {e}"
    
    def _parse_uncompressed(self, file_path: str, header_data: bytes, result: list) -> str:
        """Parse uncompressed Android backup (tar inside)."""
        # Find the start of the tar data (after the header)
        # The header ends with a double newline or the base64-encoded data starts
        with open(file_path, 'rb') as f:
            content = f.read()
        
        # Find where the tar data starts (after the header section)
        # Android backup format: header text + base64-encoded zlib-compressed tar
        header_end = content.find(b'\n\n')
        if header_end == -1:
            header_end = content.find(b'\n', content.find(b'\n') + 1)
        
        if header_end == -1:
            return "Error: Could not find end of backup header"
        
        # The rest is base64-encoded zlib-compressed tar data
        import base64
        try:
            b64_data = content[header_end:].strip()
            compressed_data = base64.b64decode(b64_data)
            tar_data = zlib.decompress(compressed_data)
        except Exception as e:
            # Try raw tar (some backups are not compressed)
            try:
                tar_data = content[header_end:].strip()
            except:
                return f"Error: Failed to decompress backup data: {e}"
        
        # Parse tar archive
        try:
            tar_file = BytesIO(tar_data)
            with tarfile.open(fileobj=tar_file, mode='r') as tar:
                members = tar.getmembers()
                
                result.append(f"**Total Files:** {len(members)}")
                result.append("")
                
                # Find important artifacts
                artifacts = []
                for member in members:
                    if member.isfile():
                        for pattern, description in ANDROID_ARTIFACTS.items():
                            if pattern in member.name.lower():
                                artifacts.append((member.name, member.size, description))
                
                if artifacts:
                    result.append("## Important Android Artifacts")
                    result.append("| Path | Size | Type |")
                    result.append("| --- | --- | --- |")
                    for path, size, desc in artifacts[:50]:
                        result.append(f"| {path} | {_format_size(size)} | {desc} |")
                    result.append("")
                
                # File listing
                result.append(f"## File Listing (First {self.max_files})")
                result.append("| Path | Size |")
                result.append("| --- | --- |")
                for member in members[:self.max_files]:
                    if member.isfile():
                        result.append(f"| {member.name} | {_format_size(member.size)} |")
                
                if len(members) > self.max_files:
                    result.append(f"\n*(Showing {self.max_files} of {len(members)} files)*")
                
                return "\n".join(result)
        except Exception as e:
            logger.error(f"Error parsing tar in Android backup: {e}")
            return f"Error: Failed to parse tar archive in backup: {e}"
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/android_backup.py
git commit -m "feat: add AndroidBackupExtractor for .ab backup files"
```

---

## Task 13: E01MetadataExtractor

**Files:**
- Create: `python_service/httpserver/services/extractors/disk_image.py`

- [ ] **Step 1: Write E01 metadata extractor**

Create `python_service/httpserver/services/extractors/disk_image.py`:

```python
"""Forensic disk image metadata extractors: E01 (EnCase Evidence File)."""
import logging
import os
import struct

from .base import BaseExtractor, register_extractor

logger = logging.getLogger(__name__)

# E01 file signatures
EVF_SIGNATURE = b'\x45\x56\x46\x09\x0d\x0a\xff\x00'  # EVF signature (E01)


@register_extractor
class E01MetadataExtractor(BaseExtractor):
    """Extracts metadata from E01 (EnCase Evidence File) forensic images."""
    
    async def extract_to_markdown(self, file_path: str) -> str:
        # Try pyewf first for full metadata
        pyewf_result = self._try_pyewf(file_path)
        if pyewf_result:
            return pyewf_result
        
        # Fallback: header-only parsing
        return self._parse_header(file_path)
    
    def _try_pyewf(self, file_path: str) -> str:
        """Try using pyewf for full metadata extraction."""
        try:
            import pyewf
        except ImportError:
            return ""
        
        try:
            ewf_handle = pyewf.open(file_path)
            
            result = [f"# E01 Forensic Image Metadata: `{os.path.basename(file_path)}`"]
            
            # Get header values
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
                result.append(f"| Time | {header_values.get('acquisition_time', 'N/A')} |")
                result.append(f"| Platform | {header_values.get('platform', 'N/A')} |")
                result.append(f"| Compression | {header_values.get('compression_type', 'N/A')} |")
                result.append("")
            
            # Get segment information
            result.append("## Image Statistics")
            result.append("| Field | Value |")
            result.append("| --- | --- |")
            
            media_size = ewf_handle.get_media_size()
            result.append(f"| Media Size | {media_size / 1024 / 1024 / 1024:.2f} GB |")
            
            segment_count = ewf_handle.get_segment_count() if hasattr(ewf_handle, 'get_segment_count') else 'N/A'
            result.append(f"| Segments | {segment_count} |")
            
            result.append(f"| File Size | {os.path.getsize(file_path):,} bytes |")
            
            # Get hash values if available
            hash_values = ewf_handle.get_hash_values() if hasattr(ewf_handle, 'get_hash_values') else None
            if hash_values:
                result.append("")
                result.append("## Integrity Hashes")
                result.append("| Algorithm | Hash |")
                result.append("| --- | --- |")
                for hash_name, hash_value in hash_values.items():
                    result.append(f"| {hash_name} | {hash_value} |")
            
            ewf_handle.close()
            return "\n".join(result)
            
        except Exception as e:
            logger.warning(f"pyewf failed for {file_path}: {e}")
            return ""
    
    def _parse_header(self, file_path: str) -> str:
        """Parse E01 header for basic metadata without pyewf."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)
        except Exception as e:
            logger.error(f"Error reading E01 file {file_path}: {e}")
            return f"Error: Failed to read E01 file: {e}"
        
        if len(header) < 8:
            return "Error: File too small to be a valid E01 file."
        
        # Check signature
        if header[:8] != EVF_SIGNATURE:
            return f"Error: Not a valid E01 file (signature: {header[:8].hex()})"
        
        result = [f"# E01 Forensic Image Metadata: `{os.path.basename(file_path)}`"]
        result.append("**Format:** E01 (EnCase Evidence File)")
        result.append("")
        
        # Parse header section
        # E01 header section starts at offset 13
        try:
            # Read header fields section
            fields_offset = struct.unpack_from('<I', header, 13)[0]
            fields_size = struct.unpack_from('<I', header, 17)[0]
            
            # Read more of the file to get header fields
            with open(file_path, 'rb') as f:
                f.seek(fields_offset)
                fields_data = f.read(min(fields_size, 4096))
            
            # Parse header fields (key=value pairs)
            fields = {}
            try:
                fields_text = fields_data.decode('utf-8', errors='replace')
                for line in fields_text.split('\n'):
                    if '=' in line:
                        key, _, value = line.partition('=')
                        fields[key.strip()] = value.strip()
            except:
                pass
            
            if fields:
                result.append("## Case Information")
                result.append("| Field | Value |")
                result.append("| --- | --- |")
                for key in ['case_number', 'evidence_number', 'examiner_name', 'description', 'acquisition_date', 'acquisition_time', 'platform']:
                    value = fields.get(key, 'N/A')
                    if value:
                        result.append(f"| {key.replace('_', ' ').title()} | {value} |")
                result.append("")
        except Exception as e:
            logger.warning(f"Error parsing E01 header fields: {e}")
        
        # Basic file information
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
```

- [ ] **Step 2: Commit**

```bash
git add python_service/httpserver/services/extractors/disk_image.py
git commit -m "feat: add E01MetadataExtractor for EnCase forensic images"
```

---

## Task 14: Update extractor_mapping.json

**Files:**
- Modify: `python_service/config/extractor_mapping.json`

- [ ] **Step 1: Update extractor_mapping.json**

Replace the contents of `python_service/config/extractor_mapping.json` with:

```json
{
    "MarkitdownExtractor": {
        "extensions": [
            ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
            ".html", ".htm", ".csv", ".json", ".xml", ".epub", ".ipynb",
            ".rss", ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
            ".tiff", ".tif", ".mp3", ".wav"
        ],
        "fallback": {
            ".pdf": "PDFExtractor",
            ".docx": "DocxExtractor",
            ".doc": "DocExtractorProxy",
            ".xlsx": "OfficeServiceAdapter",
            ".xls": "OfficeServiceAdapter",
            ".pptx": "OfficeServiceAdapter",
            ".ppt": "OfficeServiceAdapter"
        }
    },
    "PDFExtractor": [".pdf"],
    "DocxExtractor": [".docx"],
    "OfficeServiceAdapter": [".xlsx", ".xls", ".pptx", ".ppt"],
    "DocExtractorProxy": [".doc"],
    "SQLiteExtractor": [".db", ".sqlite", ".sqlite3"],
    "SqlDumpExtractor": [".sql"],
    "LevelDBExtractor": ["leveldb"],
    "RedisExtractor": [".rdb"],
    "MongoBsonExtractor": [".bson"],
    "ArchiveExtractor": [".zip", ".tar", ".gz", ".tgz", ".rar", ".7z"],
    "EmlExtractor": [".eml"],
    "MsgExtractor": [".msg"],
    "MboxExtractor": [".mbox"],
    "PstExtractor": [".pst", ".ost"],
    "EvtxExtractor": [".evtx"],
    "RegistryExtractor": [".reg", ".hiv"],
    "LnkExtractor": [".lnk"],
    "JumplistExtractor": [".automaticDestinations-ms", ".customDestinations-ms"],
    "JournalExtractor": [".journal"],
    "AndroidBackupExtractor": [".ab"],
    "E01MetadataExtractor": [".e01"],
    "_filename_routes": {
        "auth.log": "AuthLogExtractor",
        "auth.log.1": "AuthLogExtractor",
        "wtmp": "WtmpExtractor",
        "utmp": "WtmpExtractor",
        "btmp": "WtmpExtractor",
        "History": "ChromeHistoryExtractor",
        "places.sqlite": "FirefoxHistoryExtractor",
        "SAM": "RegistryExtractor",
        "SYSTEM": "RegistryExtractor",
        "SOFTWARE": "RegistryExtractor",
        "SECURITY": "RegistryExtractor",
        "DEFAULT": "RegistryExtractor",
        "NTUSER.DAT": "RegistryExtractor",
        "UsrClass.dat": "RegistryExtractor"
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add python_service/config/extractor_mapping.json
git commit -m "feat: register all forensic extractors in mapping config"
```

---

## Task 15: Integration Tests and Verification

**Files:**
- Modify: `python_service/tests/unit/test_forensic_extractors.py`

- [ ] **Step 1: Add integration tests for all extractors**

Append to `python_service/tests/unit/test_forensic_extractors.py`:

```python
@pytest.mark.asyncio
async def test_all_extractors_import():
    """Test that all forensic extractors can be imported."""
    from httpserver.services.extractors.email import EmlExtractor, MsgExtractor, MboxExtractor, PstExtractor
    from httpserver.services.extractors.windows_evtx import EvtxExtractor
    from httpserver.services.extractors.windows_registry import RegistryExtractor
    from httpserver.services.extractors.windows_lnk import LnkExtractor, JumplistExtractor
    from httpserver.services.extractors.browser_history import ChromeHistoryExtractor, FirefoxHistoryExtractor
    from httpserver.services.extractors.linux_journal import AuthLogExtractor, WtmpExtractor, JournalExtractor
    from httpserver.services.extractors.android_backup import AndroidBackupExtractor
    from httpserver.services.extractors.disk_image import E01MetadataExtractor
    
    # Verify all classes exist and are BaseExtractor subclasses
    from httpserver.services.extractors.base import BaseExtractor
    
    for cls in [EmlExtractor, MsgExtractor, MboxExtractor, PstExtractor,
                EvtxExtractor, RegistryExtractor, LnkExtractor, JumplistExtractor,
                ChromeHistoryExtractor, FirefoxHistoryExtractor,
                AuthLogExtractor, WtmpExtractor, JournalExtractor,
                AndroidBackupExtractor, E01MetadataExtractor]:
        assert issubclass(cls, BaseExtractor), f"{cls.__name__} is not a BaseExtractor subclass"


@pytest.mark.asyncio
async def test_extractor_registry():
    """Test that extractors are properly registered."""
    from httpserver.services.extractors import get_extractor, get_extractor_by_filename
    
    # Test extension-based routing
    assert get_extractor('.eml') is not None
    assert get_extractor('.msg') is not None
    assert get_extractor('.evtx') is not None
    assert get_extractor('.lnk') is not None
    
    # Test filename-based routing
    assert get_extractor_by_filename('auth.log') is not None
    assert get_extractor_by_filename('wtmp') is not None
    assert get_extractor_by_filename('SAM') is not None


@pytest.mark.asyncio
async def test_auth_log_extractor():
    """Test AuthLogExtractor with sample log data."""
    import tempfile
    
    log_content = """Jan 15 10:30:00 server sshd[1234]: Accepted publickey for john from 192.168.1.100 port 22 ssh2
Jan 15 10:31:00 server sshd[1235]: Failed password for admin from 10.0.0.50 port 22 ssh2
Jan 15 10:32:00 server sudo: john : TTY=pts/0 ; PWD=/home/john ; USER=root ; COMMAND=/bin/ls
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False) as f:
        f.write(log_content)
        tmp_path = f.name
    
    try:
        from httpserver.services.extractors.linux_journal import AuthLogExtractor
        extractor = AuthLogExtractor()
        result = await extractor.extract_to_markdown(tmp_path)
        
        assert '# Authentication Log Summary' in result
        assert 'john' in result
        assert 'SSH Login Success' in result or 'SUCCESS' in result
    finally:
        os.unlink(tmp_path)
```

- [ ] **Step 2: Run all tests**

Run: `cd /home/ymj68520/projects/Forensics/ForensicsProject/python_service && python -m pytest tests/unit/test_forensic_extractors.py -v`

Expected: All tests PASS

- [ ] **Step 3: Final commit**

```bash
git add python_service/tests/unit/test_forensic_extractors.py
git commit -m "test: add integration tests for forensic extractors"
```

---

## Summary

| Task | Description | Files Created | Files Modified |
|------|-------------|---------------|----------------|
| 1 | Update dependencies | - | requirements.txt |
| 2 | Extend routing mechanism | - | __init__.py, document_extractor.py |
| 3 | EmlExtractor | email.py | test_forensic_extractors.py |
| 4 | MsgExtractor | - | email.py, test_forensic_extractors.py |
| 5 | MboxExtractor | - | email.py, test_forensic_extractors.py |
| 6 | PstExtractor | - | email.py |
| 7 | EvtxExtractor | windows_evtx.py | test_forensic_extractors.py |
| 8 | RegistryExtractor | windows_registry.py | - |
| 9 | LnkExtractor + JumplistExtractor | windows_lnk.py | - |
| 10 | Chrome + Firefox History | browser_history.py | - |
| 11 | AuthLog + Wtmp + Journal | linux_journal.py | - |
| 12 | AndroidBackupExtractor | android_backup.py | - |
| 13 | E01MetadataExtractor | disk_image.py | - |
| 14 | Update mapping | - | extractor_mapping.json |
| 15 | Integration tests | - | test_forensic_extractors.py |
