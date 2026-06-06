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

    attachment = MIMEBase('application', 'pdf')
    attachment.set_payload(b'fake pdf content')
    encoders.encode_base64(attachment)
    attachment.add_header('Content-Disposition', 'attachment', filename='document.pdf')
    msg.attach(attachment)

    with tempfile.NamedTemporaryFile(suffix='.eml', delete=False, mode='w') as f:
        f.write(msg.as_string())
        return f.name


@pytest.fixture
def sample_mbox_file():
    """Create a sample MBOX file for testing."""
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


@pytest.mark.asyncio
async def test_msg_extractor_nonexistent_file():
    """Test MSG extractor handles missing files gracefully."""
    from httpserver.services.extractors.email import MsgExtractor

    extractor = MsgExtractor()
    result = await extractor.extract_to_markdown('/nonexistent/file.msg')

    assert 'Error' in result


@pytest.mark.asyncio
async def test_pst_extractor_nonexistent_file():
    """Test PST extractor handles missing files gracefully."""
    from httpserver.services.extractors.email import PstExtractor

    extractor = PstExtractor()
    result = await extractor.extract_to_markdown('/nonexistent/file.pst')

    assert 'Error' in result


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

    assert get_extractor('.eml') is not None
    assert get_extractor('.msg') is not None
    assert get_extractor('.evtx') is not None
    assert get_extractor('.lnk') is not None

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
