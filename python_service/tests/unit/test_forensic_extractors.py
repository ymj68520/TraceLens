"""Unit tests for forensic file type extractors."""
import asyncio
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


# ===========================================================================
# Task 12: Unit tests for 15 new extractors
# ===========================================================================


# ---------------------------------------------------------------------------
# CsvExtractor (data_exchange.py)
# ---------------------------------------------------------------------------

class TestCsvExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.data_exchange import CsvExtractor
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.csv')
        )
        assert 'Error' in result

    def test_basic_csv(self, tmp_path):
        from httpserver.services.extractors.data_exchange import CsvExtractor
        csv_file = tmp_path / "test.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n", encoding='utf-8')
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(csv_file))
        )
        assert 'CSV Data' in result
        assert 'name' in result
        assert 'age' in result
        assert 'Alice' in result

    def test_csv_numeric_stats(self, tmp_path):
        from httpserver.services.extractors.data_exchange import CsvExtractor
        csv_file = tmp_path / "nums.csv"
        csv_file.write_text("id,score\n1,90\n2,85\n3,95\n", encoding='utf-8')
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(csv_file))
        )
        assert 'Numeric Column Statistics' in result

    def test_csv_empty_file(self, tmp_path):
        from httpserver.services.extractors.data_exchange import CsvExtractor
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("", encoding='utf-8')
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(csv_file))
        )
        assert 'Error' in result

    def test_csv_tab_delimited(self, tmp_path):
        from httpserver.services.extractors.data_exchange import CsvExtractor
        csv_file = tmp_path / "tab.csv"
        csv_file.write_text("name\tage\nAlice\t30\n", encoding='utf-8')
        extractor = CsvExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(csv_file))
        )
        assert 'CSV Data' in result
        assert 'Alice' in result


# ---------------------------------------------------------------------------
# JsonDataExtractor (data_exchange.py)
# ---------------------------------------------------------------------------

class TestJsonDataExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.data_exchange import JsonDataExtractor
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.json')
        )
        assert 'Error' in result

    def test_basic_json_object(self, tmp_path):
        from httpserver.services.extractors.data_exchange import JsonDataExtractor
        json_file = tmp_path / "test.json"
        json_file.write_text('{"name": "Alice", "age": 30}', encoding='utf-8')
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(json_file))
        )
        assert 'JSON Data' in result
        assert 'name' in result
        assert 'Alice' in result

    def test_json_array(self, tmp_path):
        from httpserver.services.extractors.data_exchange import JsonDataExtractor
        json_file = tmp_path / "array.json"
        json_file.write_text('[{"id": 1}, {"id": 2}]', encoding='utf-8')
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(json_file))
        )
        assert 'JSON Data' in result
        assert 'Array' in result

    def test_json_invalid(self, tmp_path):
        from httpserver.services.extractors.data_exchange import JsonDataExtractor
        json_file = tmp_path / "bad.json"
        json_file.write_text('{not valid json', encoding='utf-8')
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(json_file))
        )
        assert 'Error' in result

    def test_jsonl(self, tmp_path):
        from httpserver.services.extractors.data_exchange import JsonDataExtractor
        jsonl_file = tmp_path / "test.jsonl"
        jsonl_file.write_text('{"a": 1}\n{"a": 2}\n', encoding='utf-8')
        extractor = JsonDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(jsonl_file))
        )
        assert 'JSON Lines' in result
        assert 'Records' in result


# ---------------------------------------------------------------------------
# XmlDataExtractor (data_exchange.py)
# ---------------------------------------------------------------------------

class TestXmlDataExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.data_exchange import XmlDataExtractor
        extractor = XmlDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.xml')
        )
        assert 'Error' in result

    def test_basic_xml(self, tmp_path):
        from httpserver.services.extractors.data_exchange import XmlDataExtractor
        xml_file = tmp_path / "test.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><root><item>Hello</item><item>World</item></root>',
            encoding='utf-8'
        )
        extractor = XmlDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(xml_file))
        )
        assert 'XML Document' in result
        assert 'root' in result
        assert 'item' in result

    def test_xml_invalid(self, tmp_path):
        from httpserver.services.extractors.data_exchange import XmlDataExtractor
        xml_file = tmp_path / "bad.xml"
        xml_file.write_text('<root><unclosed>', encoding='utf-8')
        extractor = XmlDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(xml_file))
        )
        assert 'Error' in result

    def test_xml_with_attributes(self, tmp_path):
        from httpserver.services.extractors.data_exchange import XmlDataExtractor
        xml_file = tmp_path / "attrs.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><root version="1.0"><child key="val">text</child></root>',
            encoding='utf-8'
        )
        extractor = XmlDataExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(xml_file))
        )
        assert 'XML Document' in result
        assert 'Root Attributes' in result


