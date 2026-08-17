"""Fetching a job posting from a user-supplied URL.

**This is the only place CareerHQ fetches a URL a user typed**, and that makes
it the one place where server-side request forgery is possible. From inside the
compose network — and from inside Railway — `http://backend:8000`,
`http://pgvector.railway.internal:5432` and `http://169.254.169.254/` are all
one request away, and the response would be handed back to the user as an
"extracted job posting". `assert_fetchable` is therefore not a nicety; it is the
reason this module can exist at all.

The guard runs against the **resolved address**, not the hostname. Blocking
literal private IPs alone is theatre: `backend` is a hostname, and so is any
name an attacker controls and points at `127.0.0.1`.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

#: Only these. `file://` reads the container's disk and `data:` is not a fetch
#: at all — both are ways of turning this function into something else.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Refused before the body is read in full. A posting is text; anything this
#: large is not one, and reading it would be the memory-exhaustion half of the
#: same hole.
MAX_BYTES = 2 * 1024 * 1024

TIMEOUT_SECONDS = 15.0

#: Job boards serve different markup — or nothing at all — to something that
#: announces itself as a script. This is not evasion of a block: a site that
#: refuses us still refuses us, and that refusal is reported to the user as a
#: fetch failure rather than worked around.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36 CareerHQ/1.0"
)


class JobFetchError(RuntimeError):
    """The page could not be retrieved or was not usable.

    Carries a human explanation, because the interface offers the user a way
    forward — paste the text instead — and "we could not reach it" and "the site
    refused us" call for the same next step but different words.
    """


class UnsafeUrlError(JobFetchError):
    """The URL points somewhere this service must never request."""


def _is_public(address: str) -> bool:
    """Whether an IP is one we are willing to talk to.

    Everything non-global is refused in one check rather than by enumerating
    ranges: loopback, link-local (which is where cloud metadata lives), private,
    reserved, multicast and unspecified are all `is_global == False`.
    """
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


def assert_fetchable(url: str) -> None:
    """Raise `UnsafeUrlError` unless `url` is safe to request. No I/O but DNS."""
    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("Only http and https addresses can be opened.")

    host = parsed.hostname
    if not host:
        raise UnsafeUrlError("That does not look like a web address.")

    try:
        # Every address the name resolves to, because a name may return several
        # and a round-robin that includes one private address is still a hole.
        resolved = {str(info[4][0]) for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Could not find a server at {host}.") from exc

    if not resolved or not all(_is_public(address) for address in resolved):
        # Deliberately vague to the caller: naming which internal address was
        # reached would turn the guard into a way of mapping the network.
        raise UnsafeUrlError("That address is not reachable from CareerHQ.")


async def fetch_posting(url: str) -> str:
    """Return the HTML at `url`, or raise `JobFetchError` saying why not.

    Redirects are followed manually, one hop at a time, because a permitted URL
    that redirects to `169.254.169.254` would otherwise walk straight through
    the guard — the check has to run again on every hop, not only the first.
    """
    assert_fetchable(url)
    current = url

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
    ) as client:
        for _ in range(5):
            try:
                response = await client.get(current)
            except httpx.TimeoutException as exc:
                raise JobFetchError("The site took too long to respond.") from exc
            except httpx.HTTPError as exc:
                raise JobFetchError("Could not reach that address.") from exc

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise JobFetchError("The site redirected us nowhere.")
                current = str(httpx.URL(current).join(location))
                assert_fetchable(current)
                continue

            if response.status_code in (401, 403, 429, 999):
                # The common case, and not an error in our code. LinkedIn
                # answers 999 to anything that is not a browser session. The
                # interface turns this into "paste the text instead".
                raise JobFetchError(
                    "This site does not allow automated access. Paste the posting text instead."
                )
            if response.status_code >= 400:
                raise JobFetchError(f"The site returned an error ({response.status_code}).")

            if len(response.content) > MAX_BYTES:
                raise JobFetchError("That page is too large to read.")

            return response.text

    raise JobFetchError("That address redirected too many times.")


__all__ = [
    "ALLOWED_SCHEMES",
    "MAX_BYTES",
    "JobFetchError",
    "UnsafeUrlError",
    "assert_fetchable",
    "fetch_posting",
]
