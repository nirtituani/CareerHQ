"""API and domain schemas.

A package for the same reason as ``domain.models``: slice 003 adds the
extraction schema, which is large enough to deserve its own module, and every
existing name is re-exported so no slice 001 import changed.

Note the asymmetry with ``models``: these are Pydantic schemas describing what
crosses a boundary, and nothing registers them globally — the re-exports here
are a convenience, not a requirement of any framework.
"""

from careerhq.domain.schemas.extraction import (
    ExtractedBullet,
    ExtractedCertification,
    ExtractedContact,
    ExtractedEducation,
    ExtractedLanguage,
    ExtractedProject,
    ExtractedRole,
    ExtractedSkill,
    ExtractedSummary,
    ExtractedTitle,
    ResumeExtraction,
)
from careerhq.domain.schemas.identity import GoogleClaims, ProfileOut, UserOut

__all__ = [
    "ExtractedBullet",
    "ExtractedCertification",
    "ExtractedContact",
    "ExtractedEducation",
    "ExtractedLanguage",
    "ExtractedProject",
    "ExtractedRole",
    "ExtractedSkill",
    "ExtractedSummary",
    "ExtractedTitle",
    "GoogleClaims",
    "ProfileOut",
    "ResumeExtraction",
    "UserOut",
]