# ---------------------------------------------------------------------------
# UrlExtractor (microsoft_extended.py)
# ---------------------------------------------------------------------------

class TestUrlExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import UrlExtractor
        extractor = UrlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.url')
        )
        assert 'Error' in result

    def test_basic_url(self, tmp_path):
        from httpserver.services.extractors.microsoft_extended import UrlExtractor
        url_file = tmp_path / "test.url"
        url_file.write_text(
            "[InternetShortcut]\nURL=https://www.example.com\n",
            encoding='utf-8'
        )
        extractor = UrlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(url_file))
        )
        assert 'Internet Shortcut' in result
        assert 'https://www.example.com' in result

    def test_url_with_extra_fields(self, tmp_path):
        from httpserver.services.extractors.microsoft_extended import UrlExtractor
        url_file = tmp_path / "full.url"
        url_file.write_text(
            "[InternetShortcut]\nURL=https://example.com\nIconFile=icon.ico\nIconIndex=0\nHotKey=0\n",
            encoding='utf-8'
        )
        extractor = UrlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(url_file))
        )
        assert 'Internet Shortcut' in result
        assert 'example.com' in result
        assert 'IconFile' in result


# ---------------------------------------------------------------------------
# MscExtractor (microsoft_extended.py)
# ---------------------------------------------------------------------------

class TestMscExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import MscExtractor
        extractor = MscExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.msc')
        )
        assert 'Error' in result

    def test_basic_msc(self, tmp_path):
        from httpserver.services.extractors.microsoft_extended import MscExtractor
        msc_file = tmp_path / "test.msc"
        msc_file.write_text(
            '<?xml version="1.0"?><MMC_ConsoleFile ProgramMode="Author"><VisualAttributes/></MMC_ConsoleFile>',
            encoding='utf-8'
        )
        extractor = MscExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(msc_file))
        )
        assert 'MMC Console' in result
        assert 'Author' in result


# ---------------------------------------------------------------------------
# XpsExtractor (microsoft_extended.py) - ZIP-based, nonexistent only
# ---------------------------------------------------------------------------

class TestXpsExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import XpsExtractor
        extractor = XpsExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.xps')
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# OneNoteExtractor (microsoft_extended.py)
# ---------------------------------------------------------------------------

class TestOneNoteExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import OneNoteExtractor
        extractor = OneNoteExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.one')
        )
        assert 'Error' in result

    def test_nonexistent_onetoc2(self):
        from httpserver.services.extractors.microsoft_extended import OneNoteExtractor
        extractor = OneNoteExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.onetoc2')
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# VisioExtractor (microsoft_extended.py) - ZIP-based, nonexistent only
# ---------------------------------------------------------------------------

class TestVisioExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import VisioExtractor
        extractor = VisioExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.vsdx')
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# ProjectExtractor (microsoft_extended.py)
# ---------------------------------------------------------------------------

class TestProjectExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import ProjectExtractor
        extractor = ProjectExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.mpp')
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# EtlExtractor (microsoft_extended.py)
# ---------------------------------------------------------------------------

class TestEtlExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.microsoft_extended import EtlExtractor
        extractor = EtlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.etl')
        )
        assert 'Error' in result

    def test_too_small_file(self, tmp_path):
        from httpserver.services.extractors.microsoft_extended import EtlExtractor
        etl_file = tmp_path / "tiny.etl"
        etl_file.write_bytes(b'\x00' * 10)
        extractor = EtlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(etl_file))
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# PsdExtractor (adobe_formats.py)
# ---------------------------------------------------------------------------

class TestPsdExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.adobe_formats import PsdExtractor
        extractor = PsdExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.psd')
        )
        assert 'Error' in result

    def test_invalid_magic(self, tmp_path):
        from httpserver.services.extractors.adobe_formats import PsdExtractor
        psd_file = tmp_path / "bad.psd"
        # Write valid-looking header size but wrong magic
        psd_file.write_bytes(b'\x00' * 40)
        extractor = PsdExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(psd_file))
        )
        assert 'Error' in result

    def test_basic_psd_header(self, tmp_path):
        from httpserver.services.extractors.adobe_formats import PsdExtractor
        import struct as st
        psd_file = tmp_path / "test.psd"
        # Build minimal PSD: magic(4) + version(2) + reserved(6) + channels(2) + height(4) + width(4) + depth(2) + colormode(2) + color_data_len(4)
        header = b'8BPS'                     # magic
        header += st.pack('>H', 1)           # version
        header += b'\x00' * 6                # reserved
        header += st.pack('>H', 3)           # channels
        header += st.pack('>I', 100)         # height
        header += st.pack('>I', 200)         # width
        header += st.pack('>H', 8)           # depth
        header += st.pack('>H', 3)           # color mode (RGB)
        header += st.pack('>I', 0)           # color mode data length
        header += st.pack('>I', 0)           # image resources length
        header += st.pack('>I', 0)           # layer/mask info length
        psd_file.write_bytes(header)
        extractor = PsdExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(psd_file))
        )
        assert 'PSD Image' in result
        assert '200 x 100' in result


