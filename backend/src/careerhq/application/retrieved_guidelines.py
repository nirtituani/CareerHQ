"""Guidance retrieved from the corpus, behind the unchanged `GuidelineSource` port.

**This is the whole of what slice 006 changes about tailoring.** The workflow, the nodes,
their responsibilities, the state and the finalisation rules are exactly as slice 005
built them; only which implementation of `GuidelineSource` is wired in differs. Nothing in
the graph refers to where guidance came from, so nothing in the graph changes when the
answer does.

**Market precedence (contract invariant 7) is not implemented, and that is a measured
decision rather than an omission.** The rule is *"an `israel` chunk outranks a `global`
chunk on the same topic"*, and T025 deferred the topic question to this task with an
explicit test: can embedding similarity express "same topic" reliably and reviewably?

Measured — `research.md` R13, 79 chunks, 504 cross-market pairs:

* the one true same-topic pair (Israeli section ordering against the global section-order
  rule) scores **0.650**, ranking **326th of 504** — *below the median of 0.670*;
* the highest-scoring pair of all, **0.861**, is the volunteering pair the corpus review
  ruled **complementary**, where precedence must not fire;
* the negative therefore outranks the positive by 0.211, and at every threshold from 0.60
  to 0.85 the complementary pair is wrongly caught. At the only threshold that catches the
  true case, 435 of 504 pairs fire — 86% of them.

So no threshold orders the labelled cases correctly, and a threshold is what suppression
would need. **Retrieval therefore suppresses nothing**: both markets' guidance competes on
relevance and both may be returned. That is safe under FR-038, which states that global
guidance *remains applicable to Israeli-market CVs* — the cost of doing nothing is a
little redundancy, and the cost of a wrong threshold is suppressing correct guidance most
of the time. A `topic` field can be reconsidered with this measurement as its evidence.

**A second, independent blocker, recorded because it survives any topic field.**
`GuidelineQuery` carries `role_title`, `requirements` and `section` — **no market**. Even
with perfect topic detection, retrieval cannot tell whether the CV it is serving is an
Israeli-market one, and FR-038's precedence is explicitly scoped *"for Israeli-market
CVs"*. Precedence needs both a topic signal and a market on the query; today it has
neither.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.embeddings import EmbeddingSource
from careerhq.application.guidelines import Guideline, GuidelineQuery, StaticGuidelines
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument, SourceType

logger = logging.getLogger("careerhq.retrieval")


@dataclass(frozen=True, slots=True)
class RetrievedGuideline(Guideline):
    """A `Guideline` that also carries its citation in structured form.

    **A subclass rather than a change to `Guideline`.** The prompt builders consume `text`
    and `source` and must keep doing exactly that — widening the port's own type is the
    compounding node-input change the 005/006 boundary exists to prevent. Everything extra
    here exists for consumers that are not the prompt: FR-011's persistence of what a run
    was advised, and slice 007's retrieval-quality metric.

    `token_count` travels because the FR-014 ceiling is enforced from it. Re-tokenising
    every candidate at query time is exactly what storing the count avoids.
    """

    document_slug: str = ""
    market: str = "global"
    #: The document's standing — `internal`, `institutional`, `vendor_documented` or
    #: `industry`. Part of the recorded citation (`data-model.md`) rather than of
    #: selection: nothing ranks on it, but a reader asking *how much weight did this
    #: advice deserve* cannot answer it from a slug, and re-reading the corpus would
    #: give today's answer for a run advised under yesterday's tagging. F2 retagged a
    #: document's trust level without touching a rule, which is exactly that case.
    trust_level: str = ""
    topics: tuple[str, ...] = ()
    document_version: int = 1
    content_hash: str = ""
    locator: str = ""
    token_count: int = 0


def _citation(slug: str, version: int, locator: str, content_hash: str) -> str:
    """The one-line human-readable citation the prompt renders.

    Carries the hash prefix because a citation nobody can check is decoration; twelve hex
    characters is enough to find the chunk and short enough to read.
    """
    return f"{slug} v{version} · {locator} · {content_hash[:12]}"


def _apply_market_precedence(
    ranked: list[RetrievedGuideline], *, market: str
) -> list[RetrievedGuideline]:
    """FR-038: market-specific guidance outranks global guidance **on the same topic**.

    *Outranks*, not *replaces*. Nothing is suppressed — the corpus review established
    that an Israeli rule and a global rule can address one subject and still be
    complementary (the volunteering pair: one governs inclusion, the other presentation).
    Dropping either would discard evidence-backed guidance; ordering costs nothing.

    **Deterministic, and topic comes from the declared list — never from similarity.**
    R13 measured why: cosine ranked the one true same-topic pair 326th of 504 while
    ranking a known-complementary pair first, so no threshold ordered them correctly.
    Sharing a declared topic is a set intersection, which either holds or does not.

    **A single stable pass, and the minimality is deliberate.** Walking the
    relevance-ordered list and emitting any not-yet-emitted market-specific chunk that
    shares a topic *just before* the global chunk it outranks moves exactly the chunks the
    rule requires and leaves every other position untouched. The obvious alternative — a
    sort key that demotes every contested global chunk — also pushes them below
    *uncontested* global chunks, which is a ranking change FR-038 does not ask for.
    """
    if market == "global":
        # Precedence is scoped "for Israeli-market CVs". A global-market CV has no
        # market-specific tier, so relevance order stands untouched.
        return ranked

    specific = [g for g in ranked if g.market == market]
    if not specific:
        return ranked

    contested: set[str] = set()
    for guideline in specific:
        contested.update(guideline.topics)

    emitted: set[str] = set()
    out: list[RetrievedGuideline] = []
    for guideline in ranked:
        if guideline.content_hash in emitted:
            continue
        if guideline.market == "global" and contested.intersection(guideline.topics):
            for candidate in specific:
                if candidate.content_hash in emitted:
                    continue
                if candidate.topics and set(candidate.topics) & set(guideline.topics):
                    out.append(candidate)
                    emitted.add(candidate.content_hash)
        out.append(guideline)
        emitted.add(guideline.content_hash)

    return out


class RetrievedGuidelines:
    """Semantic selection over the corpus, with integrity pinned and a token ceiling."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        embedder: EmbeddingSource,
        token_ceiling: int,
        fallback: StaticGuidelines | None = None,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._ceiling = token_ceiling
        self._fallback = fallback or StaticGuidelines()
        #: Which fallback path was taken on the last call, or `None`. FR-009 and FR-010
        #: both require that falling back is *recorded*, not merely survived — a run that
        #: silently used the static rubric is indistinguishable from one that retrieved.
        self.last_fallback_reason: str | None = None
        #: How long the last call took, in milliseconds, or `None` before the first.
        #: FR-039: SC-007 is a **measured** ≤500ms threshold, and a threshold nobody can
        #: measure is not a threshold. An attribute rather than a new metrics pipeline —
        #: D6 scopes this to the one number and forbids observability infrastructure
        #: beyond it, and `last_fallback_reason` above already set the pattern.
        #:
        #: **Recorded on every exit, fallbacks included.** An embedding backend that
        #: hangs and then raises is precisely what SC-007 exists to catch, and a metric
        #: written only on success is blind to it.
        #:
        #: **Model initialisation is excluded by construction, not by subtraction.**
        #: `FastEmbedSource` defers loading, and T030 gives `warm_up()` its caller; until
        #: that wiring lands a cold first call folds seconds of model load into this
        #: number. That is a wiring dependency, recorded on T030, not something to
        #: correct for here — subtracting an estimate would make the figure derived,
        #: which is the word FR-039 exists to rule out.
        self.last_retrieval_ms: float | None = None

    def _record_duration(self, started: float) -> float:
        """Stop the clock once, so the attribute and the log record cannot disagree."""
        self.last_retrieval_ms = (time.perf_counter() - started) * 1000
        return self.last_retrieval_ms

    async def guidelines_for(self, *, context: GuidelineQuery) -> Sequence[Guideline]:
        self.last_fallback_reason = None
        # Cleared before the work, not after: a stale reading is worse than a missing one
        # because it reads as a measurement of the call in front of you.
        self.last_retrieval_ms = None
        started = time.perf_counter()
        try:
            retrieved = await self._retrieve(context, started)
        except Exception:
            # FR-010: retrieval must never fail a tailoring run. The exception is logged
            # with its type only; whatever the backend said goes in `extra`, never into
            # anything a client renders (the T090 rule).
            logger.warning(
                "retrieval failed; falling back to the static rubric",
                exc_info=True,
                extra={
                    "duration_ms": self._record_duration(started),
                    "fallback": "retrieval_failed",
                },
            )
            self.last_fallback_reason = "retrieval_failed"
            return list(await self._fallback.guidelines_for(context=context))

        if not retrieved:
            # FR-009. An empty corpus is a failure, not "there is no guidance" — the
            # difference matters because the second reading would let a broken ingestion
            # produce confident, unguided drafts.
            logger.warning(
                "corpus returned no guidance; falling back to the static rubric",
                # **Not re-timed.** `_retrieve` completed and stopped the clock; the
                # operation FR-039 measures ended when the selection was final, and the
                # decision to fall back happens after it. Stopping the clock a second
                # time here would put two different durations for one retrieval into two
                # log records.
                extra={"duration_ms": self.last_retrieval_ms, "fallback": "empty_corpus"},
            )
            self.last_fallback_reason = "empty_corpus"
            return list(await self._fallback.guidelines_for(context=context))

        return retrieved

    async def _retrieve(self, context: GuidelineQuery, started: float) -> list[Guideline]:
        query_text = " ".join([context.role_title, *context.requirements]).strip()
        vector = list(await self._embedder.embed_query(query_text))

        rows = (
            await self._session.execute(
                sa.select(
                    KnowledgeChunk.content_hash,
                    KnowledgeChunk.text_,
                    KnowledgeChunk.token_count,
                    KnowledgeChunk.chunk_order,
                    KnowledgeDocument.slug,
                    KnowledgeDocument.version,
                    KnowledgeDocument.source_type,
                    KnowledgeDocument.market,
                    KnowledgeDocument.trust_level,
                    KnowledgeChunk.meta["topic"].as_string().label("topic_json"),
                    KnowledgeChunk.embedding.cosine_distance(vector).label("distance"),
                )
                .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
                .where(KnowledgeDocument.is_active.is_(True))
                # `content_hash` is the tie-break, not decoration: equal distances
                # otherwise order by whatever the database happens to return, and slice
                # 007 cannot compare two runs that disagree about the order.
                .order_by(sa.text("distance ASC"), KnowledgeChunk.content_hash.asc())
            )
        ).all()

        pinned: list[RetrievedGuideline] = []
        ranked: list[RetrievedGuideline] = []
        for row in rows:
            guideline = RetrievedGuideline(
                text=row.text_,
                source=_citation(
                    row.slug, row.version, f"rule {row.chunk_order + 1}", row.content_hash
                ),
                document_slug=row.slug,
                document_version=row.version,
                content_hash=row.content_hash,
                locator=f"rule {row.chunk_order + 1}",
                token_count=row.token_count,
                market=row.market,
                trust_level=row.trust_level,
                topics=tuple(json.loads(row.topic_json or "[]")),
            )
            if row.source_type == SourceType.INTEGRITY.value:
                pinned.append(guideline)
            else:
                ranked.append(guideline)

        # Integrity is pinned in a stable order of its own. It is product safety rather
        # than retrieved advice, so its position must not move with the query — a set of
        # rules that reorders per posting is harder to review and gives slice 007 a
        # moving target.
        pinned.sort(key=lambda g: (g.document_slug, g.locator))

        ranked = _apply_market_precedence(ranked, market=context.market)

        selected: list[Guideline] = list(pinned)
        # **The pinned set is never trimmed to fit.** Under a ceiling too small to hold
        # it, the honest outcome is safety rules and no advice — dropping the rules that
        # stop the model fabricating in order to make room for style tips inverts what
        # the ceiling is for.
        budget = self._ceiling - sum(g.token_count for g in pinned)
        for guideline in ranked:
            if guideline.token_count > budget:
                continue
            selected.append(guideline)
            budget -= guideline.token_count

        logger.info(
            "guidelines retrieved",
            extra={
                # FR-039. In `extra`, never in the message: Railway blanks the `message`
                # field of parsed JSON logs, so a duration written into the text is a
                # duration that does not exist where SC-007 is measured.
                "duration_ms": self._record_duration(started),
                "pinned": len(pinned),
                "selected": len(selected),
                "candidates": len(rows),
                "tokens": sum(g.token_count for g in selected if isinstance(g, RetrievedGuideline)),
                "ceiling": self._ceiling,
            },
        )
        return selected


