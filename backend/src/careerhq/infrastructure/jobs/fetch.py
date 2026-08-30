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
from dataclasses import dataclass
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


def assert_fetchable(url: str) -> set[str]:
    """Raise `UnsafeUrlError` unless `url` is safe to request. No I/O but DNS.

    **Returns the addresses it checked**, so a caller can verify that the
    connection it later opens actually reached one of them. Resolving here and
    then connecting by name resolves *twice*, and a name that answered publicly
    the first time can answer `169.254.169.254` the second — a TOCTOU that has
    been on this path since it was written. Returning the set is what lets
    `fetch_url` close it. Existing callers ignore the value and are unaffected.
    """
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

    return resolved


def _assert_peer_was_checked(peer: str | None, checked: set[str]) -> None:
    """Refuse a connection that reached an address the guard never approved.

    The second half of the DNS-rebinding fix. `assert_fetchable` decides which
    addresses are acceptable; this runs once the socket is open and **before a
    single byte of body is read**, and refuses when the address actually reached
    is not among them.

    **An unknown peer is refused, not assumed safe.** If the transport cannot say
    who it connected to, the property cannot be verified — and an unverifiable
    connection is precisely the case this exists for.

    **The message names nothing**, matching `assert_fetchable`: saying which
    address was reached would turn the guard into a way to map the network.
    """
    if peer is None or peer not in checked or not _is_public(peer):
        raise UnsafeUrlError("That address is not reachable from CareerHQ.")


@dataclass(frozen=True, slots=True)
class Retrieved:
    """One page, and **the URL it actually came from**.

    `url` is the address after every redirect, not the one requested. Slice 008
    persists it as the citation a reader can click, so returning the requested
    URL for a page that redirected would name a document nobody read — and
    FR-032's verbatim check would then be verifying an excerpt against a page the
    citation does not identify.

    Frozen and named rather than a bare tuple: both fields are strings, and
    swapping them would stay silent until someone followed a citation.
    """

    url: str
    body: str


async def fetch_url(url: str) -> Retrieved:
    """Retrieve one page safely, and say **which URL it came from**.

    The whole of the guard runs here, and each part answers a specific way in:

    * `assert_fetchable` before the first request, and again on **every redirect
      hop** — a permitted URL that redirects to `169.254.169.254` would otherwise
      walk straight through a first-hop-only check.
    * the peer address is verified against the addresses that were approved,
      **while the connection is open and before any body is read**, which closes
      the rebinding window between resolving a name and connecting to it.
    * the returned `Retrieved.url` is `current` — the address after the last
      redirect — because that is the page that was actually read.

    Introduced for slice 008, which fetches machine-chosen URLs and *publishes*
    the URL it fetched as a citation. `fetch_posting` keeps its old signature and
    delegates here, so there is exactly one implementation of this guard.
    """
    checked = assert_fetchable(url)
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
                request = client.build_request("GET", current)
                # Streamed so the socket is still open when the peer is checked:
                # a completed response has already closed it, and the address
                # would then be unavailable exactly when it matters.
                response = await client.send(request, stream=True)
            except httpx.TimeoutException as exc:
                raise JobFetchError("The site took too long to respond.") from exc
            except httpx.HTTPError as exc:
                raise JobFetchError("Could not reach that address.") from exc

            try:
                stream = response.extensions.get("network_stream")
                peer = stream.get_extra_info("server_addr") if stream is not None else None
                _assert_peer_was_checked(peer[0] if peer else None, checked)

                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise JobFetchError("The site redirected us nowhere.")
                    current = str(httpx.URL(current).join(location))
                    # Re-checked per hop, and the new address set replaces the
                    # old one — the next connection is verified against where
                    # *this* hop said to go, not where the first one did.
                    checked = assert_fetchable(current)
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

                await response.aread()
                if len(response.content) > MAX_BYTES:
                    raise JobFetchError("That page is too large to read.")

                return Retrieved(url=current, body=response.text)
            finally:
                await response.aclose()

    raise JobFetchError("That address redirected too many times.")


async def fetch_posting(url: str) -> str:
    """Return the HTML at `url`, or raise `JobFetchError` saying why not.

    **Unchanged for its callers**, and deliberately a thin wrapper: slice 003's
    extraction path wants the body and has no use for the final URL, while slice
    008 needs both. Two entry points over one implementation, rather than two
    implementations — a second SSRF guard is a second thing to get wrong, which
    is why S1 was a coordination item instead of a slice-008 file.
    """
    return (await fetch_url(url)).body


__all__ = [
    "ALLOWED_SCHEMES",
    "MAX_BYTES",
    "JobFetchError",
    "Retrieved",
    "UnsafeUrlError",
    "assert_fetchable",
    "fetch_posting",
    "fetch_url",
]