# ---------------------------------------------------------------------------
# AiExtractor (adobe_formats.py)
# ---------------------------------------------------------------------------

class TestAiExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.adobe_formats import AiExtractor
        extractor = AiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.ai')
        )
        assert 'Error' in result

    def test_eps_based_ai(self, tmp_path):
        from httpserver.services.extractors.adobe_formats import AiExtractor
        ai_file = tmp_path / "test.ai"
        ai_file.write_text(
            "%!PS-Adobe-3.0\n%%Title: Test AI\n%%Creator: TestApp\n%%EndComments\n",
            encoding='latin-1'
        )
        extractor = AiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(ai_file))
        )
        assert 'Adobe Illustrator' in result
        assert 'EPS-based' in result

    def test_unknown_format(self, tmp_path):
        from httpserver.services.extractors.adobe_formats import AiExtractor
        ai_file = tmp_path / "unknown.ai"
        ai_file.write_bytes(b'\x00\x01\x02\x03' * 20)
        extractor = AiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(ai_file))
        )
        assert 'Adobe Illustrator' in result
        assert 'Unknown' in result


# ---------------------------------------------------------------------------
# InddExtractor (adobe_formats.py)
# ---------------------------------------------------------------------------

class TestInddExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.adobe_formats import InddExtractor
        extractor = InddExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.indd')
        )
        assert 'Error' in result

    def test_raw_binary_fallback(self, tmp_path):
        from httpserver.services.extractors.adobe_formats import InddExtractor
        indd_file = tmp_path / "test.indd"
        indd_file.write_bytes(b'\x00' * 256)
        extractor = InddExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(indd_file))
        )
        assert 'Adobe InDesign' in result


# ---------------------------------------------------------------------------
# SrtExtractor (ebook_science.py)
# ---------------------------------------------------------------------------

class TestSrtExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import SrtExtractor
        extractor = SrtExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.srt')
        )
        assert 'Error' in result

    def test_basic_srt(self, tmp_path):
        from httpserver.services.extractors.ebook_science import SrtExtractor
        srt_file = tmp_path / "test.srt"
        srt_content = (
            "1\n00:00:01,000 --> 00:00:04,000\nHello World\n\n"
            "2\n00:00:05,000 --> 00:00:08,000\nSecond subtitle\n\n"
        )
        srt_file.write_text(srt_content, encoding='utf-8')
        extractor = SrtExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(srt_file))
        )
        assert 'SRT Subtitles' in result
        assert 'Hello World' in result
        assert '00:00:01,000' in result
        assert 'Total Entries' in result

    def test_srt_empty(self, tmp_path):
        from httpserver.services.extractors.ebook_science import SrtExtractor
        srt_file = tmp_path / "empty.srt"
        srt_file.write_text("no subtitles here\n", encoding='utf-8')
        extractor = SrtExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(srt_file))
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# AssVttExtractor (ebook_science.py)
# ---------------------------------------------------------------------------

class TestAssVttExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import AssVttExtractor
        extractor = AssVttExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.ass')
        )
        assert 'Error' in result

    def test_vtt_basic(self, tmp_path):
        from httpserver.services.extractors.ebook_science import AssVttExtractor
        vtt_file = tmp_path / "test.vtt"
        vtt_content = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:04.000\nHello World\n\n"
            "00:00:05.000 --> 00:00:08.000\nSecond cue\n\n"
        )
        vtt_file.write_text(vtt_content, encoding='utf-8')
        extractor = AssVttExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(vtt_file))
        )
        assert 'WebVTT' in result
        assert 'Hello World' in result
        assert 'WEBVTT' in result

    def test_ass_basic(self, tmp_path):
        from httpserver.services.extractors.ebook_science import AssVttExtractor
        ass_file = tmp_path / "test.ass"
        ass_content = (
            "[Script Info]\nTitle: Test Script\nScriptType: v4.00+\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname\nStyle: Default,Arial\n\n"
            "[Events]\nFormat: Layer,Start,End,Style,Text\n"
            "Dialogue: 0,0:00:01.00,0:00:04.00,Default,Hello\n"
            "Dialogue: 0,0:00:05.00,0:00:08.00,Default,World\n"
        )
        ass_file.write_text(ass_content, encoding='utf-8')
        extractor = AssVttExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(ass_file))
        )
        assert 'ASS/SSA Subtitles' in result
        assert 'Test Script' in result
        assert 'Events' in result


