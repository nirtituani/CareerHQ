"""FR-032 — every excerpt is checked verbatim against the page we retrieved.

**The MVP's only verification layer, and it costs nothing.** OQ-B deferred
semantic verification — whether an excerpt actually *supports* the claim built on
it — because that needs a model call, and slice 005 measured its Reviewer at 49%
of run cost. What remains is a string test, and it catches the failure that most
looks correct: **citation laundering**, an invented claim paired with a real URL.

This is only possible because the application fetches its own pages (OQ-A, and
the `SearchHit` boundary in `application/ports.py`). If the search provider had
handed us page content, we would be checking a model's quotation against a
model's summary, which proves nothing.

**Whitespace is normalised; wording is not.** Line wrapping is an artifact of
HTML rather than of what a page says, so an excerpt differing only in newlines is
the same excerpt. A changed word is a different claim and is rejected. The line
between those two is the whole judgement in this module, and it is deliberately
drawn as tightly as possible: normalise runs of whitespace, nothing else.

**A rejected claim is removed, not demoted.** FR-032 says such a claim "shall not
be presented as sourced", and the same reasoning as slice 005's severity split
applies: an unverifiable claim discarded before persistence has no representation
that could later reach a reader. Silently retiering it to `inference` would keep
a fabrication in the document with a softer label.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from careerhq.domain.schemas.research import (
    Claim,
    CompanyResearch,
    ResearchSection,
    RoleFinding,
    RoleResearch,
)

_WHITESPACE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Collapse whitespace runs. Nothing else — case and wording are preserved."""
    return _WHITESPACE.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class RejectedClaim:
    """One claim whose citation could not be verified, and why."""

    claim_id: str
    source_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CitationReport:
    """The checked research, plus the evidence that checking happened.

    `examined` is part of the result rather than something a caller infers from
    an empty `rejected` list. A checker that walked nothing would otherwise
    report a clean bill of health — the "gate with nothing to examine" failure
    this project has shipped four times.
    """

    research: CompanyResearch
    examined: int
    rejected: tuple[RejectedClaim, ...]


def _check_claim(claim: Claim, sources: Mapping[str, str]) -> tuple[int, list[RejectedClaim]]:
    """Verify one claim's excerpts. Returns how many were examined, and failures.

    Only claims carrying evidence are examined. An `inference` cites nothing by
    design (FR-029) and an `interpretation` rests on other claims rather than on
    a passage, so neither has an excerpt to check — and rejecting them for that
    would delete exactly the analysis the tiers exist to permit.
    """
    examined = 0
    failures: list[RejectedClaim] = []

    for evidence in claim.evidence:
        examined += 1
        page = sources.get(evidence.source_id)
        if page is None:
            failures.append(
                RejectedClaim(
                    claim_id=claim.id,
                    source_id=evidence.source_id,
                    reason=(
                        f"cites source {evidence.source_id!r}, which is not among the pages "
                        "CareerHQ retrieved; an unverifiable citation is not a citation"
                    ),
                )
            )
            continue
        if _normalise(evidence.excerpt) not in _normalise(page):
            failures.append(
                RejectedClaim(
                    claim_id=claim.id,
                    source_id=evidence.source_id,
                    reason="the quoted excerpt does not appear in the retrieved page",
                )
            )

    return examined, failures


def _check_section(
    section: ResearchSection, sources: Mapping[str, str]
) -> tuple[ResearchSection, int, list[RejectedClaim]]:
    examined = 0
    rejected: list[RejectedClaim] = []
    kept: list[Claim] = []

    for claim in section.claims:
        claim_examined, failures = _check_claim(claim, sources)
        examined += claim_examined
        if failures:
            rejected.extend(failures)
            continue
        kept.append(claim)

    if kept:
        return ResearchSection(claims=kept), examined, rejected

    # A section emptied by rejection must still explain itself: `ResearchSection`
    # requires a reason, and "we removed unverifiable claims" is a materially
    # different statement from "we found nothing".
    reason = section.empty_reason or (
        "Every claim in this section cited a source that could not be verified against "
        "the retrieved page, and was removed."
    )
    return ResearchSection(claims=[], empty_reason=reason), examined, rejected


def verify_excerpts(research: CompanyResearch, *, sources: Mapping[str, str]) -> CitationReport:
    """Check every excerpt in every section against the pages we retrieved.

    `sources` maps the source id given to the model onto the text CareerHQ
    fetched for it. Every section is walked — the five are separate fields, and a
    checker that covered one of them would pass a naive test while verifying
    almost nothing.
    """
    examined = 0
    rejected: list[RejectedClaim] = []
    checked: dict[str, ResearchSection] = {}

    for name in CompanyResearch.model_fields:
        section: ResearchSection = getattr(research, name)
        new_section, section_examined, section_rejected = _check_section(section, sources)
        checked[name] = new_section
        examined += section_examined
        rejected.extend(section_rejected)

    return CitationReport(
        research=CompanyResearch(**checked),
        examined=examined,
        rejected=tuple(rejected),
    )


@dataclass(frozen=True, slots=True)
class RoleCitationReport:
    """The Layer 2 counterpart of `CitationReport`.

    A separate type rather than a generic one because `research` is the useful
    field and it is a different schema in each layer; a union would push an
    `isinstance` check onto every caller to recover what the type already knew.
    `examined` is part of the result here for the identical reason — a checker
    that walked nothing must not be able to report a clean bill of health.
    """

    research: RoleResearch
    examined: int
    rejected: tuple[RejectedClaim, ...]


def verify_role_excerpts(
    research: RoleResearch, *, sources: Mapping[str, str]
) -> RoleCitationReport:
    """FR-032 for Layer 2, whose findings are a **variable list** of headings.

    The claim-level rule is Layer 1's, unchanged and deliberately shared: a
    second implementation of "does this excerpt appear in the page" is a second
    thing to get subtly different, and the two layers make the identical promise
    about citations. Only the traversal differs, because Layer 1 walks five named
    fields and Layer 2 walks a list whose length the model chose.

    A finding emptied by rejection keeps its heading and gains a reason. Dropping
    the heading would hide that the model *had* something to say there and it did
    not survive checking, which is a materially different statement from never
    having raised the subject.
    """
    examined = 0
    rejected: list[RejectedClaim] = []
    kept: list[RoleFinding] = []

    for finding in research.findings:
        section, section_examined, section_rejected = _check_section(
            ResearchSection(claims=finding.claims, empty_reason=finding.empty_reason), sources
        )
        examined += section_examined
        rejected.extend(section_rejected)
        kept.append(
            RoleFinding(
                heading=finding.heading,
                claims=section.claims,
                empty_reason=section.empty_reason,
            )
        )

    prep, prep_examined, prep_rejected = _check_section(research.interview_preparation, sources)
    examined += prep_examined
    rejected.extend(prep_rejected)

    # `no_findings_reason` is carried through unchanged: rejection empties a
    # finding, it never removes one, so a brief that had findings still has them.
    return RoleCitationReport(
        research=RoleResearch(
            findings=kept,
            no_findings_reason=research.no_findings_reason,
            interview_preparation=prep,
        ),
        examined=examined,
        rejected=tuple(rejected),
    )


__all__ = [
    "CitationReport",
    "RejectedClaim",
    "RoleCitationReport",
    "verify_excerpts",
    "verify_role_excerpts",
]
