"""What a job extraction stores, and why it stores both halves.

The reversal these tests pin down is recorded in
`specs/004-match-analysis/research.md` R1. Before slice 004, `extract_job`
joined the extracted requirements with newlines, stored *that* as
`job_description`, and discarded the posting body. One column held two
different kinds of content and nothing recorded which.

Match analysis scores against the whole posting, because the signal that
decides most matches is often stated outside a requirements section — "design
and operate services handling millions of requests per day" appears in no
requirements list and is exactly what makes a production backend history
relevant. So both halves are stored, and they serve different readers: the
posting is what gets scored, the list is what the person reads on the Details
tab.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import BaseModel

from careerhq.application.extract_job import extract_job_from_text
from careerhq.application.ports import Completion, Usage

_POSTING = """
About Acme
We are a company that does things, and we have done them since 2011.
Our team of forty engineers operates services handling millions of requests
per day across three continents.

What you'll do
Own the payments platform end to end.

Requirements
5+ years of Python
Experience with PostgreSQL
"""


class _Stub:
    """Returns the requirements a real model would find, and nothing else."""

    def __init__(self, requirements: list[str]) -> None:
        self._requirements = requirements

    async def complete[T: BaseModel](
        self, *, task: str, schema: type[T], prompt: str
    ) -> Completion[T]:
        return Completion(
            value=schema.model_validate({"requirements": self._requirements}),
            usage=Usage(model="stub", input_tokens=1, output_tokens=1, cost=Decimal("0")),
        )


@pytest.mark.asyncio
async def test_extraction_keeps_the_posting_and_the_requirements() -> None:
    """R1 — both halves survive, and the body is not thrown away.

    The failing assertion here before the fix was `job_description` holding
    "5+ years of Python\\nExperience with PostgreSQL" — the requirements list
    wearing the posting's name, with the 40-engineer scale sentence gone.
    """
    result = await extract_job_from_text(
        _POSTING, completion=_Stub(["5+ years of Python", "Experience with PostgreSQL"])
    )

    # The posting keeps everything, including the signal that lives outside the
    # requirements section and decides the match.
    assert "millions of requests" in (result.posting.job_description or "")
    assert "Own the payments platform" in (result.posting.job_description or "")

    # The requirements are their own field, not the description's contents.
    assert result.posting.requirements == ["5+ years of Python", "Experience with PostgreSQL"]

    # And the one must not be the other.
    assert result.posting.job_description != "\n".join(result.posting.requirements)


@pytest.mark.asyncio
async def test_a_posting_with_no_requirements_stores_an_empty_list_not_null() -> None:
    """`NULL` and `[]` are different facts and the legacy-row decision rests on it.

    `[]` means the posting was read and stated no requirements. `NULL` means no
    posting was ever captured — a row written before slice 004, whose
    `job_description` holds a joined requirements list rather than a posting.

    Those rows must never be scored: the prompt would claim to be reading a
    whole posting while receiving a requirements list, silently reinstating the
    requirements-only scoring R2 reversed, and the resulting number would look
    entirely normal. Collapsing these two cases removes the only thing that
    tells them apart.
    """
    result = await extract_job_from_text(_POSTING, completion=_Stub([]))

    assert result.posting.requirements == []
    assert result.posting.requirements is not None
    # The body is still stored — an empty requirement list is not an empty posting.
    assert "millions of requests" in (result.posting.job_description or "")
