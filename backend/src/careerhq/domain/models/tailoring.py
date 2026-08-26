"""Resume tailoring — the version, the run that produced it, and what it holds.

Four tables. `resume_versions` is the business document; `tailoring_runs` is the
audit record of one workflow execution; `resume_version_items` is what the diff
renders and what approval writes to; `reviewer_findings` is what the Reviewer
caught.

**Two absences are load-bearing**, in the manner of `application.py` and
`match.py`:

* **There is no `failed` version status.** A failed run leaves the version at
  `DRAFT` with a `failure_reason` recorded on the run. What remains on disk is
  an untailored resume plus an explanation of the attempt, and a retry reuses
  that draft rather than accumulating abandoned versions.
* **There is no `is_stale` column.** Staleness of the match analysis a run
  depends on is a read-time comparison between the profile's `updated_at` and
  the analysis's `created_at` — the rule `match.py` already established. Stored,
  it would be a second source of truth that goes wrong the moment a profile is
  edited without every dependent row being visited.

Both absences have tests, and those tests were watched failing.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.infrastructure.database import Base


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class VersionStatus(enum.StrEnum):
    """Where one tailored resume has got to.

    `docs/03` §10.1 draws this lifecycle, and this slice **amends** it by
    splitting one state in two.

    `REVIEWING` there meant both *the agent is criticising its own draft* and
    *the agent has finished and it is your turn*. Those are a machine working
    for tens of seconds and a human queue that may last days: different next
    actions, different interfaces, and a person watching a spinner cannot tell
    which one they are in. `AWAITING_APPROVAL` is the missing half.

    `EXPORTED` and `SUBMITTED` are **deliberately absent**. They belong to slice
    006, where export gives them something to mean. A state nothing can reach is
    a claim the code does not support.
    """

    DRAFT = "draft"
    TAILORING = "tailoring"
    REVIEWING = "reviewing"
    AWAITING_APPROVAL = "awaiting_approval"
    READY = "ready"


#: Statuses during which the workflow is running. The partial unique index
#: below is built on exactly this set, so FR-004 ("at most one run in flight per
#: job") is enforced where two clicks cannot race it.
IN_FLIGHT_STATUSES = (VersionStatus.TAILORING, VersionStatus.REVIEWING)


class RunStatus(enum.StrEnum):
    """Where one workflow execution got to.

    `ABANDONED` is distinct from `FAILED` because they mean different things to
    the person and to the reaper: a failure produced a reason, an abandonment
    produced silence. Slice 004 had to learn this the hard way — a stuck run
    that could not be recovered needed hand-written SQL three separate times,
    because the in-flight guard answered 409 to the one action that would have
    cleared it.
    """

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"


class ProposalDecision(enum.StrEnum):
    """What the owner did with one of the agent's proposals.

    **Not `provenance.ItemDecision`**, which is the import reviewer's choice and
    uses `DISCARDED` where this uses `REJECTED`. The words differ because the
    actions do: discarding an extracted item stops it ever entering the profile,
    whereas rejecting a proposal keeps the owner's existing wording. Two enums
    with one name would have made that distinction invisible at every call site.

    `EDITED` is what keeps FR-027 checkable: owner-written text stays
    distinguishable from both the agent's proposal and the master's original.
    The profile makes the same distinction with `user_corrected`, for the same
    reason — a correction nobody can identify later is indistinguishable from
    something the machine wrote.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EDITED = "edited"


class SourceKind(enum.StrEnum):
    """Which kind of profile fact an item derives from."""

    SUMMARY = "summary"
    TITLE = "title"
    EXPERIENCE_BULLET = "experience_bullet"
    SKILL = "skill"
    PROJECT = "project"
    EDUCATION = "education"
    CERTIFICATION = "certification"
    LANGUAGE = "language"


class FindingKind(enum.StrEnum):
    """What the Reviewer objected to, as a closed set.

    Closed because **finalisation routes on it**. A free-text concern cannot be
    routed, and the routing is where Principle III is enforced:

    * `UNGROUNDED` — the claim traces to nothing in the profile. The proposal is
      discarded *before persistence*, so it never reaches an approve button.
    * `OVERSTATED` — the profile supports it; the wording inflates it. Shown to
      the owner, flagged. Their judgement, not ours.
    * `UNCOVERED` — a requirement the draft fails to address. Shown against the
      draft as a whole.

    An `UNGROUNDED` finding **must quote what it objects to**, enforced below as
    a check constraint. Slice 004 established why: a verdict carrying no
    evidence lets the model invent the *absence*, which is the same fabrication
    pointed the other way. A finding that cannot say which words are unsupported
    cannot be tested, cannot be displayed, and cannot be checked by a person.
    """

    UNGROUNDED = "ungrounded"
    OVERSTATED = "overstated"
    UNCOVERED = "uncovered"


