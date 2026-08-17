"""Comeet postings, which a plain fetch cannot read.

Comeet draws its job pages in the browser. Fetching one server-side returns
116KB of HTML that strips to 825 characters of `{{position.name}} @
{{company.name}}` — the template, never filled in. There is nothing on that page
for a model to read, and handing it one produces an empty company, an empty
title, and a requirements box full of placeholders.

**Worth a vendor adapter because Comeet is not a niche.** It is the dominant
applicant tracking system in Israeli tech hiring, which is this user's market,
so "paste the text instead" would be the answer to a large share of the postings
they actually add.

The route works because the page ships the credentials its own browser code uses:

1. The HTML embeds `company_uid` and a public `token`.
2. `careers-api/2.0/company/{uid}/positions/{position_uid}` returns the
   position's **metadata** — name, company, location — exactly, and free.
3. That response carries `url_active_page`: the *employer's own* careers page
   for the role, which is server-rendered and holds the body.

Step 3 is the part that is not obvious. Comeet's API does not return the
description at all, so the body has to come from the page Comeet points at
rather than from Comeet.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from careerhq.infrastructure.jobs.fetch import (
    TIMEOUT_SECONDS,
    USER_AGENT,
    JobFetchError,
    assert_fetchable,
)

logger = logging.getLogger("careerhq.jobs")

API_BASE = "https://www.comeet.co/careers-api/2.0"

#: `https://www.comeet.com/jobs/<slug>/<company_uid>/<position-slug>/<uid>`
_URL = re.compile(
    r"^https?://(?:www\.)?comeet\.(?:com|co)/jobs/[^/]+/(?P<company>[^/]+)/[^/]+/(?P<position>[^/?#]+)",
    re.IGNORECASE,
)

#: The public token the page hands its own client-side code.
_TOKEN = re.compile(r'"token"\s*:\s*"([A-Za-z0-9]+)"')


def is_comeet_url(url: str) -> bool:
    return _URL.match(url.strip()) is not None


def _identifiers(url: str) -> tuple[str, str] | None:
    match = _URL.match(url.strip())
    return (match.group("company"), match.group("position")) if match else None


async def fetch_comeet_posting(url: str, html: str) -> tuple[dict[str, Any], str | None]:
    """Return the position's metadata and the URL holding its body.

    `html` is the already-fetched shell — the token lives in it, so this does
    not fetch the page twice.

    Raises `JobFetchError` when the page is a Comeet URL whose identifiers or
    token cannot be found, because falling through to the model at that point
    would extract the template placeholders that made this module necessary.
    """
    identifiers = _identifiers(url)
    token_match = _TOKEN.search(html)

    if identifiers is None or token_match is None:
        raise JobFetchError(
            "This Comeet posting could not be read automatically. Paste the posting text instead."
        )

    company_uid, position_uid = identifiers
    api = f"{API_BASE}/company/{company_uid}/positions/{position_uid}?token={token_match.group(1)}"

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        try:
            response = await client.get(api)
            response.raise_for_status()
            position = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JobFetchError(
                "Comeet did not return this posting. Paste the posting text instead."
            ) from exc

    # The employer's own page for the role. Comeet's API has no description
    # field, so this is where the body has to come from.
    body_url = position.get("url_active_page") or position.get("url_detected_page")
    if body_url:
        try:
            # Re-guarded: this address comes from a third-party response, which
            # makes it exactly the kind of input the SSRF check exists for.
            assert_fetchable(str(body_url))
        except JobFetchError:
            logger.warning("comeet pointed at an unfetchable page", extra={"url": url})
            body_url = None

    logger.info(
        "comeet position resolved",
        extra={"company_uid": company_uid, "position_uid": position_uid, "body": bool(body_url)},
    )
    return position, str(body_url) if body_url else None


def metadata_from_position(position: dict[str, Any]) -> dict[str, str]:
    """The fields Comeet states outright, in the shape the extraction uses."""
    location = position.get("location")
    place = location.get("name") if isinstance(location, dict) else location

    fields = {
        "job_title": position.get("name"),
        "company": position.get("company_name"),
        "location": place,
    }
    return {key: str(value).strip() for key, value in fields.items() if value}


__all__ = [
    "API_BASE",
    "fetch_comeet_posting",
    "is_comeet_url",
    "metadata_from_position",
]
