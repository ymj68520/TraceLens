"""
Unit tests for the SQLAlchemy ORM models (``server.models.database``).

These tests verify that the ORM metadata is a faithful reflection of the
PostgreSQL schema in ``migrations/postgresql/001_initial_schema.sql`` — tables,
columns, column types, foreign keys, CHECK / UNIQUE constraints, and indexes.

No live database connection is required: we inspect ``Base.metadata`` and compile
``CREATE TABLE`` DDL with the PostgreSQL dialect to assert that the constraint
clauses are emitted exactly as the migration defines them.
"""
import uuid

import pytest
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.schema import CreateTable

from server.db.session import Base
from server.models.database import (
    AnalysisResult,
    AnalysisTask,
    Client,
    CommandQueue,
    DiskImage,
    LLMAnalysis,
    Organization,
    RegistrationToken,
    TaskHistory,
    User,
)

ALL_MODELS = [
    Organization,
    User,
    Client,
    DiskImage,
    CommandQueue,
    AnalysisTask,
    AnalysisResult,
    LLMAnalysis,
    TaskHistory,
    RegistrationToken,
]

EXPECTED_TABLES = {
    "organizations",
    "users",
    "clients",
    "disk_images",
    "command_queue",
    "analysis_tasks",
    "analysis_results",
    "llm_analysis",
    "task_history",
    "registration_tokens",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def table_ddl(model) -> str:
    """Compile a model's CREATE TABLE to PostgreSQL DDL text."""
    return str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))


def columns(model):
    """Return a {column_name: Column} dict keyed by the DB column name."""
    return {col.name: col for col in model.__table__.columns}


# ---------------------------------------------------------------------------
# Table coverage
# ---------------------------------------------------------------------------

class TestTableCoverage:
    def test_all_ten_tables_present_in_metadata(self):
        assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES

    def test_no_extra_or_missing_tables(self):
        # Exact-match assertion (combined with the test above for clarity).
        assert len(Base.metadata.tables) == 10

    def test_every_model_maps_to_expected_table_name(self):
        names = {m.__tablename__ for m in ALL_MODELS}
        assert names == EXPECTED_TABLES


# ---------------------------------------------------------------------------
# Primary keys + UUID defaults
# ---------------------------------------------------------------------------

class TestPrimaryKeys:
    @pytest.mark.parametrize("model", ALL_MODELS)
    def test_each_model_has_uuid_primary_key(self, model):
        pk_cols = [c for c in model.__table__.primary_key.columns]
        assert len(pk_cols) == 1
        pk = pk_cols[0]
        assert isinstance(pk.type, UUID)
        # The Python-side default is a uuid4 generator. SQLAlchemy wraps the
        # callable as a CallableColumnDefault; invoke it (with a dummy context)
        # to confirm it yields a UUID.
        assert pk.default is not None
        value = pk.default.arg(None)
        assert isinstance(value, uuid.UUID)


# ---------------------------------------------------------------------------
# Per-table column / type fidelity
# ---------------------------------------------------------------------------

class TestOrganizationColumns:
    def test_columns(self):
        c = columns(Organization)
        assert isinstance(c["id"].type, UUID)
        assert isinstance(c["name"].type, UUID.__class__) or c["name"].type.length == 255
        assert c["name"].nullable is False
        assert c["name"].unique is True
        assert isinstance(c["settings"].type, JSONB)
        assert isinstance(c["subscription_tier"].type, JSONB.__class__) or c[
            "subscription_tier"
        ].type.length == 50
        assert "created_at" in c


class TestUserColumns:
    def test_columns_and_nullability(self):
        c = columns(User)
        assert c["username"].nullable is False
        assert c["email"].nullable is False
        assert c["password_hash"].nullable is False
        assert c["role"].nullable is False
        assert c["password_hash"].type.length == 255

    def test_cost_is_decimal_not_biginteger(self):
        # llm_analysis.cost must be DECIMAL(10,4) per schema (not BigInteger)
        cost = columns(LLMAnalysis)["cost"]
        assert isinstance(cost.type, Numeric)
        assert (cost.type.precision, cost.type.scale) == (10, 4)


class TestMetadataColumnMapping:
    """``metadata`` is reserved in SQLAlchemy; verify the DB column is correct."""

    def test_disk_image_metadata_db_column_name(self):
        assert "metadata" in columns(DiskImage)
        assert isinstance(columns(DiskImage)["metadata"].type, JSONB)

    def test_analysis_task_metadata_db_column_name(self):
        assert "metadata" in columns(AnalysisTask)
        assert isinstance(columns(AnalysisTask)["metadata"].type, JSONB)

    def test_analysis_result_metadata_db_column_name(self):
        assert "metadata" in columns(AnalysisResult)
        assert isinstance(columns(AnalysisResult)["metadata"].type, JSONB)

    def test_python_attributes_differ_from_db_column(self):
        # The reserved name is exposed under a renamed Python attribute.
        assert hasattr(DiskImage, "image_metadata")
        assert hasattr(AnalysisTask, "task_metadata")
        assert hasattr(AnalysisResult, "result_metadata")


