"""S1 — what the batch fetch path must guarantee, beyond what `fetch_posting` did.

Slice 008 fetches **N machine-chosen URLs per run** instead of one URL a human
typed, and it *persists and displays* the URL it fetched as a citation. Two
properties follow that the single-URL path never needed:

* **The final post-redirect URL must come back to the caller.** `fetch_posting`
  maintained `current` correctly through every hop and then threw it away,
  returning only the body. A citation naming the *requested* URL when a redirect
  moved us elsewhere points at a page nobody read — and FR-032 would then be
  verifying an excerpt against a document the citation does not identify.

* **The address that was checked must be the address that is talked to.**
  `assert_fetchable` resolves a name and returns; `httpx` then resolves it again
  when it connects. Nothing carried the checked addresses forward, so a name
  whose A record is public at check time can answer `169.254.169.254` at connect
  time. That TOCTOU is on the shipped path today; slice 008 multiplies how often
  it is met, so this path verifies the peer it actually reached.

These tests use loopback and RFC 5737 documentation addresses rather than the
network. Nothing here makes an outbound request.
"""

from __future__ import annotations

import pytest

from careerhq.infrastructure.jobs.fetch import (
    Retrieved,
    UnsafeUrlError,
    assert_fetchable,
    fetch_posting,
    fetch_url,
)


class TestTheFinalUrlComesBack:
    """FR-008/FR-032: the citation must name the page we actually read."""

    def test_retrieved_carries_both_the_body_and_the_final_url(self) -> None:
        """A tuple would work; a named pair means a caller cannot swap them.

        `FetchedSource.url` is persisted and rendered as the citation, so the
        two values are not interchangeable and an accidental swap would be
        invisible until someone clicked a citation.
        """
        retrieved = Retrieved(url="https://example.com/final", body="<html></html>")
        assert retrieved.url == "https://example.com/final"
        assert retrieved.body == "<html></html>"

    def test_it_is_immutable(self) -> None:
        """The final URL is evidence about a completed fetch. Nothing downstream
        may quietly correct it to the one that was requested."""
        retrieved = Retrieved(url="https://example.com/final", body="x")
        with pytest.raises(Exception):  # noqa: B017 - frozen dataclass
            retrieved.url = "https://example.com/other"  # type: ignore[misc]


class TestTheOldEntryPointStillWorks:
    """`fetch_posting` has two callers and its own tests. It must keep its
    signature exactly — `str` in, `str` out — or S1 has broken slice 003."""

    def test_it_still_returns_a_plain_string(self) -> None:
        import inspect

        signature = inspect.signature(fetch_posting)
        assert list(signature.parameters) == ["url"]
        assert signature.return_annotation in ("str", str)

    def test_it_is_a_thin_wrapper_over_fetch_url(self) -> None:
        """Not a second implementation. A second SSRF implementation is a second
        thing to get wrong, which is the whole reason S1 exists as a shared
        coordination item rather than a slice-008 file."""
        source = inspect_source(fetch_posting)
        assert "fetch_url" in source, (
            "fetch_posting no longer delegates to fetch_url; the two paths have "
            "diverged and only one of them is being kept correct"
        )


def inspect_source(function: object) -> str:
    import inspect

    return inspect.getsource(function)  # type: ignore[arg-type]


class TestTheGuardIsUnchanged:
    """`assert_fetchable` is the security boundary and S1 must not weaken it.

    These duplicate a handful of `test_job_fetch.py` assertions on purpose: the
    batch path is new, and a guard that was quietly relaxed to make N URLs
    convenient is exactly the failure this slice was warned about.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://127.0.0.1/",
            "http://localhost:5432/",
            "http://10.0.0.1/",
            "file:///etc/passwd",
        ],
    )
    def test_the_guard_still_refuses_what_it_always_refused(self, url: str) -> None:
        with pytest.raises(UnsafeUrlError):
            assert_fetchable(url)

    def test_the_guard_returns_the_addresses_it_checked(self) -> None:
        """The change S1 needs: the checked addresses must be available to the
        connection, or checking them was advisory.

        `localhost` resolves to loopback and is refused, so this asserts the
        shape on a name that passes — using a literal so no DNS is involved.
        """
        checked = assert_fetchable("http://93.184.216.34/")
        assert checked, "assert_fetchable returned no addresses; nothing can be pinned"
        assert all(isinstance(address, str) for address in checked)

    def test_a_literal_public_address_is_its_own_checked_address(self) -> None:
        assert assert_fetchable("http://93.184.216.34/") == {"93.184.216.34"}


class TestThePeerIsVerified:
    """The rebinding window, closed at the point it actually matters.

    `_assert_peer_was_checked` is what runs after the connection is open and
    before any body is read. If DNS answered differently the second time, the
    address we reached is not in the set we approved, and the fetch is refused
    with the body still unread.
    """

    def test_a_peer_in_the_checked_set_is_accepted(self) -> None:
        from careerhq.infrastructure.jobs.fetch import _assert_peer_was_checked

        _assert_peer_was_checked("93.184.216.34", {"93.184.216.34", "93.184.216.35"})

    def test_a_peer_outside_the_checked_set_is_refused(self) -> None:
        """This is the rebinding case: the name resolved public at check time and
        answered something else when we connected."""
        from careerhq.infrastructure.jobs.fetch import _assert_peer_was_checked

        with pytest.raises(UnsafeUrlError):
            _assert_peer_was_checked("169.254.169.254", {"93.184.216.34"})

    def test_a_private_peer_is_refused_even_if_it_was_somehow_checked(self) -> None:
        """Defence in depth. If the checked set ever contained a private address
        — a bug in the guard, or a future edit — the peer check still refuses."""
        from careerhq.infrastructure.jobs.fetch import _assert_peer_was_checked

        with pytest.raises(UnsafeUrlError):
            _assert_peer_was_checked("127.0.0.1", {"127.0.0.1"})

    def test_an_unknown_peer_is_refused_rather_than_assumed_safe(self) -> None:
        """If the transport cannot tell us who it reached, we do not guess. An
        unverifiable connection is refused, not waved through."""
        from careerhq.infrastructure.jobs.fetch import _assert_peer_was_checked

        with pytest.raises(UnsafeUrlError):
            _assert_peer_was_checked(None, {"93.184.216.34"})

    def test_the_refusal_never_names_the_address_it_found(self) -> None:
        """The existing guard is deliberately vague — naming what it reached
        would make the guard a way of mapping the network. The peer check must
        keep that property rather than reintroducing the disclosure."""
        from careerhq.infrastructure.jobs.fetch import _assert_peer_was_checked

        with pytest.raises(UnsafeUrlError) as caught:
            _assert_peer_was_checked("10.1.2.3", {"93.184.216.34"})
        assert "10.1.2.3" not in str(caught.value)
        assert "93.184.216.34" not in str(caught.value)


class TestTheBatchBudget:
    """FR-004: a run is bounded by a configured number of sources, in code."""

    def test_fetch_url_takes_one_url(self) -> None:
        """The batch budget belongs to the *caller* — `research_company` already
        enforces `max_sources` — so this stays a single-URL primitive. A batch
        function here would put the same budget in two places, and the one that
        drifted would be the one nobody was watching."""
        import inspect

        assert list(inspect.signature(fetch_url).parameters) == ["url"]