class ResumeVersion(Base):
    """One tailored resume for one job.

    Records lineage rather than inheriting it (ADR-012): the source master and
    **the state that master was in at creation**. After creation this is an
    independent document — a later profile edit must not reach it, which is
    Principle IV and is asserted by `test_version_immutability.py`.
    """

    __tablename__ = "resume_versions"

    __table_args__ = (
        # FR-004, in the schema rather than in a handler. An application-level
        # check loses to a double-click; a partial unique index does not.
        Index(
            "uq_resume_versions_one_in_flight_per_application",
            "application_id",
            unique=True,
            postgresql_where=text("status IN ('tailoring', 'reviewing')"),
        ),
        CheckConstraint(
            "status IN ('draft', 'tailoring', 'reviewing', 'awaiting_approval', 'ready')",
            name="ck_resume_versions_status",
        ),
        CheckConstraint(
            "confidence_score IS NULL OR confidence_score BETWEEN 0 AND 100",
            name="ck_resume_versions_confidence_range",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    profile_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("professional_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Lineage. Which master this was created from, and its state at the time.
    source_resume_profile_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("resume_profiles.id"), nullable=False
    )
    source_profile_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    professional_title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[VersionStatus] = mapped_column(
        String(24), nullable=False, default=VersionStatus.DRAFT
    )
    confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: `docs/03` line 273's "tailoring workflow reference". `use_alter` because
    #: the run points back at the version, and one of the two has to be added
    #: after the other exists. **It must be named** — an unnamed `use_alter`
    #: constraint cannot be dropped, which breaks `drop_all` outright against an
    #: existing database. Slice 004 hit exactly that.
    tailoring_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(
            "tailoring_runs.id",
            use_alter=True,
            name="fk_resume_versions_tailoring_run",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    items: Mapped[list[ResumeVersionItem]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="ResumeVersionItem.position",
        foreign_keys="ResumeVersionItem.resume_version_id",
    )


class TailoringRun(Base):
    """One execution of the workflow. The audit record Principle V requires.

    Usage is stored twice, deliberately: summed onto this row, and itemised in
    `tailoring_run_calls` (T092). The totals alone once looked sufficient —
    "a per-step table nothing reads would be cost without a reader" — until a
    real failed run gave the breakdown a reader: run `cd27b092` was billed
    $0.36 across several calls and the record could not say which node spent
    it, whether the escalation ran, or what the call that failed had already
    cost. The totals stay because two endpoints read them; the rows are the
    itemised bill behind them.
    """

    __tablename__ = "tailoring_runs"

    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'abandoned')",
            name="ck_tailoring_runs_status",
        ),
        CheckConstraint("attempts BETWEEN 0 AND 2", name="ck_tailoring_runs_attempts"),
    )

    id: Mapped[uuid.UUID] = _pk()
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Read, never written (FR-011). Slice 004's calibration is measured over
    #: the history of these rows, and a tailoring run that modified one would
    #: corrupt a measurement nobody would think to re-check.
    match_analysis_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("match_analyses.id"), nullable=False
    )

    #: The Tailoring Plan the draft was written against.
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    #: Every guideline the nodes consumed, each with its source. Redundant while
    #: the source is a static rubric; the only thing that makes slice 007's
    #: retrieval-quality metric measurable once it is not. Storing it from the
    #: start also keeps 005 and 006 runs comparable, which is the point of a
    #: regression harness.
    guidelines_used: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    #: Which named version of the severity rules finalised this run. Changing a
    #: threshold is a **new version, never an edit** — otherwise every
    #: historical run is silently reinterpreted.
    finalisation_rules_version: Mapped[str] = mapped_column(String(32), nullable=False)

    #: Task name -> model, as resolved at run time. Not the configuration file's
    #: current contents, which may have changed since.
    model_config_used: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[RunStatus] = mapped_column(String(16), nullable=False, default=RunStatus.RUNNING)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    #: Null while running. This is what the reaper reads.
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Decimal, never float. An audit value accumulated over many runs, not a
    #: display value.
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("0"))

    #: True only from the fixture gateway, and it reaches the interface. Canned
    #: content mistaken for real output would mean approving invented history.
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    findings: Mapped[list[ReviewerFinding]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    calls: Mapped[list[TailoringRunCall]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="TailoringRunCall.sequence",
    )


class TailoringRunCall(Base):
    """One `complete()` call a run made — the itemised line behind the totals.

    Written by `_record_usage` on **both** paths: the calls a failed run made
    were billed whether or not the run finished, and a failure that persists
    only totals cannot say which node spent what (run `cd27b092`, $0.36).

    Two invariants live in the schema rather than in prose:

    * **(run, sequence) is unique**, so re-recording — a success that then
      fails on the flush re-enters through the failure path — cannot silently
      double the bill. `_record_usage` deletes before it inserts; this index is
      what catches the day that rule is broken.
    * **Every row names its task.** A label-less row answers nothing the totals
      do not already answer, so the schema refuses it.
    """

    __tablename__ = "tailoring_run_calls"

    __table_args__ = (
        Index(
            "uq_tailoring_run_calls_run_sequence",
            "tailoring_run_id",
            "sequence",
            unique=True,
        ),
        CheckConstraint("length(task) > 0", name="ck_tailoring_run_calls_task_named"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0",
            name="ck_tailoring_run_calls_tokens_non_negative",
        ),
        CheckConstraint("cost >= 0", name="ck_tailoring_run_calls_cost_non_negative"),
    )

    id: Mapped[uuid.UUID] = _pk()
    tailoring_run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tailoring_runs.id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Zero-based position in the run's call order. The ordering column, since
    #: a timestamp cannot serve: `func.now()` is transaction-scoped, so every
    #: row written in one transaction would carry the same instant.
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    #: The task name the node passed to `complete()` — `tailor_plan`,
    #: `tailor_review`, `tailor_revise_escalated`. Task, not node: the
    #: escalation *is* a task name (docs/08 §3.2.3), and this column is where
    #: "did the escalation run and what did it cost" becomes answerable.
    task: Mapped[str] = mapped_column(String(64), nullable=False)

    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Decimal, never float. An audit value, not a display value.
    cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)

    #: Per call, not smeared across the run: `tailoring_runs.is_fixture` is
    #: "any call was canned", this is "*this* call was".
    is_fixture: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    run: Mapped[TailoringRun] = relationship(back_populates="calls")


