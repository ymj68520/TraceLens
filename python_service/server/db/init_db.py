"""
Database initialization and migration script.

Usage (run from the ``python_service`` directory)::

    python -m server.db.init_db --migrate --init --seed

* ``--migrate`` applies the canonical SQL schema
  (``migrations/postgresql/001_initial_schema.sql``).
* ``--init`` creates any tables missing from the ORM metadata via
  ``Base.metadata.create_all`` (no-op for tables that already exist).
* ``--seed`` creates the default organization and super admin user.
* ``--drop`` drops all ORM-managed tables (interactive confirm).

The migration file path is resolved relative to the repository root so the
script works whether it is invoked from ``python_service`` or the repo root.
"""
import os
import sys
import uuid

from sqlalchemy import text

# Ensure ``server`` is importable regardless of the current working directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from server.db.session import Base, SessionLocal, engine  # noqa: E402
from server.models.database import (  # noqa: E402
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


def _resolve_migration_path() -> str:
    """Locate ``001_initial_schema.sql`` relative to this file / cwd."""
    candidates = [
        # repo root (two levels up from python_service) + migrations
        os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "migrations",
            "postgresql", "001_initial_schema.sql",
        ),
        # when run from repo root
        "migrations/postgresql/001_initial_schema.sql",
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
    return candidates[-1]


def create_tables():
    """Create all database tables defined in the ORM metadata."""
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created")


def drop_tables():
    """Drop all database tables (USE WITH CAUTION)."""
    Base.metadata.drop_all(bind=engine)
    print("✓ Database tables dropped")


def create_default_organization():
    """Create default organization if it doesn't exist. Returns its id."""
    db = SessionLocal()
    try:
        existing = db.query(Organization).filter(
            Organization.name == "Default Organization"
        ).first()
        if not existing:
            org = Organization(
                id=uuid.uuid4(),
                name="Default Organization",
                subscription_tier="enterprise",
            )
            db.add(org)
            db.commit()
            db.refresh(org)
            print(f"✓ Created default organization: {org.id}")
            return org.id
        else:
            print(f"✓ Default organization exists: {existing.id}")
            return existing.id
    finally:
        db.close()


def create_super_admin(org_id):
    """Create super admin user if it doesn't exist."""
    from passlib.context import CryptContext

    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == "super_admin").first()
        if not existing:
            user = User(
                id=uuid.uuid4(),
                org_id=org_id,
                username="super_admin",
                email="super_admin@tracelens.local",
                password_hash=pwd_context.hash("admin123"),  # CHANGE IN PRODUCTION
                role="super_admin",
            )
            db.add(user)
            db.commit()
            print(f"✓ Created super admin: {user.id}")
        else:
            print(f"✓ Super admin exists: {existing.id}")
    finally:
        db.close()


def run_migrations():
    """Run SQL migrations from the migrations directory."""
    migration_file = _resolve_migration_path()
    if os.path.exists(migration_file):
        with open(migration_file, "r") as f:
            sql = f.read()
        with engine.begin() as conn:  # begin() commits on success, rolls back on error
            conn.execute(text(sql))
        print(f"✓ Applied migration: {migration_file}")
    else:
        print(f"✗ Migration file not found: {migration_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Database management")
    parser.add_argument("--init", action="store_true", help="Initialize database")
    parser.add_argument(
        "--migrate", action="store_true", help="Run SQL migrations"
    )
    parser.add_argument("--seed", action="store_true", help="Seed default data")
    parser.add_argument("--drop", action="store_true", help="Drop all tables")
    args = parser.parse_args()

    if args.drop:
        confirm = input(
            "⚠️  This will drop all tables. Type 'yes' to confirm: "
        )
        if confirm.lower() == "yes":
            drop_tables()
        else:
            print("Aborted")

    if args.migrate:
        run_migrations()

    if args.init:
        create_tables()

    if args.seed:
        org_id = create_default_organization()
        create_super_admin(org_id)
