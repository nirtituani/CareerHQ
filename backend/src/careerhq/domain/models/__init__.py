"""Domain models.

Business rules that must always hold are expressed as database constraints
rather than as application checks. A check in Python can be raced, forgotten by
the next endpoint, or bypassed by a migration script; a UNIQUE constraint
cannot.

This is a package rather than a module because slice 003 adds roughly a dozen
entities, and one file growing past a thousand lines makes review harder for no
benefit. Every name is re-exported here, so ``from careerhq.domain.models
import User`` keeps working exactly as it did — no import in slice 001 code
changed when this split happened.

SQLAlchemy needs every mapped class imported before ``Base.metadata`` is
complete, so importing this package is what registers the whole schema. That is
why the re-exports are load-bearing rather than a convenience.
"""

from careerhq.domain.models.application import (
    Application,
    ApplicationStatusHistory,
    Company,
    NormalizedStatus,
    normalize_company_name,
    normalize_status,
)
from careerhq.domain.models.identity import ProfessionalProfile, User
from careerhq.domain.models.imports import ExtractionItem, ImportedResume
from careerhq.domain.models.match import (
    MatchAnalysis,
    MatchBand,
    MatchRequirement,
    MatchStatus,
    RequirementKind,
    RequirementVerdict,
    Shortfall,
)
from careerhq.domain.models.profile import (
    Certification,
    ContactInformation,
    Education,
    ExperienceBullet,
    Language,
    MilitaryService,
    ProfessionalTitle,
    Project,
    ResumeProfile,
    Skill,
    SummaryBlock,
    VolunteerExperience,
    WorkExperience,
)
from careerhq.domain.models.provenance import ImportStatus, ItemDecision, Source
from careerhq.domain.models.tailoring import (
    IN_FLIGHT_STATUSES,
    FindingKind,
    ProposalDecision,
    ResumeVersion,
    ResumeVersionItem,
    ReviewerFinding,
    RunStatus,
    SourceKind,
    TailoringRun,
    VersionStatus,
)

__all__ = [
    "IN_FLIGHT_STATUSES",
    "Application",
    "ApplicationStatusHistory",
    "Certification",
    "Company",
    "ContactInformation",
    "Education",
    "ExperienceBullet",
    "ExtractionItem",
    "FindingKind",
    "ImportStatus",
    "ImportedResume",
    "ItemDecision",
    "Language",
    "MatchAnalysis",
    "MatchBand",
    "MatchRequirement",
    "MatchStatus",
    "MilitaryService",
    "NormalizedStatus",
    "ProfessionalProfile",
    "ProfessionalTitle",
    "Project",
    "ProposalDecision",
    "RequirementKind",
    "RequirementVerdict",
    "ResumeProfile",
    "ResumeVersion",
    "ResumeVersionItem",
    "ReviewerFinding",
    "RunStatus",
    "Shortfall",
    "Skill",
    "Source",
    "SourceKind",
    "SummaryBlock",
    "TailoringRun",
    "User",
    "VersionStatus",
    "VolunteerExperience",
    "WorkExperience",
    "normalize_company_name",
    "normalize_status",
]