class ResumeVersionItem(Base):
    """One item in a tailored version — what the diff renders.

    **`original_text` is copied, not referenced**, and that is a deliberate
    departure from Principle I's "reference, do not duplicate". FR-031 and
    Principle IV require a version not to change when the profile does; a
    reference would make an approved diff mutate underneath it, and "what you
    approved" would stop being reproducible. The copy *is* the lineage snapshot,
    which is the same reasoning behind `source_profile_updated_at` above.

    **`final_text` is materialised rather than derived** from `decision` plus
    the other two columns. Deriving it means every reader re-implements the
    rule, and the reader that gets it wrong is slice 006's PDF export — where a
    wrong answer becomes a document sent to an employer.
    """

    __tablename__ = "resume_version_items"

    __table_args__ = (
        Index(
            "uq_resume_version_items_source",
            "resume_version_id",
            "source_kind",
            "source_item_id",
            unique=True,
            postgresql_where=text("source_item_id IS NOT NULL"),
        ),
        CheckConstraint(
            "decision IN ('pending', 'accepted', 'rejected', 'edited')",
            name="ck_resume_version_items_decision",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    resume_version_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    source_kind: Mapped[SourceKind] = mapped_column(String(32), nullable=False)
    #: The profile fact this derives from. Null for items with no single source,
    #: such as a rewritten summary assembled from several.
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    #: Null when the agent proposed no change to this item.
    proposed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_text: Mapped[str] = mapped_column(Text, nullable=False)

    decision: Mapped[ProposalDecision] = mapped_column(
        String(16), nullable=False, default=ProposalDecision.PENDING
    )
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    version: Mapped[ResumeVersion] = relationship(
        back_populates="items", foreign_keys=[resume_version_id]
    )
    findings: Mapped[list[ReviewerFinding]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )


class ReviewerFinding(Base):
    """One thing the Reviewer objected to.

    Findings persist **even when the proposal they objected to was discarded**
    under the grounding rule. The record of what the Reviewer caught is the
    evidence that the guardrail ran at all, and slice 007 measures against it.
    """

    __tablename__ = "reviewer_findings"

    __table_args__ = (
        CheckConstraint(
            "kind IN ('ungrounded', 'overstated', 'uncovered')",
            name="ck_reviewer_findings_kind",
        ),
        # An `ungrounded` finding must say which words it objects to. Without
        # this the model can assert an absence it cannot support, which is the
        # fabrication the taxonomy exists to prevent, pointed the other way.
        CheckConstraint(
            "kind <> 'ungrounded' OR (quoted_text IS NOT NULL AND length(quoted_text) > 0)",
            name="ck_reviewer_findings_ungrounded_quotes",
        ),
        # An `uncovered` finding concerns the draft as a whole. There is no item
        # for an unaddressed requirement to attach to, and manufacturing one
        # would repeat slice 004's `unverified`-shortfall mistake exactly:
        # demanding a structured field the model has no honest basis to fill.
        CheckConstraint(
            "kind <> 'uncovered' OR resume_version_item_id IS NULL",
            name="ck_reviewer_findings_uncovered_has_no_item",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    tailoring_run_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("tailoring_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resume_version_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("resume_version_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    kind: Mapped[FindingKind] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    quoted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    run: Mapped[TailoringRun] = relationship(back_populates="findings")
    item: Mapped[ResumeVersionItem | None] = relationship(back_populates="findings")