# ---------------------------------------------------------------------------
# ObjExtractor (ebook_science.py)
# ---------------------------------------------------------------------------

class TestObjExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import ObjExtractor
        extractor = ObjExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.obj')
        )
        assert 'Error' in result

    def test_basic_obj(self, tmp_path):
        from httpserver.services.extractors.ebook_science import ObjExtractor
        obj_file = tmp_path / "test.obj"
        obj_content = (
            "# Simple cube\n"
            "v 0.0 0.0 0.0\n"
            "v 1.0 0.0 0.0\n"
            "v 1.0 1.0 0.0\n"
            "v 0.0 1.0 0.0\n"
            "vn 0.0 0.0 1.0\n"
            "f 1 2 3\n"
            "f 1 3 4\n"
        )
        obj_file.write_text(obj_content, encoding='utf-8')
        extractor = ObjExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(obj_file))
        )
        assert 'OBJ 3D Model' in result
        assert 'Vertices' in result
        assert 'Faces' in result
        assert 'Bounding Box' in result


# ---------------------------------------------------------------------------
# StlExtractor (ebook_science.py)
# ---------------------------------------------------------------------------

class TestStlExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import StlExtractor
        extractor = StlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.stl')
        )
        assert 'Error' in result

    def test_ascii_stl(self, tmp_path):
        from httpserver.services.extractors.ebook_science import StlExtractor
        stl_file = tmp_path / "test.stl"
        stl_content = (
            "solid test\n"
            "  facet normal 0 0 1\n"
            "    outer loop\n"
            "      vertex 0 0 0\n"
            "      vertex 1 0 0\n"
            "      vertex 0 1 0\n"
            "    endloop\n"
            "  endfacet\n"
            "endsolid test\n"
        )
        stl_file.write_text(stl_content, encoding='utf-8')
        extractor = StlExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(stl_file))
        )
        assert 'STL 3D Model' in result
        assert 'ASCII STL' in result
        assert 'Triangles' in result


# ---------------------------------------------------------------------------
# EpubExtractor (ebook_science.py) - ZIP-based, nonexistent only
# ---------------------------------------------------------------------------

class TestEpubExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import EpubExtractor
        extractor = EpubExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.epub')
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# MobiExtractor (ebook_science.py) - binary, nonexistent only
# ---------------------------------------------------------------------------

class TestMobiExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import MobiExtractor
        extractor = MobiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.mobi')
        )
        assert 'Error' in result

    def test_too_small(self, tmp_path):
        from httpserver.services.extractors.ebook_science import MobiExtractor
        mobi_file = tmp_path / "tiny.mobi"
        mobi_file.write_bytes(b'\x00\x01')
        extractor = MobiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(mobi_file))
        )
        assert 'Error' in result

    def test_no_mobi_magic(self, tmp_path):
        from httpserver.services.extractors.ebook_science import MobiExtractor
        mobi_file = tmp_path / "bad.mobi"
        mobi_file.write_bytes(b'\x00' * 200)
        extractor = MobiExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown(str(mobi_file))
        )
        assert 'Error' in result


# ---------------------------------------------------------------------------
# Hdf5Extractor (ebook_science.py) - needs h5py, nonexistent only
# ---------------------------------------------------------------------------

class TestHdf5Extractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import Hdf5Extractor
        extractor = Hdf5Extractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.h5')
        )
        # Either h5py is missing (returns "Error: h5py...") or file not found
        assert 'Error' in result


# ---------------------------------------------------------------------------
# DicomExtractor (ebook_science.py) - needs pydicom, nonexistent only
# ---------------------------------------------------------------------------

class TestDicomExtractor:
    def test_nonexistent_file(self):
        from httpserver.services.extractors.ebook_science import DicomExtractor
        extractor = DicomExtractor()
        result = asyncio.get_event_loop().run_until_complete(
            extractor.extract_to_markdown('/nonexistent/file.dcm')
        )
        # Either pydicom is missing (returns "Error: pydicom...") or file not found
        assert 'Error' in result
