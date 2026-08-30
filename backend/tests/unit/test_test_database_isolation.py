"""The test database is overridable, so two worktrees do not drop each other's schema.

**This is test infrastructure, and it exists because the failure it prevents was misdiagnosed
twice.** `conftest` runs `DROP SCHEMA public CASCADE` at session start. With the database name
hardcoded, two checkouts running the suite at once corrupt each other: the observable symptom is a
scatter of unrelated integration failures whose *count changes between runs of identical code*.
That reads as a flaky suite, and it cost a wrong conclusion about a change that turned out to be
innocent.

**The guard is the other half.** Making the target configurable is precisely what creates the
possibility of pointing it at real data — `.env` sets `DATABASE_URL` to the *development*
database, which holds evaluation evidence that exists nowhere else. So the override has its own
variable name, and a database that does not look like a test database is refused rather than
dropped.
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    DEFAULT_TEST_DATABASE_URL,
    TEST_DATABASE_URL_VAR,
    resolve_test_database_url,
)


def test_the_default_is_unchanged_when_nothing_is_set() -> None:
    """An ordinary local run and CI must behave exactly as before this was configurable.

    **The environment is passed in explicitly rather than read from the process**, because a
    default asserted against the ambient environment is not an assertion about the default: this
    project has already shipped a config test that passed or failed depending on whether an
    earlier test had imported `litellm`, which injects `.env` as real variables. Handing the
    mapping in removes the question.
    """
    assert resolve_test_database_url({}) == DEFAULT_TEST_DATABASE_URL
    assert DEFAULT_TEST_DATABASE_URL.rsplit("/", 1)[-1] == "careerhq_test"


def test_the_variable_redirects_the_suite() -> None:
    """The whole point: a worktree can claim a database nobody else is dropping."""
    url = "postgresql+psycopg://careerhq:careerhq@localhost:5432/careerhq_test_worktree_a"

    assert resolve_test_database_url({TEST_DATABASE_URL_VAR: url}) == url


def test_the_override_is_not_database_url() -> None:
    """**`DATABASE_URL` must not redirect this suite.**

    That name already means "the database this application talks to", and `.env` points it at the
    development database. If it also redirected the tests, a developer who had merely exported
    their own `DATABASE_URL` would drop their development schema by running `pytest` — including
    the paid evaluation rows, which exist in no backup that is current. The override needs a name
    nobody sets by accident.
    """
    resolved = resolve_test_database_url(
        {"DATABASE_URL": "postgresql+psycopg://careerhq:careerhq@localhost:5432/careerhq"}
    )

    assert resolved == DEFAULT_TEST_DATABASE_URL
    assert TEST_DATABASE_URL_VAR != "DATABASE_URL"


@pytest.mark.parametrize(
    "database",
    ["careerhq", "postgres", "railway", "careerhq_prod"],
    ids=["development", "maintenance", "production-name", "prod-suffix"],
)
def test_a_database_that_does_not_look_like_a_test_database_is_refused(database: str) -> None:
    """The suite drops the schema, so the wrong name is unrecoverable rather than inconvenient.

    `careerhq` is the development database and `railway` is production's. Neither should be
    reachable from a variable, and a typo in the variable must fail loudly rather than quietly
    finding a real database and emptying it.
    """
    url = f"postgresql+psycopg://careerhq:careerhq@localhost:5432/{database}"

    with pytest.raises(RuntimeError) as refusal:
        resolve_test_database_url({TEST_DATABASE_URL_VAR: url})

    message = str(refusal.value)
    assert database in message, "the refusal does not say which database was rejected"
    assert "DROP SCHEMA" in message, "the refusal does not say why the name matters"


@pytest.mark.parametrize(
    "database",
    ["careerhq_test", "careerhq_test_agent2", "TEST_upper", "my_test_db"],
)
def test_names_that_do_look_like_test_databases_are_accepted(database: str) -> None:
    """The control.

    Without it the refusal test above passes against a function that rejects everything.
    """
    url = f"postgresql+psycopg://careerhq:careerhq@localhost:5432/{database}"

    assert resolve_test_database_url({TEST_DATABASE_URL_VAR: url}) == url


def test_query_parameters_do_not_defeat_the_check() -> None:
    """`?sslmode=require` is part of the URL, not part of the database name.

    Splitting on `/` alone would leave `careerhq?sslmode=require`, which contains no `test` and so
    would be refused — but a name like `prod?test=1` would sail through. The check reads the name.
    """
    with pytest.raises(RuntimeError):
        resolve_test_database_url(
            {TEST_DATABASE_URL_VAR: "postgresql+psycopg://u:p@h:5432/careerhq?test=1"}
        )
