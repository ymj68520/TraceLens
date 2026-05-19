"""Unit tests for DLLMarkdownGenerator."""

import pytest

from httpserver.services.dll.dll_markdown_generator import DLLMarkdownGenerator


@pytest.fixture
def generator():
    """Create a DLLMarkdownGenerator instance."""
    return DLLMarkdownGenerator()


@pytest.fixture
def minimal_analysis_result():
    """Minimal valid DLL analysis result."""
    return {
        "file_name": "test.dll",
        "format": "PE",
        "file_size": 1024,
        "md5": "abc123",
        "sha256": "def456",
        "signature_status": "Unsigned",
        "threat_score": 0,
        "sections": [],
        "imports": [],
        "exports": [],
        "anomalies": [],
    }


@pytest.fixture
def full_analysis_result():
    """Full DLL analysis result with sections, imports, exports, and anomalies."""
    return {
        "file_name": "malware.dll",
        "format": "PE",
        "file_size": 45056,
        "md5": "deadbeef123456",
        "sha256": "abcdef1234567890",
        "signature_status": "Unsigned",
        "threat_score": 75,
        "sections": [
            {
                "name": ".text",
                "virtual_address": 0x1000,
                "virtual_size": 0x2000,
                "entry_point": 0x1050,
                "permissions": "RX",
            },
            {
                "name": ".data",
                "virtual_address": 0x3000,
                "virtual_size": 0x1000,
                "entry_point": 0.0,
                "permissions": "RW",
            },
        ],
        "imports": [
            {"dll": "kernel32.dll", "function": "CreateProcessW"},
            {"dll": "wininet.dll", "function": "InternetOpenUrlW"},
        ],
        "exports": [
            {"name": "DllMain", "address": 0x1000},
            {"name": "InitPlugin", "address": 0x2000},
        ],
        "anomalies": [
            "Section .text has unusually high entropy (7.8)",
            "Suspicious import: CreateProcessW from kernel32.dll",
        ],
    }


class TestDLLMarkdownGenerator:
    """Test DLLMarkdownGenerator functionality."""

    def test_generate_method_exists(self, generator):
        """Test that generate method exists and is callable."""
        assert callable(generator.generate)
        assert hasattr(generator, "generate")

    def test_generate_returns_string(self, generator, minimal_analysis_result):
        """Test that generate returns a non-empty string."""
        result = generator.generate(minimal_analysis_result)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_includes_file_name(self, generator, minimal_analysis_result):
        """Test that report includes the file name."""
        result = generator.generate(minimal_analysis_result)
        assert "test.dll" in result

    def test_generate_includes_file_info(self, generator, minimal_analysis_result):
        """Test that report includes file information section."""
        result = generator.generate(minimal_analysis_result)
        assert "## File Information" in result
        assert "PE" in result
        assert "Unsigned" in result

    def test_generate_includes_threat_assessment(self, generator, minimal_analysis_result):
        """Test that report includes threat assessment section."""
        result = generator.generate(minimal_analysis_result)
        assert "## Threat Assessment" in result
        assert "0/100" in result

    def test_generate_sections_table_columns(self, generator, full_analysis_result):
        """Test that sections table has correct columns (no raw_size)."""
        result = generator.generate(full_analysis_result)
        header = "| Name | Virtual Address | Virtual Size | Entry Point | Permissions |"
        assert header in result
        # Ensure raw_size is NOT in the table
        assert "raw_size" not in result

    def test_generate_sections_table_rows(self, generator, full_analysis_result):
        """Test that sections table contains correct row data."""
        result = generator.generate(full_analysis_result)
        assert ".text" in result
        assert "0x1000" in result
        assert "0x2000" in result
        assert ".data" in result
        assert "RX" in result
        assert "RW" in result

    def test_generate_imports_section(self, generator, full_analysis_result):
        """Test that imports section is generated correctly."""
        result = generator.generate(full_analysis_result)
        assert "## Imported Functions" in result
        assert "kernel32.dll" in result
        assert "CreateProcessW" in result
        assert "wininet.dll" in result
        assert "InternetOpenUrlW" in result

    def test_generate_exports_section(self, generator, full_analysis_result):
        """Test that exports section is generated correctly."""
        result = generator.generate(full_analysis_result)
        assert "## Exported Functions" in result
        assert "DllMain" in result
        assert "InitPlugin" in result

    def test_generate_anomalies_section(self, generator, full_analysis_result):
        """Test that anomalies section is generated correctly."""
        result = generator.generate(full_analysis_result)
        assert "## Anomalies" in result
        assert "Section .text has unusually high entropy" in result
        assert "Suspicious import: CreateProcessW" in result

    def test_generate_no_sections_when_empty(self, generator, minimal_analysis_result):
        """Test that no sections section appears when sections list is empty."""
        result = generator.generate(minimal_analysis_result)
        assert "## Sections" not in result

    def test_generate_no_imports_when_empty(self, generator, minimal_analysis_result):
        """Test that no imports section appears when imports list is empty."""
        result = generator.generate(minimal_analysis_result)
        assert "## Imported Functions" not in result

    def test_generate_no_exports_when_empty(self, generator, minimal_analysis_result):
        """Test that no exports section appears when exports list is empty."""
        result = generator.generate(minimal_analysis_result)
        assert "## Exported Functions" not in result

    def test_generate_no_anomalies_when_empty(self, generator, minimal_analysis_result):
        """Test that no anomalies section appears when anomalies list is empty."""
        result = generator.generate(minimal_analysis_result)
        assert "## Anomalies" not in result

    def test_generate_with_default_values(self, generator):
        """Test generation with completely empty dict (all defaults)."""
        result = generator.generate({})
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Unknown" in result  # Default file name

    def test_get_threat_level_critical(self, generator):
        """Test threat level for critical score."""
        assert generator._get_threat_level(85) == "CRITICAL"
        assert generator._get_threat_level(100) == "CRITICAL"

    def test_get_threat_level_high(self, generator):
        """Test threat level for high score."""
        assert generator._get_threat_level(60) == "HIGH"
        assert generator._get_threat_level(79) == "HIGH"

    def test_get_threat_level_medium(self, generator):
        """Test threat level for medium score."""
        assert generator._get_threat_level(40) == "MEDIUM"
        assert generator._get_threat_level(59) == "MEDIUM"

    def test_get_threat_level_low(self, generator):
        """Test threat level for low score."""
        assert generator._get_threat_level(20) == "LOW"
        assert generator._get_threat_level(39) == "LOW"

    def test_get_threat_level_safe(self, generator):
        """Test threat level for safe score."""
        assert generator._get_threat_level(0) == "SAFE"
        assert generator._get_threat_level(19) == "SAFE"

    def test_generate_threat_assessment_with_high_score(self, generator, full_analysis_result):
        """Test threat assessment shows HIGH for score 75."""
        result = generator.generate(full_analysis_result)
        assert "75/100" in result
        assert "HIGH" in result

    def test_generate_report_footer(self, generator, minimal_analysis_result):
        """Test that report includes generator footer."""
        result = generator.generate(minimal_analysis_result)
        assert "*Report generated by DLL Analyzer*" in result

    def test_generate_md5_display(self, generator, minimal_analysis_result):
        """Test that MD5 hash is displayed with backtick formatting."""
        result = generator.generate(minimal_analysis_result)
        assert "abc123" in result

    def test_generate_sha256_display(self, generator, minimal_analysis_result):
        """Test that SHA256 hash is displayed with backtick formatting."""
        result = generator.generate(minimal_analysis_result)
        assert "def456" in result