class TestNullableAndSizeFidelity:
    def test_disk_images_required_fields(self):
        c = columns(DiskImage)
        assert c["path"].nullable is False
        assert c["size_bytes"].nullable is False
        assert c["format"].nullable is False
        assert c["path"].type.length == 1000
        assert c["md5_hash"].type.length == 32

    def test_command_queue_required_fields(self):
        c = columns(CommandQueue)
        assert c["command_type"].nullable is False
        assert c["parameters"].nullable is False
        assert isinstance(c["parameters"].type, JSONB)
        assert c["ttl"].nullable is False

    def test_analysis_tasks_required_fields(self):
        c = columns(AnalysisTask)
        assert c["task_name"].nullable is False
        assert c["analysis_type"].nullable is False

    def test_analysis_results_required_fields(self):
        c = columns(AnalysisResult)
        assert c["result_type"].nullable is False

    def test_llm_analysis_required_fields(self):
        c = columns(LLMAnalysis)
        assert c["analysis_result"].nullable is False

    def test_registration_tokens_required_fields(self):
        c = columns(RegistrationToken)
        assert c["token"].nullable is False
        assert c["token"].unique is True
        assert c["expires_at"].nullable is False


# ---------------------------------------------------------------------------
# Foreign keys (count + ondelete behavior)
# ---------------------------------------------------------------------------

