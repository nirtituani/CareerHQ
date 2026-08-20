"""Recording and moving an application (T068).

The use case that User Story 2 exists for: capture a job — company, title, and
the description text slice 004 will tailor against — and record every move it
makes afterwards.

Two rules are enforced here rather than at the edge, so they hold for the
JobTracker importer in User Story 3 as well as for the HTTP routes:

* **The normalized status is derived, never accepted.** `normalize_status` is
  the only producer (FR-013). No caller passes one in — there is no parameter
  for it.
* **A status change appends history, and only a change does.** Editing notes is
  not a move (FR-012).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.domain.models import (
    Application,
    ApplicationStatusHistory,
    Company,
    normalize_company_name,
    normalize_status,
)

#: Fields a request may write directly. `normalized_status` is absent by design
#: and `status` is handled separately, because moving it writes history.
WRITABLE_FIELDS = frozenset(
    {
        "job_title",
        "location",
        "job_description",
        # The list beside the posting, not in place of it (research.md R1).
        # Accepted from the client because the Add form lets a person write or
        # correct requirements by hand, exactly as it does the description.
        "requirements",
        "job_url",
        "job_description_url",
        "date_added",
        "date_applied",
        "source",
        "salary_text",
        "contact_name",
        "contact_email",
        "notes",
    }
)

#: Written by parsing, never by `setattr` of a raw string.
DATE_FIELDS = frozenset({"date_added", "date_applied"})

DEFAULT_STATUS = "Pre-Applied"


def parse_date(value: Any) -> datetime | None:
    """Coerce what a form sends into what the column holds.

    The form sends `2026-08-15`; the column is a timestamp. Left as a string it
    reaches the driver as text and is cast by PostgreSQL on a good day — so the
    behaviour would depend on the driver rather than on us, and a change of
    driver would turn a working field into a 500.

    Date-only values are anchored at midnight UTC. Storing a bare date as "now"
    would make "added on the 15th" mean something different depending on when
    the form was submitted.
    """
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)

    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # An unparseable date is dropped rather than guessed. A wrong date is
        # worse than an absent one for anything reasoning over a timeline
        # (research.md R8, Finding 4).
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _writable(data: dict[str, Any]) -> dict[str, Any]:
    """The writable subset of a request body, with dates parsed."""
    return {
        field: parse_date(data[field]) if field in DATE_FIELDS else data[field]
        for field in WRITABLE_FIELDS & data.keys()
    }


async def resolve_company(
    session: AsyncSession, *, user_id: uuid.UUID, name: str, domain: str | None = None
) -> Company:
    """Find this user's company by normalized name, or create it (C2, FR-014).

    Read-then-write is safe here only because C2 backs it: under a concurrent
    import retry the second INSERT loses to the UNIQUE constraint rather than
    producing a second row. The check below is the fast path, not the guarantee.

    The domain — the form's "Company Website (for logo)" — belongs to the
    employer rather than to one application, so a second job at the same place
    inherits it without being typed again. An existing domain is not overwritten
    by a later blank.
    """
    normalized = normalize_company_name(name)
    domain = (domain or "").strip() or None

    existing = await session.scalar(
        select(Company).where(Company.user_id == user_id, Company.normalized_name == normalized)
    )
    if existing is not None:
        if domain and not existing.domain:
            existing.domain = domain
        return existing

    # The name is stored as the user first entered it; later spellings of the
    # same employer resolve to this row without rewriting what they typed.
    company = Company(user_id=user_id, name=name.strip(), normalized_name=normalized, domain=domain)
    session.add(company)
    await session.flush()
    return company


async def record_application(
    session: AsyncSession, *, user_id: uuid.UUID, data: dict[str, Any]
) -> Application:
    """Create an application, its company, and its opening history row.

    Valid with no submitted resume (FR-011) — there is no field for one until
    slice 004.
    """
    company = await resolve_company(
        session, user_id=user_id, name=data["company"], domain=data.get("company_domain")
    )
    label = (data.get("status") or DEFAULT_STATUS).strip()

    fields = _writable(data)
    fields.pop("job_title", None)
    # A blank date_added means "now", which is the column's own default.
    if fields.get("date_added") is None:
        fields.pop("date_added", None)

    application = Application(
        user_id=user_id,
        company_id=company.id,
        job_title=data["job_title"],
        status=label,
        normalized_status=normalize_status(label),
        **fields,
    )
    session.add(application)
    await session.flush()

    # The opening status is recorded so the timeline is complete from the first
    # row, rather than beginning at whatever the first edit happened to be.
    session.add(
        ApplicationStatusHistory(
            application_id=application.id,
            from_status=None,
            to_status=label,
            normalized_to_status=application.normalized_status,
        )
    )
    await session.flush()
    return application


def apply_changes(application: Application, data: dict[str, Any]) -> None:
    """Apply a partial update, appending history if the status moved.

    `normalized_status` in the request body is ignored rather than rejected: it
    is derived from the label below, and two fields describing one fact is the
    drift FR-013 exists to prevent.
    """
    for field, value in _writable(data).items():
        setattr(application, field, value)

    if "status" not in data:
        return

    label = (data["status"] or "").strip()
    if not label or label == application.status:
        return

    previous = application.status
    application.status = label
    application.normalized_status = normalize_status(label)

    application.status_history.append(
        ApplicationStatusHistory(
            from_status=previous,
            to_status=label,
            normalized_to_status=application.normalized_status,
            note=data.get("status_note"),
        )
    )


__all__ = [
    "DEFAULT_STATUS",
    "WRITABLE_FIELDS",
    "apply_changes",
    "record_application",
    "resolve_company",
]
