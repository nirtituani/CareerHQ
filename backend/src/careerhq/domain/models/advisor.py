"""The Career Advisor's memory — runs, memories, dispositions (data-model.md).

Three tables, and the shape *is* the argument:

* **`career_memories` is insert-only.** Understanding that changes is a new
  row superseding the old one; a claim and its frozen evidence are never
  edited, because editing a persisted claim silently reinterprets what a
  person was told (Constitution IV, the criteria-versioning discipline). The
  mutable remainder is lifecycle position only — `status` moves forward,
  `last_confirmed_at` advances — the "lock is about content, not the row"
  reading the resume-version lock established.
* **`memory_dispositions` is the lifecycle made queryable.** FR-013 says every
  active memory must be explicitly dispositioned by every later run; as an
  append-only log keyed `(run_id, memory_id)` that claim is a set comparison,
  not a hope. `left_open` requires a reason exactly as `retired` does — an
  explicit decision, never a default for a memory the model forgot.
* **`advisor_runs`** mirrors `match_analyses`: a `pending` row committed
  before any provider call, one in flight per user enforced by a partial
  unique index, cost recorded even for a failed run.

**Deliberate absences**, in the manner of `match.py`:

* **No cap constraint.** `count(active) <= 25` is COUNT-shaped, which a CHECK
  cannot express; it is a use-case invariant (`advisor_grounding.py`), closed
  against the only race that matters by the one-pending-run index, and drilled
  by a watched-failing test.
* **No `is_stale` column.** Freshness is `last_confirmed_at` against now,
  derived at read time — stored, it goes wrong the moment anything moves
  without every memory being visited (the `match.py` argument verbatim).
* **No uniqueness on `(kind, scope)`.** Supersession chains legitimately hold
  many rows about one subject; only the *active* set must be
  contradiction-free, and that is the reconciliation gate's job (FR-016).

These are String columns, so a row loaded in a fresh session returns a plain
`str` — compare statuses with ``==``, never ``is`` (the shipped-twice gotcha).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import event as sa_event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.infrastructure.database import Base


class AdvisorRunStatus(enum.StrEnum):
    """Where one run got to. `pending` is committed before any provider call,
    so the interface has something to poll and a failure has somewhere to
    record itself instead of leaving a blank forever."""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MemoryStatus(enum.StrEnum):
    """A memory's lifecycle position. Forward-only:
    ``tentative -> active`` (evidence reached the floor), and either of those
    to ``superseded`` or ``retired``. No transition leaves a terminal state —
    a dismissed claim returning on materially different evidence is a **new**
    row carrying `recreates_dismissed_id`, never a resurrection."""

    ACTIVE = "active"
    TENTATIVE = "tentative"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class DispositionAction(enum.StrEnum):
    """What a run did with one memory. The schema-side verb `leave_open`
    becomes the recorded participle `left_open` here; `advisor_grounding.py`
    owns that translation and is the only module that performs it."""

    CREATED = "created"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"
    RETIRED = "retired"
    LEFT_OPEN = "left_open"


#: The distinguished retirement reason a user's dismissal writes. Both
#: enforcement layers of FR-021 key on it: the prompt renders these memories
#: as "dismissed by the user — do not recreate", and the deterministic gate
#: refuses a matching recreation unless the evidence materially changed.
USER_DISMISSED = "user_dismissed"


class AdvisorRun(Base):
    """One analysis execution. The audit anchor (Constitution V)."""

    __tablename__ = "advisor_runs"

    __table_args__ = (
        # At most one run in flight per user, enforced where it cannot be
        # raced. An application-level check loses to two clicks.
        Index(
            "uq_advisor_run_one_pending_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[AdvisorRunStatus] = mapped_column(String(16), nullable=False)
    #: Set only when `failed`, and shown to the person — the kind of failure,
    #: never the driver's text (slice 002's disclosure rule).
    error: Mapped[str | None] = mapped_column(Text)

    #: `ADVISOR_RULES_VERSION` at run time. NOT NULL from the first insert: a
    #: comparison across runs governed by different unnamed rules measures
    #: nothing (the `criteria_version` argument).
    rules_version: Mapped[str] = mapped_column(String(32), nullable=False)

    #: The full deterministic pack this run computed — facts with ids,
    #: denominators and record ids. NULL while pending. Kept whole so SC-001's
    #: audit and the interface's "computed from" rendering read the run's own
    #: evidence rather than recomputing under possibly-newer rules.
    evidence_pack: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    #: The three counts that make *found-nothing* (`proposed = 0`) and
    #: *discarded-everything* (`proposed > 0, applied = 0`) different,
    #: queryable outcomes (FR-009). NULL while pending.
    ops_proposed: Mapped[int | None] = mapped_column(SmallInteger)
    ops_applied: Mapped[int | None] = mapped_column(SmallInteger)
    ops_discarded: Mapped[int | None] = mapped_column(SmallInteger)

    #: Per-call attribution. The interface reporting one model for a run that
    #: used two is a recorded lesson (T088), so both are stored.
    grouping_model: Mapped[str | None] = mapped_column(String(128))
    reason_model: Mapped[str | None] = mapped_column(String(128))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    #: Decimal, never float — an audit record. Includes what a *failed* run
    #: spent: a run that reads as free is worse than one that reads as
    #: unrecorded.
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    #: True only from the fixture adapter.
    is_fixture: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    dispositions: Mapped[list[MemoryDisposition]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<AdvisorRun {self.id} {self.status}>"


class CareerMemory(Base):
    """One falsifiable claim the agent judged worth preserving. Insert-only."""

    __tablename__ = "career_memories"

    __table_args__ = (
        # NULL scope_value exactly when the scope is global — a two-way
        # equivalence, like the grounding constraint on match requirements.
        CheckConstraint(
            "(scope_kind = 'global') = (scope_value IS NULL)",
            name="ck_career_memory_scope",
        ),
        # A retirement carries its reason, and only a retirement does.
        CheckConstraint(
            "(status = 'retired') = (retired_reason IS NOT NULL)",
            name="ck_career_memory_retired_reason",
        ),
        CheckConstraint(
            "priority IS NULL OR priority BETWEEN 0 AND 100",
            name="ck_career_memory_priority",
        ),
        CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id",
            name="ck_career_memory_supersedes_not_self",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    advisor_run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("advisor_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Immutable after insert (with everything below through
    #: `last_confirmed_at`'s exceptions) — the immutability gate test walks
    #: exactly this list.
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    #: Open vocabulary, deliberately not DB-constrained: the agent may
    #: discover pattern kinds the schema did not anticipate. Grounding rules,
    #: not topic whitelists, are the constraint (spec).
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_value: Mapped[str | None] = mapped_column(Text)

    #: Frozen: the cited facts (numerators, denominators, record ids, date
    #: range) and any grouping relied on, at the moment the claim was made.
    #: A record of past justification, never a live view — the next run
    #: reconciles against *current* data and supersedes if the world moved.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #: Agent-assigned, 0-100, NULL when the memory is not actionable
    #: (FR-022). Mutable: a confirming run may re-rank.
    priority: Mapped[int | None] = mapped_column(SmallInteger)
    priority_reason: Mapped[str | None] = mapped_column(Text)

    status: Mapped[MemoryStatus] = mapped_column(String(16), nullable=False)
    #: Set at insert, never after. The lineage chain the interface walks.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("career_memories.id", ondelete="SET NULL")
    )
    #: The dismissal history a legitimate recreation carries (analyze D8).
    recreates_dismissed_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("career_memories.id", ondelete="SET NULL")
    )
    retired_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: The only mutable timestamp: a `confirmed` disposition advances it. The
    #: fresh figures live on the disposition row's `evidence_delta`, never
    #: here — frozen evidence stays frozen.
    last_confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<CareerMemory {self.id} {self.status} {self.kind}>"


class MemoryDisposition(Base):
    """One run's explicit decision about one memory. Append-only."""

    __tablename__ = "memory_dispositions"

    __table_args__ = (
        UniqueConstraint("run_id", "memory_id", name="uq_memory_disposition_once_per_run"),
        # Retiring and leaving open both state their why; created/confirmed/
        # superseded carry their meaning in the rows they touch.
        CheckConstraint(
            "(action IN ('retired', 'left_open')) = (reason IS NOT NULL)",
            name="ck_memory_disposition_reason",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("advisor_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("career_memories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    action: Mapped[DispositionAction] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    #: A confirmation's fresh figures ("was 6/10 -> now 9/14"), riding the log
    #: row so the memory's frozen evidence is never touched.
    evidence_delta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[AdvisorRun] = relationship(back_populates="dispositions")
    memory: Mapped[CareerMemory] = relationship()

    def __repr__(self) -> str:
        return f"<MemoryDisposition {self.action} {self.memory_id}>"


class MemoryContentFrozen(RuntimeError):
    """A frozen column of a persisted memory was written (FR-012).

    A distinct type for the `VersionLocked` reason: an immutability refusal
    must not be swallowed by a handler written for validation errors, and a
    silent no-op on an immutability guarantee is indistinguishable from
    success — Constitution IV makes that a release blocker.
    """


#: The content columns, frozen at insert. The mutable remainder — `status`
#: (forward only), `retired_reason` (set with the transition), `priority`,
#: `priority_reason` (a confirming run may re-rank) and `last_confirmed_at` —
#: is the lifecycle, and the lock is about content, not the row.
_FROZEN_MEMORY_COLUMNS: tuple[str, ...] = (
    "claim",
    "kind",
    "scope_kind",
    "scope_value",
    "evidence",
    "advisor_run_id",
    "supersedes_id",
    "recreates_dismissed_id",
    "user_id",
    "created_at",
)


@sa_event.listens_for(CareerMemory, "before_update")
def _refuse_frozen_memory_writes(
    mapper: object, connection: object, target: CareerMemory
) -> None:
    """Enforced by a listener rather than by care: every UPDATE against a
    memory passes through here, whatever module issued it — including one the
    boundary gate's whitelist would have allowed."""
    state = sa_inspect(target)
    tampered = [
        column
        for column in _FROZEN_MEMORY_COLUMNS
        if state.attrs[column].history.has_changes()
    ]
    if tampered:
        raise MemoryContentFrozen(
            "a career memory's content is frozen at insert; changed understanding is a "
            f"new memory that supersedes this one. Frozen column(s) written: {tampered}"
        )
