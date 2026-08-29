"""The guideline corpus: authored rules, their chunks, and their provenance.

**This holds writing *guidance*, never professional facts.** Profile content is
structured operational data and is retrieved relationally; only semantic
knowledge goes through vector search (Constitution VI, ADR-008,
`docs/03` §7.5). Embedding a profile here would produce approximate answers to
questions the database answers exactly.

Names follow `docs/03` §7 — `KnowledgeDocument`, `KnowledgeChunk`,
`ChunkMetadata` — rather than inventing parallel ones. Two fields that section
does *not* define are added, and both were surfaced by the corpus research:
``market`` (no geography dimension existed) and defined values for
``trust_level`` (the field existed with no vocabulary).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from careerhq.infrastructure.database import Base

#: `BAAI/bge-small-en-v1.5` through fastembed/ONNX emits 384 dimensions. This
#: is a **schema commitment**: changing the embedding model to one with a
#: different width is a migration, not a configuration change.
EMBEDDING_DIMENSIONS = 384


class Market(enum.StrEnum):
    """Which market's evidence supports a piece of guidance.

    **`GLOBAL` means the evidence is global — not that the guidance is
    inapplicable to Israel.** Global guidance applies to Israeli-market CVs.
    `ISRAEL` means the evidence specifically supports the Israeli market, and
    where authoritative Israeli evidence conflicts with global guidance the
    Israeli guidance wins for Israeli-market CVs (FR-038).

    Written out because the distinction is easy to invert on sight: ATS rules
    ship `GLOBAL` only because every ATS source found is a global vendor or a
    US university career centre, which is a statement about the *evidence*.
    Reading it as "ATS guidance does not apply in Israel" would suppress
    correct guidance for exactly the users this product targets.
    """

    GLOBAL = "global"
    ISRAEL = "israel"


class TrustLevel(enum.StrEnum):
    """How much standing the source behind a rule has.

    `docs/03` defined the field and left the vocabulary open. These are the
    values the corpus research settled on. Community and SEO-tier material does
    not reach the corpus at all, so has no value here.
    """

    #: CareerHQ-authored product rule. Integrity rules are ALWAYS this: they
    #: are safety obligations under Principle III, not advice to be sourced.
    INTERNAL = "internal"
    #: A government, academic or equivalent body.
    INSTITUTIONAL = "institutional"
    #: A vendor documenting its own product's behaviour.
    VENDOR_DOCUMENTED = "vendor_documented"
    #: A credible industry practitioner or publisher.
    INDUSTRY = "industry"


class SourceType(enum.StrEnum):
    """The corpus category a document belongs to."""

    RESUME_BEST_PRACTICES = "resume_best_practices"
    ATS_GUIDELINES = "ats_guidelines"
    DOMAIN_SPECIFIC = "domain_specific"
    SENIORITY = "seniority"
    INTEGRITY = "integrity"
    ISRAEL_MARKET = "israel_market"


class Topic(enum.StrEnum):
    """The subjects Corpus V1 actually covers. **Not a taxonomy of resume writing.**

    Every value here was read off the 79 authored rules; none was invented to round the
    list out, and there is no placeholder for a subject the corpus does not yet address.
    A vocabulary that describes more than the corpus contains cannot be checked against
    it, and the first wrong assignment would be invisible.

    **Topics are a list per document, not a scalar.** Two documents legitimately span two
    subjects each — `israel-military-and-section-order` covers military service *and*
    section ordering, `universal-document-conventions` covers section ordering *and* the
    factual role fields — because rules were grouped by **trust level**, which is a
    different axis. A scalar would have forced those files to split for a reason that has
    nothing to do with what they say.

    **This exists for exactly one consumer: FR-038 precedence.** `research.md` R13
    measured why it could not be derived instead — cosine similarity ranked the one true
    same-topic pair 326th of 504, below the median, while ranking a pair known to be
    complementary first of all. Topic is assigned by hand because the thing it encodes is
    "makes a claim about the same decision", which is a logical relation rather than a
    semantic-overlap one.
    """

    INTEGRITY = "integrity"
    ATS_PARSING = "ats-parsing"
    DOCUMENT_STRUCTURE = "document-structure"
    SECTION_ORDER = "section-order"
    EXPERIENCE_BULLETS = "experience-bullets"
    SKILLS = "skills"
    SUMMARY = "summary"
    PROFESSIONAL_TITLE = "professional-title"
    PROJECTS_EDUCATION = "projects-education"
    VOLUNTEERING = "volunteering"
    MILITARY_SERVICE = "military-service"
    PERSONAL_DETAILS = "personal-details"
    SENIORITY = "seniority"
    TECHNICAL_DEPTH = "technical-depth"
    SELECTION = "selection"
    VOCABULARY = "vocabulary"


class KnowledgeDocument(Base):
    """One authored corpus file.

    Curated only: the corpus is a version-controlled house asset reviewed like
    code, which is what makes "retrieved content is data, never instructions"
    (FR-013) a structural property rather than an aspiration. User-uploaded
    guideline documents are out of scope for this slice (D1).
    """

    __tablename__ = "knowledge_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    #: Stable natural key taken from the filename. **Never renamed** — a
    #: recorded citation resolves through it.
    slug: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    #: Bumped when content changes. Citations recorded against an earlier
    #: version stay resolvable (FR-012).
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    market: Mapped[str] = mapped_column(String(16), nullable=False)
    trust_level: Mapped[str] = mapped_column(String(24), nullable=False)
    #: Register IDs (`S-002`, …) the rules in this document derive from. The
    #: corpus is authored, so this records derivation rather than quotation.
    origin_source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    #: Archived documents are excluded from retrieval by default.
    #: Which embedding model produced this document's vectors (T053).
    #:
    #: **Nullable, and NULL means unknown rather than mismatched.** A corpus ingested
    #: before this column existed records nothing, and nothing can recover which model
    #: wrote those vectors. Refusing on NULL would strand a working deployment on a fact
    #: nobody has; stamping the configured model onto it would be worse, asserting in a
    #: column built to be trusted something that was never verified.
    #:
    #: **Not part of chunk identity.** `KnowledgeChunk.content_hash` stays a hash of the
    #: rule text alone (FR-012) — folding the model in would make every citation recorded
    #: by an earlier run unresolvable the moment the model changed, which is precisely
    #: what FR-012 forbids. This is a separate recorded fact so identity can stay textual.
    #:
    #: **Why a column at all**: `bge-small` and MiniLM are both 384-dimension, so
    #: `EMBEDDING_DIMENSIONS`, `vector(384)` and the adapter's registry width check all
    #: pass for either. Nothing else in the schema can tell them apart, and ingesting with
    #: one while querying with the other returns confident nonsense — measured at cosine
    #: **0.346** against **1.000** for the model that actually wrote the vector.
    embedding_model: Mapped[str | None] = mapped_column(String(128), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    chunks: Mapped[list[KnowledgeChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("market IN ('global', 'israel')", name="ck_knowledge_documents_market"),
        CheckConstraint(
            "trust_level IN ('internal', 'institutional', 'vendor_documented', 'industry')",
            name="ck_knowledge_documents_trust_level",
        ),
        CheckConstraint("version >= 1", name="ck_knowledge_documents_version"),
    )


class KnowledgeChunk(Base):
    """One authored rule — **and therefore one retrieval chunk** (FR-037).

    A rule's qualifications and exceptions are part of *its own text*, never a
    sibling chunk. This is forced by the content rather than chosen as a
    default: "military service can be a credibility signal" retrieved without
    "where relevant to the candidate and the role" is a materially different
    and worse instruction.

    Identity is the **content hash**, not a surrogate key or a position. That
    is what makes a citation checkable rather than merely present: recompute
    the hash over the recorded text and a match proves the guidance existed in
    the corpus unaltered, while a miss proves drift, loudly. It is also what
    lets re-ingestion be idempotent — unchanged text keeps its hash, and edited
    text becomes a new chunk, which is the honest outcome (FR-012).
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: SHA-256 over the normalised rule text. The citation identity.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The rule, INCLUDING its conditions.
    text_: Mapped[str] = mapped_column("text", Text, nullable=False)
    chunk_order: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Stored so the retrieval ceiling (FR-014) can be enforced without
    #: re-tokenising every candidate on every query.
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    #: `ChunkMetadata` — market, trust_level, role_family, seniority,
    #: resume_section, source_title, source_type, origin_source_ids.
    #:
    #: **`source_url` was listed here and was removed (T025).** An authored rule
    #: has no URL: the rule is CareerHQ's own words, and the URL belongs to the
    #: *evidence* it derives from. Three things made the field unfillable rather
    #: than merely empty — a document may cite several sources at once
    #: (`ats-fields-and-sections` cites three vendors, so a scalar cannot hold
    #: them), 22 of 79 rules are product judgement with no register entry and
    #: therefore no URL at all, and S-018's register entry carries a file path
    #: rather than a URL. `origin_source_ids` is the resolvable pointer and the
    #: source register is what resolves it; a per-chunk URL would have been a
    #: citation target invented to fill a column.
    #:
    #: **`topic` was listed here and is deferred to T027.** Its only consumer is
    #: the market-precedence rule — an `israel` chunk outranks a `global` chunk
    #: *on the same topic* — which T027 implements. Adding a hand-maintained
    #: topic taxonomy now would be a second classification of content the
    #: embeddings already classify, able to disagree with them silently, built
    #: before the consumer that would reveal which is right. That is designing
    #: T027 inside T025, which is the error `guidelines.py` names about `top_k`.
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        #: Idempotent ingestion depends on this: the same rule text in the same
        #: document cannot be stored twice.
        UniqueConstraint(
            "document_id", "content_hash", name="uq_knowledge_chunks_document_content"
        ),
        CheckConstraint("token_count > 0", name="ck_knowledge_chunks_token_count"),
        Index("ix_knowledge_chunks_document_id", "document_id"),
    )


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "Market",
    "SourceType",
    "Topic",
    "TrustLevel",
]
