"""A `WebSearch` that answers from a script, keyed by query.

The sibling of `scripted_seam.py`, and it exists for the same reason: slice 008
reaches the public web, and a suite that needed the network would be neither
runnable in CI nor honest — a passing test would depend on what a search engine
happened to return that morning.

**Keyed by query, not by call order.** The queries Layer 1 issues are generated
deterministically from the company name and domain, so a test can name them
exactly; and asserting *which* query the application chose is the whole subject
of OQ-I, which asks whether role-query planning earns a model call. A double
keyed on order could not express that.

**An unscripted query is an error, never an empty list.** A silent empty result
would let a test pass while the application searched for something nobody
intended — the same class of false gate as a `-k` selector matching no tests and
printing a cheerful pass, which this project has shipped four times.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from careerhq.application.ports import SearchHit


class SearchScriptExhausted(AssertionError):
    """The application searched for something the script does not cover.

    An `AssertionError` rather than a `RuntimeError` because it means the test's
    expectation of the application was wrong — usually that query generation
    produced something other than what the test predicted, which is exactly the
    behaviour worth catching.
    """


@dataclass(slots=True)
class ScriptedSearch:
    """`WebSearch` that returns canned hits per query.

    Conforms structurally rather than by inheritance, so nothing under
    `application/` needs to know this exists.
    """

    #: Query string -> the hits it returns. An empty list is a valid answer and
    #: means "searched, found nothing" — distinct from "never asked".
    script: dict[str, Sequence[SearchHit]]

    queries: list[str] = field(default_factory=list)

    async def search(self, *, query: str, limit: int) -> list[SearchHit]:
        if query not in self.script:
            raise SearchScriptExhausted(
                f"the application searched for {query!r}, which the script does not cover. "
                f"Scripted queries: {sorted(self.script)}"
            )
        self.queries.append(query)
        # Honoured rather than ignored: `limit` is the run's source budget
        # (FR-004), and a double that overran it would hide a real overrun.
        return list(self.script[query])[:limit]

    @property
    def call_count(self) -> int:
        return len(self.queries)


__all__ = ["ScriptedSearch", "SearchScriptExhausted"]
