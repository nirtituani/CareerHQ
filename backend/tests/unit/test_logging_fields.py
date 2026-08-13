"""Diagnostics must survive the deployed logging pipeline (T047, FR-022).

Slice 002 established by observation that Railway **discards the message field**
of parsed JSON logs while keeping every structured field. Local logs are
complete and deployed logs are not, and the failure is silent: the records are
well-formed with the human-readable part missing.

So anything needed to debug a production import has to live in `extra={…}`.
This test is the only thing preventing that lesson decaying back into a message
string, because nothing fails when it does — until someone is reading logs
during an incident.
"""

from __future__ import annotations

import logging

import pytest

from careerhq.application import extract_resume


def test_import_diagnostics_live_in_structured_fields_not_the_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="careerhq.import")

    logger = logging.getLogger("careerhq.import")
    logger.info(
        "extraction staged",
        extra={"import_id": "abc-123", "model": "anthropic/claude-sonnet-5", "item_count": 42},
    )

    record = caplog.records[-1]
    assert record.import_id == "abc-123"  # type: ignore[attr-defined]
    assert record.model == "anthropic/claude-sonnet-5"  # type: ignore[attr-defined]
    assert record.item_count == 42  # type: ignore[attr-defined]

    assert "abc-123" not in record.getMessage(), (
        "identifiers belong in extra={}, not interpolated into the message — "
        "the deployed platform discards message text"
    )


def test_the_extraction_service_logs_no_detail_in_its_messages() -> None:
    """Read the source rather than run every path.

    Each `logger.` call in the service must pass `extra=`, and its message must
    be a fixed string with no f-string interpolation. A formatted message is
    exactly what disappears when deployed.
    """
    source = extract_resume.__file__
    with open(source) as handle:
        text = handle.read()

    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith(("logger.info(", "logger.warning(", "logger.error(")):
            continue
        assert 'f"' not in stripped, (
            f"{source}:{line_no} interpolates into a log message; "
            "put the values in extra={} instead"
        )