def citation_snapshot(guidelines: Sequence[Guideline]) -> list[dict[str, Any]]:
    """What a run was advised, frozen at the moment it was advised (FR-011, FR-012).

    **Written from the retrieved objects, never from `TailoringState`.** The state key is
    the prompt-facing representation and stays `list[dict[str, str]]` — widening it to
    carry seven fields would push retrieval detail through every node in order to reach
    the single line that writes a row, which is the compounding node-input change the
    005/006 boundary exists to prevent (FR-002, FR-003).

    **A snapshot, not a pointer.** The corpus is deliberately not insert-only — the
    review deleted two unsupported ATS claims — so a record holding only `content_hash`
    would resolve to nothing the moment a rule was corrected, and a past run would read
    as though it had been advised by a rule that no longer exists. The same pattern
    `ResumeVersionItem.original_text` already uses.

    **A guideline with no citation records none.** `StaticGuidelines` is a constant, not
    a corpus chunk; emitting empty strings to keep the shape uniform would write a record
    that fails its own hash verification and so is indistinguishable from the drift that
    verification exists to detect. A consumer tells the two apart by asking whether
    `content_hash` is present, which is the honest question.
    """
    snapshot: list[dict[str, Any]] = []
    for guideline in guidelines:
        entry: dict[str, Any] = {"text": guideline.text, "source": guideline.source}
        if isinstance(guideline, RetrievedGuideline):
            entry.update(
                document_slug=guideline.document_slug,
                document_version=guideline.document_version,
                content_hash=guideline.content_hash,
                locator=guideline.locator,
                market=guideline.market,
                trust_level=guideline.trust_level,
            )
        snapshot.append(entry)
    return snapshot


__all__ = ["RetrievedGuideline", "RetrievedGuidelines", "citation_snapshot"]
