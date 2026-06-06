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
