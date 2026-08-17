"""Reading a fetched page, with and without the model.

Two functions, tried in that order by `application/extract_job.py`:

* `json_ld_job_posting` — most applicant tracking systems (Greenhouse, Lever,
  Ashby, Workday, and anything chasing Google's job search) publish schema.org
  `JobPosting` data in the page. Where it exists it is **exact and free**: the
  employer wrote those fields, so there is nothing to infer and no completion to
  bill. That is why it is tried first rather than kept as a fallback.
* `html_to_text` — what the model reads when there is no such data.

HTML is parsed with the standard library's `HTMLParser` rather than a new
dependency. What is needed here is "drop the tags, keep the words", and the
model tolerates the imperfection that a full DOM parser would remove.
"""

from __future__ import annotations

import json
import re
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from careerhq.domain.schemas.job import JobPostingExtraction

#: Content that is in the markup but is not the page's words.
_SILENT_TAGS = frozenset({"script", "style", "noscript", "template", "svg", "head"})

#: Tags after which a line break belongs, so the text keeps its paragraphs.
#: A posting flattened to one line loses the bullet structure that makes it
#: readable — and that slice 004 tailors against.
_BREAKING_TAGS = frozenset(
    {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._silent = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in _SILENT_TAGS:
            self._silent += 1
        elif tag in _BREAKING_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SILENT_TAGS and self._silent:
            self._silent -= 1
        elif tag in _BREAKING_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._silent:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Strip a page to its readable words, keeping paragraph breaks."""
    extractor = _TextExtractor()
    extractor.feed(html)

    text = "".join(extractor.parts)
    # Non-breaking spaces read as words to a model and as gaps to a person.
    text = text.replace("\xa0", " ")
    # Collapse runs of blank lines, but keep one — the structure is the point.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return "\n".join(line.strip() for line in text.splitlines()).strip()


#: Three or more of these means the page shipped its template, not its content.
#: One is not enough — a posting for a templating job may legitimately mention
#: `{{ user.name }}`, and refusing that would be worse than the problem.
_PLACEHOLDER = re.compile(r"\{\{[^{}]{1,60}\}\}")
_MIN_PLACEHOLDERS = 3


def looks_unrendered(text: str) -> bool:
    """Whether `text` is a JavaScript template that was never filled in.

    Client-rendered job boards — Comeet among them — serve a shell whose
    content arrives later by fetch. Stripping that shell yields
    `{{position.name}} @ {{company.name}}` and little else, which a model will
    read and "extract" into an empty company, an empty title, and a
    requirements box full of placeholders.

    Detecting it turns a result that looks like a broken extraction into the one
    instruction that actually works: paste the posting text.
    """
    return len(_PLACEHOLDER.findall(text)) >= _MIN_PLACEHOLDERS


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every object in a JSON-LD document, however it is nested.

    Real pages wrap the posting in `@graph`, in a bare array, or inline it at
    the top level, and which one is a property of the vendor rather than of the
    standard. Walking makes that irrelevant.
    """
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found += _walk(value)
    elif isinstance(node, list):
        for item in node:
            found += _walk(item)
    return found


def _is_job_posting(node: dict[str, Any]) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return any(isinstance(k, str) and k.lower() == "jobposting" for k in kinds)


def _text(value: Any) -> str | None:
    """A JSON-LD value that may be a string, a dict, or a list of either."""
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, dict):
        for key in ("name", "value", "@value"):
            if key in value:
                return _text(value[key])
    if isinstance(value, list):
        for item in value:
            if found := _text(item):
                return found
    return None


def _location(node: dict[str, Any]) -> str | None:
    place = node.get("jobLocation")
    if isinstance(place, list):
        place = place[0] if place else None
    if not isinstance(place, dict):
        return _text(place)

    address = place.get("address")
    if isinstance(address, dict):
        parts = [
            _text(address.get(key))
            for key in ("addressLocality", "addressRegion", "addressCountry")
        ]
        if joined := ", ".join(part for part in parts if part):
            return joined
    return _text(address) or _text(place.get("name"))


def _salary(node: dict[str, Any]) -> str | None:
    """Salary as words, not numbers.

    Reassembled into the phrasing a person would write, because the field it
    lands in is free text by design — postings say "competitive" as readily as
    they say a range, and a numeric model cannot hold both.
    """
    base = node.get("baseSalary")
    if isinstance(base, str):
        return base.strip() or None
    if not isinstance(base, dict):
        return None

    currency = _text(base.get("currency")) or ""
    value = base.get("value")
    if isinstance(value, dict):
        low, high = value.get("minValue"), value.get("maxValue")
        unit = _text(value.get("unitText"))
        amount = (
            f"{low:,}-{high:,}"
            if isinstance(low, int | float) and isinstance(high, int | float)
            else _text(value.get("value"))
        )
        if not amount:
            return None
        return " ".join(part for part in (currency, str(amount), unit and unit.lower()) if part)
    return _text(value)


def _domain(node: dict[str, Any]) -> str | None:
    organisation = node.get("hiringOrganization")
    if not isinstance(organisation, dict):
        return None
    for key in ("sameAs", "url"):
        if raw := _text(organisation.get(key)):
            host = urlparse(raw if "//" in raw else f"//{raw}").hostname
            if host:
                return host.removeprefix("www.")
    return None


def json_ld_job_posting(html: str) -> JobPostingExtraction | None:
    """The posting's own structured data, or None if the page has none.

    None is not a failure — it is the signal to fall through to the model.
    """
    for raw in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            document = json.loads(unescape(raw.strip()))
        except (json.JSONDecodeError, ValueError):
            # A malformed block on a page is common and is not our problem; the
            # next block, or the model, may still work.
            continue

        for node in _walk(document):
            if not _is_job_posting(node):
                continue

            description = _text(node.get("description"))
            return JobPostingExtraction(
                job_title=_text(node.get("title")),
                company=_text(node.get("hiringOrganization")),
                company_domain=_domain(node),
                location=_location(node),
                salary_text=_salary(node),
                # The description is HTML even in here, near enough always.
                job_description=html_to_text(description) if description else None,
            )

    return None


__all__ = ["html_to_text", "json_ld_job_posting", "looks_unrendered"]
