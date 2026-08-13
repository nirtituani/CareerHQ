"""Where a fact came from.

FR-004 requires user-verified facts to stay distinguishable from unverified
extraction — and it requires it **after** approval, not only during review. So
this travels with the data into the profile rather than being discarded at the
approval boundary, and every profile entity carries it.

The design language renders these as line treatments rather than colours:
`extracted` is a dashed rule (provisional), the other two are solid (affirmed).
That distinction survives greyscale and colour blindness, which colour alone
does not (docs/09 §5).
"""

from __future__ import annotations

import enum


class Source(enum.StrEnum):
    EXTRACTED = "extracted"
    USER_CORRECTED = "user_corrected"
    USER_ADDED = "user_added"


class ImportStatus(enum.StrEnum):
    """Lifecycle of one upload (data-model.md §5).

    `APPROVED` is terminal and is the only transition that writes profile data.
    `FAILED` carries an explanation and is shown as a failure — never as an
    empty review form, which would imply the CV was read and found to contain
    nothing (FR-008).
    """

    PENDING = "pending"
    EXTRACTED = "extracted"
    FAILED = "failed"
    APPROVED = "approved"
    DISCARDED = "discarded"


class ItemDecision(enum.StrEnum):
    """The reviewer's choice for one extracted item.

    Defaults to `PENDING` whatever the confidence. No score auto-accepts
    anything (FR-029) — Principle II admits no threshold, and "we were very sure
    about this one" is how an approval gate quietly stops being one.
    """

    PENDING = "pending"
    ACCEPTED = "accepted"
    DISCARDED = "discarded"


__all__ = ["ImportStatus", "ItemDecision", "Source"]
