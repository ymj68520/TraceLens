"""
Unit tests for the Pydantic API schemas (``server.models.schemas``).

These tests verify that:
* The schema module imports cleanly (brief Step 2).
* Field constraints (roles, formats, command types, sizes, TTL bounds) reject
  invalid input and accept valid input.
* The ``image_metadata`` / ``task_metadata`` / ``result_metadata`` field names
  match the SQLAlchemy ORM attribute names, so response models can be populated
  from ORM instances via ``from_attributes``.
"""
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from server.models import schemas


# ---------------------------------------------------------------------------
# Import / module surface
# ---------------------------------------------------------------------------

class TestModuleSurface:
    def test_module_imports_cleanly(self):
        # Brief Step 2: ``from server.models.schemas import *`` must succeed.
        assert hasattr(schemas, "UserCreate")
        assert hasattr(schemas, "CommandResponse")
        assert hasattr(schemas, "ErrorResponse")

    EXPECTED_SCHEMAS = [
        "OrganizationBase",
        "OrganizationCreate",
        "OrganizationResponse",
        "UserBase",
        "UserCreate",
        "UserLogin",
        "UserResponse",
        "TokenResponse",
        "ClientCapabilities",
        "ClientRegister",
        "ClientResponse",
        "ClientCredentialResponse",
        "DiskImageCreate",
        "DiskImageResponse",
        "CommandCreate",
        "CommandResponse",
        "CommandPollResponse",
        "AnalysisTaskCreate",
        "AnalysisTaskResponse",
        "AnalysisResultCreate",
        "TaskStatusUpdate",
        "RegistrationTokenCreate",
        "RegistrationTokenResponse",
        "ErrorResponse",
    ]

    def test_all_expected_schemas_present(self):
        for name in self.EXPECTED_SCHEMAS:
            assert hasattr(schemas, name), f"missing schema: {name}"


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------

class TestOrganizationSchemas:
    def test_create_with_defaults(self):
        org = schemas.OrganizationCreate(name="Acme")
        assert org.subscription_tier == "free"
        assert org.settings == {}

    def test_rejects_empty_name(self):
        with pytest.raises(ValidationError):
            schemas.OrganizationCreate(name="")

    def test_rejects_oversized_name(self):
        with pytest.raises(ValidationError):
            schemas.OrganizationCreate(name="x" * 256)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

VALID_ROLE_IDS = ["super_admin", "org_admin", "analyst", "auditor"]


