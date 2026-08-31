"""Migration 0020: reshaping the empty Layer 2 table (slice 010, T003/T006).

The reshape is safe **only because the table is provably empty** — Layer 2 was
never wired to a route, so no deployment can hold a row. The migration asserts
that emptiness before touching anything, and this file is where that guard is
watched failing (testing rule 1): a fake row must make the upgrade refuse.

Runs the real alembic chain against a dedicated scratch database, because the
suite's own schema comes from `create_all` and would prove nothing about the
migration. The scratch name is derived from the test URL so it keeps the
"must contain 'test'" property, and the whole file is skipped when PostgreSQL
is not available — skipped, never silently green.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError

from tests.conftest import resolve_test_database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]

#: The revision under test and the one before it.
TARGET = "0020_application_research"
PREVIOUS = "0019_company_research"


def _scratch_url() -> str:
    base = resolve_test_database_url()
    root, name = base.rsplit("/", 1)
    return f"{root}/{name.split('?', 1)[0]}_migration"


def _sync_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql+psycopg://", 1)


@pytest.fixture(scope="module")
def scratch_database() -> Iterator[str]:
    """A freshly created database this module may migrate and drop."""
    url = _scratch_url()
    admin = sa.create_engine(_sync_url(resolve_test_database_url()), isolation_level="AUTOCOMMIT")
    name = url.rsplit("/", 1)[-1]
    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))
            connection.execute(sa.text(f'CREATE DATABASE "{name}"'))
    except sa.exc.OperationalError as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL not available for migration test: {exc.__class__.__name__}")
    yield url
    with admin.connect() as connection:
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(scope="module")
def alembic_config(scratch_database: str) -> Iterator[Config]:
    """The real alembic config, pointed at the scratch database.

    `env.py` reads the URL from `Settings`, so the override goes through the
    environment plus a cache clear — the same seam the application itself uses.
    """
    import os

    from careerhq.config import get_settings

    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = scratch_database
    get_settings.cache_clear()
    # A file-less Config, deliberately: env.py runs `fileConfig(...)` when a
    # config file is named, and fileConfig disables existing loggers — which
    # silently breaks every caplog assertion that runs after this module. The
    # only thing the ini provides that the migration needs is script_location,
    # so set that alone.
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    yield config
    if previous is not None:
        os.environ["DATABASE_URL"] = previous
    get_settings.cache_clear()


def _seed_role_snapshot_row(url: str) -> None:
    """The minimal FK chain 0019's schema demands, ending in one Layer 2 row."""
    engine = sa.create_engine(_sync_url(url))
    user_id, company_id, application_id, company_snapshot_id, role_snapshot_id = (
        uuid.uuid4() for _ in range(5)
    )
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO users (id, google_sub, email) "
                "VALUES (:id, :sub, 'migration-drill@example.com')"
            ),
            {"id": user_id, "sub": f"drill-{user_id}"},
        )
        connection.execute(
            sa.text(
                "INSERT INTO companies (id, user_id, name, normalized_name) "
                "VALUES (:id, :user_id, 'Drill', 'drill')"
            ),
            {"id": company_id, "user_id": user_id},
        )
        connection.execute(
            sa.text(
                "INSERT INTO applications (id, user_id, company_id, job_title, status, "
                "normalized_status) VALUES (:id, :user_id, :company_id, 'Drill', "
                "'Wishlist', 'wishlist')"
            ),
            {"id": application_id, "user_id": user_id, "company_id": company_id},
        )
        connection.execute(
            sa.text(
                "INSERT INTO company_research_snapshots (id, user_id, company_id, sections, "
                "input_tokens, output_tokens, cost, status) VALUES (:id, :user_id, "
                ":company_id, '{}', 0, 0, 0, 'succeeded')"
            ),
            {"id": company_snapshot_id, "user_id": user_id, "company_id": company_id},
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_research_snapshots (id, user_id, application_id, "
                "company_research_snapshot_id, findings, input_tokens, output_tokens, cost, "
                "status) VALUES (:id, :user_id, :application_id, :company_snapshot_id, '[]', "
                "0, 0, 0, 'succeeded')"
            ),
            {
                "id": role_snapshot_id,
                "user_id": user_id,
                "application_id": application_id,
                "company_snapshot_id": company_snapshot_id,
            },
        )
    engine.dispose()


def _clear_role_snapshot_rows(url: str) -> None:
    engine = sa.create_engine(_sync_url(url))
    with engine.begin() as connection:
        connection.execute(sa.text("DELETE FROM role_research_snapshots"))
    engine.dispose()


def test_0020_refuses_a_populated_table_then_reshapes_an_empty_one(
    scratch_database: str, alembic_config: Config
) -> None:
    """One test, in one order, because the drill IS the scenario.

    Upgrade to 0019 → seed a Layer 2 row → 0020 must refuse naming the guard →
    clear the row → 0020 must succeed → the reshape must be complete. Split into
    separate tests, the refusal could pass against a database a later test had
    already migrated, which is the "gate with nothing to examine" failure.
    """
    command.upgrade(alembic_config, PREVIOUS)

    _seed_role_snapshot_row(scratch_database)
    with pytest.raises((CommandError, RuntimeError), match="role_research_snapshots"):
        command.upgrade(alembic_config, TARGET)

    _clear_role_snapshot_rows(scratch_database)
    command.upgrade(alembic_config, TARGET)

    engine = sa.create_engine(_sync_url(scratch_database))
    inspector = sa.inspect(engine)

    tables = inspector.get_table_names()
    assert "application_research_snapshots" in tables
    assert "role_research_snapshots" not in tables

    columns = {c["name"] for c in inspector.get_columns("application_research_snapshots")}
    # The reshape, column by column: renamed, dropped, added.
    assert "sections" in columns and "findings" not in columns
    assert "company_research_snapshot_id" not in columns
    assert {"produced_by", "cost_basis"} <= columns

    source_columns = {c["name"] for c in inspector.get_columns("research_sources")}
    assert "application_snapshot_id" in source_columns
    assert "role_snapshot_id" not in source_columns

    with engine.connect() as connection:
        constraint = connection.execute(
            sa.text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'ck_research_sources_exactly_one_snapshot'"
            )
        ).scalar_one()
        assert "application_snapshot_id" in constraint

        guard_index = connection.execute(
            sa.text(
                "SELECT indexdef FROM pg_indexes WHERE tablename = "
                "'application_research_snapshots' AND indexname = "
                "'uq_application_research_one_running_per_application'"
            )
        ).scalar_one()
        assert "running" in guard_index

        checks = connection.execute(
            sa.text(
                "SELECT conname FROM pg_constraint WHERE conrelid = "
                "'application_research_snapshots'::regclass AND contype = 'c'"
            )
        ).scalars()
        names = set(checks)

    # Assert the count of what was examined: the three carried-over checks plus
    # the new cost_basis one must all exist under their new names.
    expected = {
        "ck_application_research_snapshots_status",
        "ck_application_research_snapshots_tokens_non_negative",
        "ck_application_research_snapshots_cost_non_negative",
        "ck_application_research_snapshots_cost_basis",
    }
    assert expected <= names, f"missing: {expected - names}"

    engine.dispose()