class TestForeignKeys:
    def test_total_fk_count_matches_schema(self):
        total_fks = sum(
            len(t.foreign_keys) for t in Base.metadata.tables.values()
        )
        # 17 FK relationships: 16 from the Task 1 schema + command_queue.task_id
        # added in migration 002 (Task 4).
        assert total_fks == 17

    @pytest.mark.parametrize(
        "model,col,parent,ondelete",
        [
            (User, "org_id", "organizations", "CASCADE"),
            (Client, "org_id", "organizations", "CASCADE"),
            (DiskImage, "client_id", "clients", "CASCADE"),
            (CommandQueue, "client_id", "clients", "CASCADE"),
            (CommandQueue, "user_id", "users", "SET NULL"),
            (CommandQueue, "task_id", "analysis_tasks", "CASCADE"),  # migration 002
            (AnalysisTask, "org_id", "organizations", "CASCADE"),
            (AnalysisTask, "client_id", "clients", "SET NULL"),
            (AnalysisTask, "user_id", "users", "SET NULL"),
            (AnalysisTask, "disk_image_id", "disk_images", "SET NULL"),
            (AnalysisResult, "task_id", "analysis_tasks", "CASCADE"),
            (AnalysisResult, "client_id", "clients", "SET NULL"),
            (LLMAnalysis, "task_id", "analysis_tasks", "CASCADE"),
            (TaskHistory, "task_id", "analysis_tasks", "CASCADE"),
            (TaskHistory, "user_id", "users", "SET NULL"),
            (RegistrationToken, "org_id", "organizations", "CASCADE"),
        ],
    )
    def test_fk_target_and_ondelete(self, model, col, parent, ondelete):
        # Iterate a COPY (list(...)) so we never mutate the column's FK set,
        # which would corrupt later mapper configuration.
        fks = list(columns(model)[col].foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == parent
        assert fk.ondelete == ondelete

    def test_registration_token_created_by_has_no_ondelete(self):
        # Schema: created_by UUID REFERENCES users(id)  (no ON DELETE clause)
        fks = list(columns(RegistrationToken)["created_by"].foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == "users"
        assert fk.ondelete in (None, "NO ACTION")

    def test_llm_analysis_file_id_has_no_fk(self):
        # file_id is a plain UUID with no FK in the schema
        assert len(list(columns(LLMAnalysis)["file_id"].foreign_keys)) == 0


# ---------------------------------------------------------------------------
# CHECK constraints (compiled DDL contains the exact predicate text)
# ---------------------------------------------------------------------------

class TestCheckConstraints:
    @pytest.mark.parametrize(
        "model, predicate",
        [
            (
                User,
                "role IN ('super_admin', 'org_admin', 'analyst', 'auditor')",
            ),
            (Client, "status IN ('online', 'offline', 'error')"),
            (
                DiskImage,
                "format IN ('E01', 'DD', 'Directory')",
            ),
            (
                CommandQueue,
                "command_type IN ('analyze_disk', 'extract_file', 'health_check')",
            ),
            (
                CommandQueue,
                "priority IN ('low', 'normal', 'high', 'critical')",
            ),
            (
                CommandQueue,
                "status IN ('pending', 'assigned', 'in_progress', 'completed', "
                "'failed', 'expired')",
            ),
            (
                AnalysisTask,
                "analysis_type IN ('full', 'quick', 'windows', 'android', 'linux')",
            ),
            (
                AnalysisTask,
                "status IN ('created', 'queued', 'running', 'completed', 'failed', "
                "'cancelled')",
            ),
            (AnalysisTask, "progress >= 0 AND progress <= 100"),
            (
                AnalysisResult,
                "result_type IN ('database', 'file', 'metadata')",
            ),
            (RegistrationToken, "max_clients > 0"),
            (RegistrationToken, "used_count >= 0"),
            (RegistrationToken, "used_count <= max_clients"),
        ],
    )
    def test_check_predicate_present(self, model, predicate):
        # Normalize whitespace so line-wrapping in DDL doesn't break matching.
        import re

        ddl = re.sub(r"\s+", " ", table_ddl(model))
        assert predicate in ddl, (
            f"CHECK predicate missing from {model.__tablename__} DDL:\n{ddl}"
        )

    def test_no_unexpected_check_constraints(self):
        # Count CHECK constraints per table matches the schema.
        expected_counts = {
            "users": 1,
            "clients": 1,
            "disk_images": 1,
            "command_queue": 3,
            "analysis_tasks": 3,
            "analysis_results": 1,
            "registration_tokens": 3,
        }
        from sqlalchemy import CheckConstraint

        for table_name, count in expected_counts.items():
            table = Base.metadata.tables[table_name]
            checks = [
                c
                for c in table.constraints
                if isinstance(c, CheckConstraint)
            ]
            assert len(checks) == count, (
                f"{table_name}: expected {count} CHECK constraints, "
                f"got {len(checks)}"
            )


# ---------------------------------------------------------------------------
# UNIQUE constraints
# ---------------------------------------------------------------------------

class TestUniqueConstraints:
    @pytest.mark.parametrize(
        "model, cols",
        [
            (User, ["org_id", "username"]),
            (Client, ["org_id", "hostname"]),
        ],
    )
    def test_composite_unique(self, model, cols):
        from sqlalchemy import UniqueConstraint

        table = model.__table__
        composites = [
            c for c in table.constraints if isinstance(c, UniqueConstraint)
        ]
        found = any(
            sorted(c.name for c in uc.columns) == sorted(cols)
            or [col.name for col in uc.columns] == cols
            for uc in composites
        )
        assert found, (
            f"{model.__tablename__} missing UNIQUE({', '.join(cols)}); "
            f"got {[ [c.name for c in uc.columns] for uc in composites]}"
        )

    def test_organizations_name_unique(self):
        assert columns(Organization)["name"].unique is True

    def test_clients_registration_token_unique(self):
        assert columns(Client)["registration_token"].unique is True

    def test_registration_tokens_token_unique(self):
        assert columns(RegistrationToken)["token"].unique is True


# ---------------------------------------------------------------------------
# Indexes (the six named performance indexes from the schema)
# ---------------------------------------------------------------------------

class TestIndexes:
    EXPECTED = {
        "idx_clients_org_status": ("clients", ("org_id", "status")),
        "idx_command_queue_client_status": (
            "command_queue",
            ("client_id", "status", "ttl"),
        ),
        "idx_analysis_tasks_org_status": (
            "analysis_tasks",
            ("org_id", "status"),
        ),
        "idx_analysis_results_task": ("analysis_results", ("task_id",)),
        "idx_disk_images_client": ("disk_images", ("client_id",)),
        "idx_task_history_task": ("task_history", ("task_id",)),
    }

    @pytest.mark.parametrize("index_name", sorted(EXPECTED))
    def test_named_index_exists(self, index_name):
        table_name, cols = self.EXPECTED[index_name]
        table = Base.metadata.tables[table_name]
        index = table.indexes.get(index_name) if hasattr(table.indexes, "get") else None
        # Table.indexes is a set; look up by name.
        index = next((i for i in table.indexes if i.name == index_name), None)
        assert index is not None, (
            f"Index {index_name} missing from {table_name}; "
            f"have {[i.name for i in table.indexes]}"
        )
        assert tuple(col.name for col in index.columns) == cols


# ---------------------------------------------------------------------------
# Relationships (ORM-level, for cascade wiring)
# ---------------------------------------------------------------------------

class TestRelationships:
    def test_organization_back_populates(self):
        assert "users" in Organization.__mapper__.relationships
        assert "clients" in Organization.__mapper__.relationships
        assert "analysis_tasks" in Organization.__mapper__.relationships

    def test_cascade_delete_orphans_on_client_children(self):
        # Disk images and commands are deleted with their client.
        disk_images = Client.__mapper__.relationships["disk_images"].cascade
        commands = Client.__mapper__.relationships["commands"].cascade
        assert disk_images.delete and disk_images.delete_orphan
        assert commands.delete and commands.delete_orphan

    def test_analysis_task_children_cascade(self):
        for rel in ("results", "llm_analyses", "history"):
            cascade = AnalysisTask.__mapper__.relationships[rel].cascade
            assert cascade.delete and cascade.delete_orphan
