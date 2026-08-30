"""The real `SourceFetcher`: retrieve one public page, through the shared guard.

**This is coordination item S1 discharged.** FR-015 requires slice 008 to fetch
through the *existing* SSRF guard rather than growing its own, and this module
does exactly that and nothing more — it calls `jobs.fetch.fetch_url`, which
performs the address check, re-runs it on every redirect hop, and verifies the
peer it actually reached before reading a byte of body. There is no `httpx`
import here, and a test asserts its absence: an adapter with its own client would
bypass all three protections in one step and nothing else would notice.

**What this adds on top of the guard** is only the shape slice 008 needs:

* the **final** URL travels back on `FetchedSource.url`, because that value is
  persisted and rendered as the citation a reader can click;
* HTML becomes text, because the model must never be sent markup (FR-005 is
  about not echoing pages back, and sending tags in would spend the same tokens
  for less signal);
* a failure becomes `None` rather than an exception.

**Why `None` rather than a raise.** A run reads up to `MAX_SOURCES` pages and one
of them being down is the ordinary case, not an error: `research_company` records
the URL in `failed_urls`, which is what makes FR-009's "attempted-and-failed, not
silently dropped" record exist. A raise would abandon the other five pages and
the money already spent on the run.

**An SSRF refusal is also `None`**, deliberately. Searching the open web will
occasionally surface a URL that resolves inward, and that is an expected outcome
of the feature rather than an incident. The guard refuses it, the run records it
as consulted-and-failed, and the brief is honest about how much it read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser

from careerhq.application.ports import FetchedSource
from careerhq.infrastructure.jobs.fetch import (
    JobFetchError,
    Retrieved,
    fetch_url,
)
from careerhq.infrastructure.jobs.parse import html_to_text, looks_unrendered

#: Below this, a page carries nothing worth citing. A source that contributes no
#: quotable text still occupies a slot in the run's budget, so refusing it early
#: leaves room for one that does.
MIN_USABLE_CHARACTERS = 120


class _Title(HTMLParser):
    """The contents of `<title>`, if the page has one.

    `html_to_text` deliberately drops `<head>`, so the title has to be read
    separately rather than recovered from the body text.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._inside = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside and self.title is None:
            self.title = data.strip() or None


def _title_of(html: str) -> str | None:
    parser = _Title()
    try:
        parser.feed(html)
    except Exception:
        return None
    return parser.title


@dataclass(frozen=True, slots=True)
class WebSourceFetcher:
    """`SourceFetcher` over the shared guard.

    `retrieve` is injected so a test can script the transport without patching a
    module global, and defaults to the real guarded fetch. It is **not** a
    configuration knob: anything substituted for it must uphold the same
    guarantees, which is why the default is asserted in a test.
    """

    retrieve: Callable[[str], Awaitable[Retrieved]] = field(default=fetch_url)

    async def fetch(self, *, url: str) -> FetchedSource | None:
        """Retrieve `url`, or `None` if it could not be read. Never raises for a
        fetch failure; a programming error still surfaces."""
        try:
            retrieved = await self.retrieve(url)
        except JobFetchError:
            # Covers `UnsafeUrlError` too, which subclasses it — a refused
            # address and an unreachable one are both "consulted, no content".
            return None

        text = html_to_text(retrieved.body).strip()

        # FR-017. A client-rendered board serves `{{position.name}}`; treating
        # that as content would put placeholders into a research brief, which
        # reads as a broken feature rather than as an unreadable page.
        if not text or looks_unrendered(text) or len(text) < MIN_USABLE_CHARACTERS:
            return None

        return FetchedSource(
            url=retrieved.url,
            title=_title_of(retrieved.body) or retrieved.url,
            text=text,
            # Assigned by the caller, which numbers sources per run. Left empty
            # here on purpose: an id minted by the adapter would be unique per
            # fetch rather than per run, and the model cites the run's numbering.
            source_id="",
        )


__all__ = ["MIN_USABLE_CHARACTERS", "WebSourceFetcher"]
