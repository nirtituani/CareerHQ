"""Does this job have posting content the analysis will actually read?

**One question, one answer, asked by everything that spends a completion.**

Match used to decide this twice and disagree with itself:
`create_pending_analysis` tested `application.requirements` while `run_analysis`
sent `application.job_description`. A job with requirements and no description
passed the gate, was sent an empty posting, and returned `0/100 ·
low_probability` carrying the model's own verdict — "No job posting content was
provided". It billed $0.007266 and read on screen as a judgement about the
person rather than about a missing field.

The content was there. It had been pasted into the requirements box, and nothing
sent it. A stricter gate would have refused that job too, and been just as wrong.

Tailoring had no equivalent check at all: a `ready` analysis was enough, so an
empty-posting score of 0 was a valid precondition for a five-call run.
"""

from __future__ import annotations

from typing import Protocol


class _HasPosting(Protocol):
    """Structural, so this stays testable without a database row."""

    job_description: str | None
    requirements: list[str] | None


def scoreable_posting(application: _HasPosting) -> str | None:
    """The posting text to analyse, or `None` when there is nothing to analyse.

    **`None` means no completion may be requested.** Both Match and Tailor read
    this before spending anything.

    Preference order, and the reasoning for each:

    1. **`requirements is None` is refused outright**, whatever the description
       says. That marks a row written before slice 004, whose `job_description`
       holds a joined requirements list rather than a posting (research R1).
       Scoring it compares the profile against that list while the prompt claims
       to be reading a whole advert, and the number that comes back looks
       entirely normal. This refusal predates the scoreability work and is
       preserved by it.
    2. **The description**, when it has content. It is the whole posting;
       `requirements` is a list extracted *from* it, so preferring the list would
       hand the model less than it already had.
    3. **The requirements**, composed, when there is no description. This is not
       substitution — it is reading a field the owner filled that the prompt had
       been ignoring.

    Composition **reformats and never adds**: each line is one stored
    requirement, bulleted. No heading, no framing sentence, nothing the owner did
    not type. A test walks the result and asserts every line traces to a stored
    value.
    """
    requirements = application.requirements
    if requirements is None:
        return None

    description = (application.job_description or "").strip()
    if description:
        return description

    lines = [line.strip() for line in requirements if line and line.strip()]
    if not lines:
        return None

    return "\n".join(f"- {line}" for line in lines)


__all__ = ["scoreable_posting"]