class TestUserSchemas:
    def _valid_kwargs(self, **overrides):
        base = {
            "username": "analyst1",
            "email": "analyst@example.com",
            "role": "analyst",
            "password": "securepass",
            "org_id": uuid.uuid4(),
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize("role", VALID_ROLE_IDS)
    def test_all_role_names_accepted(self, role):
        user = schemas.UserCreate(**self._valid_kwargs(role=role))
        assert user.role == role

    def test_rejects_invalid_role(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(**self._valid_kwargs(role="wizard"))

    def test_rejects_short_username(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(**self._valid_kwargs(username="ab"))  # < 3 chars

    def test_rejects_short_password(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(**self._valid_kwargs(password="short"))  # < 8 chars

    def test_rejects_invalid_email(self):
        with pytest.raises(ValidationError):
            schemas.UserCreate(**self._valid_kwargs(email="not-an-email"))

    def test_login_schema(self):
        login = schemas.UserLogin(username="u", password="p")
        assert login.username == "u"


class TestTokenResponse:
    def test_defaults_and_required(self):
        tok = schemas.TokenResponse(access_token="abc", expires_in=3600)
        assert tok.token_type == "bearer"
        assert tok.expires_in == 3600


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class TestClientSchemas:
    def test_register_with_capabilities(self):
        reg = schemas.ClientRegister(
            registration_token="tok",
            hostname="host-01",
            capabilities=schemas.ClientCapabilities(),
        )
        assert reg.capabilities.max_concurrent_tasks == 2
        assert reg.capabilities.supported_formats == ["E01", "DD", "Directory"]
        assert reg.capabilities.version == "1.0.0"

    def test_register_rejects_empty_hostname(self):
        with pytest.raises(ValidationError):
            schemas.ClientRegister(
                registration_token="tok",
                hostname="",
                capabilities=schemas.ClientCapabilities(),
            )

    def test_credential_response_defaults(self):
        creds = schemas.ClientCredentialResponse(
            client_id=uuid.uuid4(),
            jwt_token="jwt",
            server_url="http://localhost",
        )
        assert creds.poll_interval == 10

    def test_response_from_orm_like_object(self):
        # ``from_attributes`` lets the response read from a plain object.
        client_obj = SimpleNamespace(
            id=uuid.uuid4(),
            created_at=datetime.utcnow(),
            org_id=uuid.uuid4(),
            hostname="host-01",
            status="online",
            last_poll=None,
            last_seen=None,
            version=None,
            capabilities={"max_concurrent_tasks": 2},
        )
        resp = schemas.ClientResponse.model_validate(client_obj)
        assert resp.hostname == "host-01"
        assert resp.status == "online"


# ---------------------------------------------------------------------------
# Disk Image
# ---------------------------------------------------------------------------

DISK_FORMATS = ["E01", "DD", "Directory"]


class TestDiskImageSchemas:
    def _valid_kwargs(self, **overrides):
        base = {
            "path": "/evidence/disk.e01",
            "size_bytes": 1024,
            "format": "E01",
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize("fmt", DISK_FORMATS)
    def test_all_formats_accepted(self, fmt):
        img = schemas.DiskImageCreate(**self._valid_kwargs(format=fmt))
        assert img.format == fmt

    def test_rejects_invalid_format(self):
        with pytest.raises(ValidationError):
            schemas.DiskImageCreate(**self._valid_kwargs(format="ISO"))

    def test_rejects_non_positive_size(self):
        with pytest.raises(ValidationError):
            schemas.DiskImageCreate(**self._valid_kwargs(size_bytes=0))

    def test_uses_image_metadata_field_name(self):
        # Must match ORM attribute ``DiskImage.image_metadata``.
        img = schemas.DiskImageCreate(
            **self._valid_kwargs(image_metadata={"case": "C-1"})
        )
        assert img.image_metadata == {"case": "C-1"}
        # The reserved name ``metadata`` must NOT be a schema field.
        assert "metadata" not in schemas.DiskImageCreate.model_fields

    def test_response_reads_image_metadata_from_orm_like(self):
        disk_obj = SimpleNamespace(
            id=uuid.uuid4(),
            created_at=datetime.utcnow(),
            client_id=uuid.uuid4(),
            indexed_at=datetime.utcnow(),
            path="/evidence/disk.dd",
            size_bytes=2048,
            format="DD",
            md5_hash=None,
            image_metadata={"source": "acquisition"},
        )
        resp = schemas.DiskImageResponse.model_validate(disk_obj)
        assert resp.image_metadata == {"source": "acquisition"}


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

COMMAND_TYPES = ["analyze_disk", "extract_file", "health_check"]


class TestCommandSchemas:
    def _valid_kwargs(self, **overrides):
        base = {
            "client_id": uuid.uuid4(),
            "command_type": "analyze_disk",
            "parameters": {"image_path": "/disk.e01"},
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize("ctype", COMMAND_TYPES)
    def test_all_command_types_accepted(self, ctype):
        cmd = schemas.CommandCreate(**self._valid_kwargs(command_type=ctype))
        assert cmd.command_type == ctype

    def test_rejects_invalid_command_type(self):
        with pytest.raises(ValidationError):
            schemas.CommandCreate(**self._valid_kwargs(command_type="reboot"))

    def test_ttl_defaults_to_24(self):
        cmd = schemas.CommandCreate(**self._valid_kwargs())
        assert cmd.ttl_hours == 24

    @pytest.mark.parametrize("ttl", [0, -1, 169, 200])
    def test_rejects_out_of_range_ttl(self, ttl):
        with pytest.raises(ValidationError):
            schemas.CommandCreate(**self._valid_kwargs(ttl_hours=ttl))

    @pytest.mark.parametrize("ttl", [1, 24, 168])
    def test_accepts_in_range_ttl(self, ttl):
        cmd = schemas.CommandCreate(**self._valid_kwargs(ttl_hours=ttl))
        assert cmd.ttl_hours == ttl

    def test_priority_defaults_normal(self):
        cmd = schemas.CommandCreate(**self._valid_kwargs())
        assert cmd.priority == "normal"


class TestCommandParameterModels:
    def test_analyze_disk_defaults(self):
        p = schemas.AnalyzeDiskParameters(image_path="/disk.e01")
        assert p.analysis_type == "full"
        assert p.output_format == "sqlite"
        assert p.options == {"file_carving": True, "llm_text_extraction": True}

    def test_extract_file_defaults(self):
        p = schemas.ExtractFileParameters(image_path="/disk.e01", file_path="/doc")
        assert p.output_to == "server"

    def test_health_check_has_no_required_fields(self):
        p = schemas.HealthCheckParameters()
        # No fields beyond the base; should construct without input.
        assert p.model_dump() == {}


# ---------------------------------------------------------------------------
# Analysis Task
# ---------------------------------------------------------------------------

ANALYSIS_TYPES = ["full", "quick", "windows", "android", "linux"]


class TestAnalysisTaskSchemas:
    def _valid_kwargs(self, **overrides):
        base = {
            "client_id": uuid.uuid4(),
            "disk_image_id": uuid.uuid4(),
            "task_name": "case-1 analysis",
            "analysis_type": "full",
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize("atype", ANALYSIS_TYPES)
    def test_all_analysis_types_accepted(self, atype):
        task = schemas.AnalysisTaskCreate(**self._valid_kwargs(analysis_type=atype))
        assert task.analysis_type == atype

    def test_rejects_invalid_analysis_type(self):
        with pytest.raises(ValidationError):
            schemas.AnalysisTaskCreate(**self._valid_kwargs(analysis_type="macos"))

    def test_rejects_empty_task_name(self):
        with pytest.raises(ValidationError):
            schemas.AnalysisTaskCreate(**self._valid_kwargs(task_name=""))

    def test_response_uses_task_metadata_field_name(self):
        # Must match ORM attribute ``AnalysisTask.task_metadata``.
        assert "task_metadata" in schemas.AnalysisTaskResponse.model_fields
        assert "metadata" not in schemas.AnalysisTaskResponse.model_fields

    def test_response_reads_task_metadata_from_orm_like(self):
        task_obj = SimpleNamespace(
            id=uuid.uuid4(),
            created_at=datetime.utcnow(),
            org_id=uuid.uuid4(),
            client_id=None,
            user_id=None,
            disk_image_id=None,
            task_name="case-1",
            analysis_type="full",
            status="created",
            progress=0,
            started_at=None,
            completed_at=None,
            error_message=None,
            task_metadata={"priority_label": "high"},
        )
        resp = schemas.AnalysisTaskResponse.model_validate(task_obj)
        assert resp.task_metadata == {"priority_label": "high"}


# ---------------------------------------------------------------------------
# Analysis Result / Task status update
# ---------------------------------------------------------------------------

class TestAnalysisResultSchemas:
    def _valid_kwargs(self, **overrides):
        base = {
            "command_id": uuid.uuid4(),
            "task_id": uuid.uuid4(),
            "status": "completed",
        }
        base.update(overrides)
        return base

    @pytest.mark.parametrize("status", ["completed", "failed"])
    def test_valid_statuses_accepted(self, status):
        res = schemas.AnalysisResultCreate(**self._valid_kwargs(status=status))
        assert res.status == status

    def test_rejects_invalid_status(self):
        with pytest.raises(ValidationError):
            schemas.AnalysisResultCreate(**self._valid_kwargs(status="running"))

    def test_uses_result_metadata_field_name(self):
        # Must match ORM attribute ``AnalysisResult.result_metadata``.
        res = schemas.AnalysisResultCreate(
            **self._valid_kwargs(result_metadata={"artifacts": 3})
        )
        assert res.result_metadata == {"artifacts": 3}
        assert "metadata" not in schemas.AnalysisResultCreate.model_fields


class TestTaskStatusUpdate:
    def test_progress_bounds(self):
        update = schemas.TaskStatusUpdate(
            command_id=uuid.uuid4(), status="in_progress", progress=50
        )
        assert update.progress == 50

    @pytest.mark.parametrize("progress", [-1, 101])
    def test_rejects_out_of_range_progress(self, progress):
        with pytest.raises(ValidationError):
            schemas.TaskStatusUpdate(
                command_id=uuid.uuid4(), status="in_progress", progress=progress
            )


# ---------------------------------------------------------------------------
# Registration Token
# ---------------------------------------------------------------------------

class TestRegistrationTokenSchemas:
    def test_defaults(self):
        tok = schemas.RegistrationTokenCreate(org_id=uuid.uuid4())
        assert tok.max_clients == 10
        assert tok.expires_in_hours == 720

    @pytest.mark.parametrize("max_clients", [0, -1, 1001])
    def test_rejects_out_of_range_max_clients(self, max_clients):
        with pytest.raises(ValidationError):
            schemas.RegistrationTokenCreate(
                org_id=uuid.uuid4(), max_clients=max_clients
            )

    @pytest.mark.parametrize("hours", [0, 8761])
    def test_rejects_out_of_range_expiry(self, hours):
        with pytest.raises(ValidationError):
            schemas.RegistrationTokenCreate(
                org_id=uuid.uuid4(), expires_in_hours=hours
            )


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------

class TestErrorResponse:
    def test_only_error_required(self):
        err = schemas.ErrorResponse(error="not_found")
        assert err.detail is None
        assert err.code is None
