from pydantic import ValidationError
import pytest

from httpserver.services.forensic_report.models import (
    DataState,
    ReportRecord,
    Severity,
)


def test_report_record_preserves_sensitive_values_verbatim():
    record = ReportRecord(
        record_id="rec_" + "a" * 64,
        category="wifi",
        title="Home WiFi",
        source_table="wifi_networks",
        source_record_id="7",
        data_state=DataState.EXISTING,
        severity=Severity.HIGH,
        fields={"pre_shared_key": "CorrectHorseBatteryStaple"},
    )
    assert record.fields["pre_shared_key"] == "CorrectHorseBatteryStaple"


def test_record_rejects_non_prefixed_identifier():
    with pytest.raises(ValidationError):
        ReportRecord(
            record_id="7",
            category="wifi",
            title="Home WiFi",
            source_table="wifi_networks",
            source_record_id="7",
        )


def test_record_rejects_non_hex_identifier():
    with pytest.raises(ValidationError):
        ReportRecord(
            record_id="rec_" + "z" * 64,
            category="wifi",
            title="Home WiFi",
            source_table="wifi_networks",
            source_record_id="7",
        )
