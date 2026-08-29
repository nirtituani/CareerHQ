"""T013, T014, T015, T016, T017, T018, T027 — retrieval behind the `GuidelineSource` port.

The contract is `specs/006-document-retrieval/contracts/guideline-retrieval.md`. Every
invariant with a consumer today is asserted here: the port's shape, integrity pinning,
the FR-014 ceiling, citation identity across a changing corpus, the two fallback paths,
market precedence, and that guidance tracks the posting at all.

**Invariant 7 — market precedence — IS implemented** (T027, 2026-08-28), on a declared
`topic` list rather than on similarity. The earlier version of this docstring said the
opposite and was left behind when R13 reversed the decision. `research.md` R13 has the
measurement: cosine ranked the single true same-topic pair 326th of 504 cross-market
pairs, below the median, while ranking a pair the corpus review ruled *complementary*
first of all. No threshold orders them correctly, so the relation is declared, not
inferred — and precedence outranks without suppressing, because FR-038 says global
guidance remains applicable to Israeli CVs.

**Two embedding doubles, and they are not interchangeable.** `StubEmbedder` derives a
vector from a character sum: deterministic, which is what ordering and ceiling
assertions need, and blind to content, which is why T013 must not use it. See
`LexicalEmbedder` at the foot of the file.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import inspect
import logging
import math
import pathlib
import re
import zlib
from collections.abc import Sequence

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from careerhq.application.agents.tailoring.prompts import (
    _guidelines,
    build_draft_prompt,
    build_plan_prompt,
)
from careerhq.application.agents.tailoring.state import TailoringState
from careerhq.application.guidelines import (
    Guideline,
    GuidelineQuery,
    GuidelineSource,
    StaticGuidelines,
)
from careerhq.application.ingest_corpus import ingest_corpus
from careerhq.application.retrieved_guidelines import RetrievedGuideline, RetrievedGuidelines
from careerhq.domain.models.knowledge import KnowledgeChunk, KnowledgeDocument

pytestmark = pytest.mark.asyncio

_QUERY = GuidelineQuery(
    role_title="Senior Backend Engineer",
    requirements=("Python", "PostgreSQL", "distributed systems", "mentoring"),
)


class StubEmbedder:
    """Deterministic vectors, so ordering assertions are about the code, not the model.

    Every chunk gets a vector derived from its text; the query gets one derived from its
    own. Distances are therefore stable across runs, which is what lets determinism be
    asserted at all.
    """

    def __init__(self) -> None:
        self.queries: list[str] = []

    @property
    def dimensions(self) -> int:
        return 384

    @staticmethod
    def _vector(text: str) -> list[float]:
        seed = sum(ord(c) for c in text)
        return [((seed + i * 7) % 100) / 100.0 for i in range(384)]

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> Sequence[float]:
        self.queries.append(text)
        return self._vector(text)


class ExplodingEmbedder(StubEmbedder):
    async def embed_query(self, text: str) -> Sequence[float]:
        raise RuntimeError("embedding backend is down")


async def _ingested(session: AsyncSession) -> StubEmbedder:
    embedder = StubEmbedder()
    await ingest_corpus(session, embedder=embedder)
    return embedder


async def test_it_satisfies_the_port_unchanged(db_session: AsyncSession) -> None:
    """FR-002/FR-003. The 005/006 boundary holds or the slice has redesigned the workflow."""
    source: GuidelineSource = RetrievedGuidelines(
        db_session, embedder=StubEmbedder(), token_ceiling=1500
    )

    assert hasattr(source, "guidelines_for")


async def test_integrity_rules_are_always_returned_whatever_the_query(
    db_session: AsyncSession,
) -> None:
    """Contract invariant: integrity is product safety, not retrieved advice.

    A run whose posting is semantically distant from the idea of honesty is exactly the
    run that needs these, so they cannot be crowded out by a close semantic match.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)

    for query in (
        _QUERY,
        GuidelineQuery(role_title="Pastry Chef", requirements=("laminated dough",)),
    ):
        guidelines = await source.guidelines_for(context=query)
        integrity = [g for g in guidelines if "integrity" in g.source]
        assert len(integrity) == 15, (
            f"expected all 15 integrity rules pinned, got {len(integrity)} for {query.role_title}"
        )


async def test_integrity_rules_come_first(db_session: AsyncSession) -> None:
    """Ordering contract: integrity, then the rest, in the order the prompt renders them."""
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)

    guidelines = await source.guidelines_for(context=_QUERY)
    kinds = ["integrity" in g.source for g in guidelines]

    assert kinds[:15] == [True] * 15
    assert not any(kinds[15:]), "an integrity rule appeared after a non-integrity one"


async def test_total_tokens_respect_the_ceiling(db_session: AsyncSession) -> None:
    """FR-014, enforced from `token_count` rather than by re-tokenising."""
    embedder = await _ingested(db_session)

    for ceiling in (1500, 1000, 900):
        source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=ceiling)
        guidelines = await source.guidelines_for(context=_QUERY)
        used = sum(g.token_count for g in guidelines)
        assert used <= ceiling, f"ceiling {ceiling} exceeded: {used}"


async def test_the_pinned_set_is_never_dropped_to_fit_the_ceiling(
    db_session: AsyncSession,
) -> None:
    """The one case where the ceiling yields.

    Integrity is 795 tokens of the 1,500 budget. Under a ceiling too small to hold it,
    the honest failure is to return the safety rules and no advice — not to silently
    drop the rules that stop the model fabricating.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100)

    guidelines = await source.guidelines_for(context=_QUERY)

    assert len(guidelines) == 15
    assert all("integrity" in g.source for g in guidelines)


async def test_every_guideline_carries_a_resolvable_citation(
    db_session: AsyncSession,
) -> None:
    """FR-006. A citation resolves through slug + version + content hash.

    Recomputing the hash over the recorded text is what makes it *checkable* rather than
    merely present, so the hash has to travel.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)

    for guideline in await source.guidelines_for(context=_QUERY):
        assert guideline.document_slug
        assert guideline.document_version >= 1
        assert len(guideline.content_hash) == 64
        assert guideline.locator
        assert hashlib.sha256(guideline.text.encode()).hexdigest() == guideline.content_hash, (
            f"citation does not verify against its own text: {guideline.document_slug}"
        )
        assert guideline.document_slug in guideline.source


async def test_retrieval_is_deterministic(db_session: AsyncSession) -> None:
    """Same corpus, same query, same order — twice.

    Without a stable tie-break the order depends on whatever the database returns for
    equal distances, and slice 007 cannot compare two runs.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)

    first = await source.guidelines_for(context=_QUERY)
    second = await source.guidelines_for(context=_QUERY)

    assert [g.content_hash for g in first] == [g.content_hash for g in second]


async def test_an_empty_corpus_falls_back_and_records_it(db_session: AsyncSession) -> None:
    """FR-009. Empty corpus is a failure, not "no guidance"."""
    source = RetrievedGuidelines(db_session, embedder=StubEmbedder(), token_ceiling=1500)

    guidelines = await source.guidelines_for(context=_QUERY)

    assert guidelines == list(await StaticGuidelines().guidelines_for(context=_QUERY))
    assert source.last_fallback_reason == "empty_corpus"


async def test_a_retrieval_failure_never_fails_the_run(db_session: AsyncSession) -> None:
    """FR-010. The tailoring run continues on the static rubric."""
    await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=ExplodingEmbedder(), token_ceiling=1500)

    guidelines = await source.guidelines_for(context=_QUERY)

    assert guidelines == list(await StaticGuidelines().guidelines_for(context=_QUERY))
    assert source.last_fallback_reason == "retrieval_failed"


_ISRAEL = GuidelineQuery(
    role_title="Senior Backend Engineer",
    requirements=("Python", "PostgreSQL", "distributed systems", "mentoring"),
    market="israel",
)


def _find(guidelines: Sequence[Guideline], slug: str, locator: str) -> int:
    for i, g in enumerate(guidelines):
        if getattr(g, "document_slug", None) == slug and getattr(g, "locator", None) == locator:
            return i
    raise AssertionError(f"{slug} {locator} was not retrieved at all")


async def test_israeli_guidance_outranks_global_guidance_on_the_same_topic(
    db_session: AsyncSession,
) -> None:
    """FR-038, on the one live case — and it is the F4 pair R13 could not detect.

    Both documents declare `section-order`. Cosine put this pair 326th of 504; a declared
    topic makes it a set intersection, which either holds or does not.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100_000)

    guidelines = await source.guidelines_for(context=_ISRAEL)

    israeli = _find(guidelines, "israel-military-and-section-order", "rule 2")
    globalish = _find(guidelines, "universal-document-conventions", "rule 1")
    assert israeli < globalish, "Israeli section-order guidance must outrank the global rule"


async def test_precedence_orders_but_never_suppresses(db_session: AsyncSession) -> None:
    """*Outranks*, not *replaces*. The volunteering pair is the reason.

    The corpus review ruled `israel-military-and-section-order#5` and
    `universal-structure-and-ordering#4` **complementary** — one governs inclusion, the
    other presentation. Both share the `volunteering` topic, so precedence orders them;
    dropping either would discard evidence-backed guidance from a different institutional
    source.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100_000)

    guidelines = await source.guidelines_for(context=_ISRAEL)

    israeli = _find(guidelines, "israel-military-and-section-order", "rule 5")
    globalish = _find(guidelines, "universal-structure-and-ordering", "rule 4")
    assert israeli < globalish
    assert len(guidelines) == 79, "precedence must reorder, never drop"


async def test_precedence_leaves_unrelated_topics_alone(db_session: AsyncSession) -> None:
    """ "It does not outrank on unrelated topics" — the other half of invariant 7.

    **Asserted on the hoist itself, not on the surviving order of global chunks.** The
    first version of this test compared the relative order of global guidance between a
    global-market and an Israeli-market query, and a drill exposed it: removing the topic
    intersection entirely — hoisting *every* Israeli chunk above *every* global one —
    left that comparison unchanged, because inserting chunks between global entries does
    not reorder the global entries among themselves. The test passed the drill it existed
    to fail.

    So the assertion is on the *justification*: any Israeli chunk that moved up must now
    outrank at least one global chunk that shares a topic with it and that outranked it
    before. Jumping unrelated chunks on the way is unavoidable — outranking a related
    chunk at position 25 means passing everything between — so demanding otherwise, as a
    second draft of this test did, asks for something no implementation can satisfy.
    `israel-personal-details` declares `personal-details`, which no global document
    declares, so it must never move at all.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100_000)

    baseline = await source.guidelines_for(context=_QUERY)
    israeli_run = await source.guidelines_for(context=_ISRAEL)

    before = {g.content_hash: i for i, g in enumerate(baseline)}
    after = {g.content_hash: i for i, g in enumerate(israeli_run)}

    unjustified: list[str] = []
    for isr in israeli_run:
        if getattr(isr, "market", "global") != "israel":
            continue
        if after[isr.content_hash] >= before[isr.content_hash]:
            continue  # did not move up; nothing to justify

        # It moved. Somewhere it must now outrank a global chunk it shares a topic
        # with, and did not outrank before — that pair is the justification.
        justified = any(
            set(isr.topics) & set(getattr(other, "topics", ()))
            and before[other.content_hash] < before[isr.content_hash]
            and after[isr.content_hash] < after[other.content_hash]
            for other in israeli_run
            if getattr(other, "market", "global") == "global"
        )
        if not justified:
            unjustified.append(
                f"{isr.document_slug} {isr.locator} {isr.topics} was hoisted "
                f"{before[isr.content_hash] - after[isr.content_hash]} places, "
                "outranking no global chunk that shares a topic with it"
            )

    assert not unjustified, "precedence outranked on unrelated topics:\n  " + "\n  ".join(
        unjustified
    )


async def test_a_global_market_query_is_unaffected(db_session: AsyncSession) -> None:
    """Precedence is scoped "for Israeli-market CVs"; a global CV has no specific tier."""
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100_000)

    ordered = [g.content_hash for g in await source.guidelines_for(context=_QUERY)]
    again = [g.content_hash for g in await source.guidelines_for(context=_QUERY)]

    assert ordered == again
    israeli = [g.content_hash for g in await source.guidelines_for(context=_ISRAEL)]
    assert ordered != israeli, "the israel query should differ; otherwise precedence is inert"


async def test_precedence_is_deterministic_and_uses_no_threshold(
    db_session: AsyncSession,
) -> None:
    """Topic is a declared set intersection, so there is nothing to tune.

    R13 measured that no cosine threshold separates the labelled cases. If one is ever
    introduced it must arrive with new evidence and this assertion changes deliberately.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100_000)

    first = [g.content_hash for g in await source.guidelines_for(context=_ISRAEL)]
    second = [g.content_hash for g in await source.guidelines_for(context=_ISRAEL)]

    assert first == second
    assert not hasattr(source, "similarity_threshold")


async def test_chunks_at_an_equal_distance_are_ordered_by_content_hash(
    db_session: AsyncSession,
) -> None:
    """The tie-break, asserted directly rather than via determinism.

    **19 of the 79 chunks share a distance with another chunk** under the stub embedder,
    so the tie-break is load-bearing — but `test_retrieval_is_deterministic` cannot prove
    it. Removing the tie-break leaves that test passing, because PostgreSQL happens to
    return the same physical order for two calls inside one process. Incidental stability
    is not the same property as a defined order, and only one of them survives a vacuum,
    a re-ingestion, or a different plan.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=100_000)

    guidelines = await source.guidelines_for(context=_QUERY)
    ranked = [g for g in guidelines if "integrity" not in g.source]

    rows = (
        await db_session.execute(
            sa.select(
                KnowledgeChunk.content_hash,
                KnowledgeChunk.embedding.cosine_distance(
                    list(
                        await embedder.embed_query(
                            " ".join([_QUERY.role_title, *_QUERY.requirements])
                        )
                    )
                ).label("d"),
            )
        )
    ).all()
    distance = {r.content_hash: round(float(r.d), 12) for r in rows}

    groups: dict[float, list[str]] = {}
    for guideline in ranked:
        groups.setdefault(distance[guideline.content_hash], []).append(guideline.content_hash)

    tied = {d: hashes for d, hashes in groups.items() if len(hashes) > 1}
    assert tied, "no distance ties in this corpus; the tie-break would be unexercised"

    for d, hashes in tied.items():
        assert hashes == sorted(hashes), (
            f"chunks at distance {d} are not in content_hash order: {hashes}"
        )


# --------------------------------------------------------------------------------------
# T016 — citation identity across a changing corpus.
#
# The existing `test_every_guideline_carries_a_resolvable_citation` recomputes the hash
# over text that has not moved, which proves the hash is bound to the text but says
# nothing about the property FR-011 and FR-012 actually claim: that a citation recorded
# by an earlier run stays resolvable *after the corpus changes*, and that drift is loud
# rather than silent. These three exercise the corpus changing underneath a citation.
# --------------------------------------------------------------------------------------

_T016_DOC = """---
slug: t016-fixture
source_type: resume_best_practices
market: global
trust_level: internal
role_family: any
seniority: any
resume_section: any
topic: [experience-bullets]
origin_source_ids: []
---

# A citation-identity fixture

Preamble prose that must never become a chunk.

## Rules

- Lead each bullet with the outcome the work produced, because a reader scanning a
  column of bullets reads the first few words of each and nothing else.

- State the scale a system operated at where the profile records it, because scale is
  what distinguishes comparable-sounding work at two different employers.

- Name the technologies inside the bullet that used them rather than only in a skills
  list, because a reader judging depth wants to see where a tool was actually applied.
"""


@pytest.fixture
def t016_corpus(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "corpus"
    (root / "universal").mkdir(parents=True)
    (root / "universal" / "t016-fixture.md").write_text(_T016_DOC)
    return root


async def _cited(session: AsyncSession, root: pathlib.Path) -> list[RetrievedGuideline]:
    """Ingest the fixture corpus and return what retrieval cites for it."""
    embedder = StubEmbedder()
    await ingest_corpus(session, embedder=embedder, root=root)
    source = RetrievedGuidelines(session, embedder=embedder, token_ceiling=1500)
    retrieved = await source.guidelines_for(context=_QUERY)
    return [g for g in retrieved if isinstance(g, RetrievedGuideline)]


async def test_a_citation_still_resolves_after_an_unchanged_corpus_is_re_ingested(
    db_session: AsyncSession, t016_corpus: pathlib.Path
) -> None:
    """FR-012. Re-ingestion must not invalidate a citation an earlier run recorded.

    Content-addressed identity is what makes this true rather than hoped for, and it is
    the reason a positional or offset-based citation was rejected (D4): every one of
    those breaks on a re-ingestion that changed nothing.
    """
    before = await _cited(db_session, t016_corpus)
    assert len(before) == 3, f"fixture corpus should yield 3 chunks, got {len(before)}"

    after = await _cited(db_session, t016_corpus)

    assert {g.content_hash for g in after} == {g.content_hash for g in before}
    assert {g.document_version for g in after} == {1}, "an unchanged document must not bump"
    for cited in before:
        match = [g for g in after if g.content_hash == cited.content_hash]
        assert len(match) == 1
        assert match[0].text == cited.text, "re-ingestion rewrote the text under a live citation"
        assert match[0].locator == cited.locator


async def test_an_edited_rule_cannot_rewrite_what_an_earlier_run_was_advised(
    db_session: AsyncSession, t016_corpus: pathlib.Path
) -> None:
    """FR-011 and FR-012, the case the contract calls drift.

    Three separate claims, and the middle one is the loud part:

    1. The edited rule becomes a **new** chunk — a new hash, a bumped document version.
    2. The hash the earlier run recorded **no longer resolves in the corpus**. That miss
       is what makes a recorded citation checkable rather than decorative; if the edited
       text kept the old hash, a past run's advice would have been silently rewritten and
       nothing anywhere could tell.
    3. The earlier run's own snapshot still verifies against the hash it recorded, so
       what that run was advised remains resolvable after the corpus moved on.
    """
    before = await _cited(db_session, t016_corpus)
    recorded = next(g for g in before if g.locator == "rule 1")

    path = t016_corpus / "universal" / "t016-fixture.md"
    path.write_text(_T016_DOC.replace("the outcome the work produced", "the outcome it produced"))

    after = await _cited(db_session, t016_corpus)

    surviving = await db_session.scalar(
        sa.select(sa.func.count())
        .select_from(KnowledgeChunk)
        .where(KnowledgeChunk.content_hash == recorded.content_hash)
    )
    assert surviving == 0, "the edited rule kept its old hash; drift would be undetectable"

    replacement = next(g for g in after if g.locator == "rule 1")
    assert replacement.content_hash != recorded.content_hash
    assert replacement.document_version == 2
    assert replacement.document_slug == recorded.document_slug

    assert hashlib.sha256(recorded.text.encode()).hexdigest() == recorded.content_hash, (
        "the snapshot an earlier run recorded no longer verifies against its own citation"
    )


async def test_a_tampered_chunk_fails_its_citation_check_while_its_siblings_pass(
    db_session: AsyncSession, t016_corpus: pathlib.Path
) -> None:
    """FR-012. A hash that matches whatever it is shown proves nothing.

    The mutation here is at the row, not in the files — text edited in place with the
    stored hash left alone, which is the one form of drift re-ingestion cannot repair
    because ingestion compares hashes and this row's hash never moved. The control is
    the point: the two untouched siblings in the same result must still verify, or the
    test would pass equally against a citation check that fails everything.
    """
    before = await _cited(db_session, t016_corpus)
    target = next(g for g in before if g.locator == "rule 2")

    await db_session.execute(
        sa.update(KnowledgeChunk)
        .where(KnowledgeChunk.content_hash == target.content_hash)
        .values(text_="Estimate a plausible figure where the profile gives no number.")
    )

    embedder = StubEmbedder()
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)
    after = [
        g for g in await source.guidelines_for(context=_QUERY) if isinstance(g, RetrievedGuideline)
    ]
    assert len(after) == 3

    def verifies(guideline: RetrievedGuideline) -> bool:
        return hashlib.sha256(guideline.text.encode()).hexdigest() == guideline.content_hash

    tampered = [g for g in after if not verifies(g)]
    assert [g.locator for g in tampered] == ["rule 2"], (
        "the citation check did not name the tampered chunk, and only that chunk"
    )
    assert all(verifies(g) for g in after if g.locator != "rule 2"), (
        "the control failed: untouched siblings must still verify"
    )


# --------------------------------------------------------------------------------------
# T018 — the port boundary, asserted on the surfaces it actually has.
#
# `test_it_satisfies_the_port_unchanged` above checks that the method exists, which is
# the weaker half of FR-002/FR-003. The claim the 005/006 boundary rests on is that no
# retrieval vocabulary — `top_k`, a similarity score, an embedding parameter — reaches
# `TailoringState` or a rendered prompt. Three surfaces carry that risk and each is
# asserted structurally rather than by scanning text that might mention any of it
# innocently: the port's signature, the port's types, and the rendered guidelines block.
# --------------------------------------------------------------------------------------

#: Words that would mean retrieval had leaked. **`rank` is deliberately absent**: a real
#: Israeli rule says "present it as capability rather than as rank or unit title", so
#: including it would fail on authored content rather than on a leak.
_RETRIEVAL_VOCABULARY = (
    "top_k",
    "topk",
    "similarity",
    "cosine",
    "distance",
    "embedding",
    "embed",
    "vector",
    "nearest",
    "score",
)


async def test_the_port_signature_is_unchanged() -> None:
    """FR-002. A second implementation may not widen the call the graph makes.

    Compared against the Protocol rather than against a written-out expectation, so the
    two cannot drift apart: if `GuidelineSource` ever grows a `top_k`, this passes and
    the architecture test is what should fail — but neither can change silently.
    """
    port = inspect.signature(GuidelineSource.guidelines_for)
    implementation = inspect.signature(RetrievedGuidelines.guidelines_for)

    assert implementation == port, "the retrieval implementation widened the port"
    assert [p.name for p in port.parameters.values()] == ["self", "context"]
    assert port.parameters["context"].kind is inspect.Parameter.KEYWORD_ONLY


async def test_the_port_types_carry_no_retrieval_vocabulary() -> None:
    """FR-003, at the type surface a caller codes against.

    `Guideline` is what the port returns and what the prompt builders consume. Two
    fields, and neither is negotiable: widening it is how retrieval detail would reach a
    node input without anyone editing a node. `RetrievedGuideline`'s extra fields are
    fine precisely because they live on a **subclass** the port does not promise.
    """
    assert [f.name for f in dataclasses.fields(Guideline)] == ["text", "source"]

    for declared in (Guideline, GuidelineQuery):
        for f in dataclasses.fields(declared):
            assert not any(term in f.name for term in _RETRIEVAL_VOCABULARY), (
                f"{declared.__name__}.{f.name} is retrieval vocabulary on the port"
            )


async def test_no_retrieval_detail_reaches_the_state_or_the_rendered_prompt(
    db_session: AsyncSession,
) -> None:
    """FR-003, on the two surfaces a model can actually see.

    **Deliberately the worst case.** State is loaded with every field the retrieval
    implementation knows — `asdict` of the full `RetrievedGuideline`, not the two-key
    projection the use case builds — so what is proved is that the *prompt builder* is
    the boundary, not that the use case happens to project carefully today.

    **Scope**, per the rule this project has broken before: the forbidden-word scan runs
    over what the **renderer adds** to the rule text, never over rule text itself. A rule
    may legitimately say "rank"; the rendering around it may not say "cosine". Scanning
    the whole prompt for words that could appear innocently in authored guidance proves
    nothing and fails on content.

    ***Tightened 2026-08-29 (T052).*** The prompt used to render `- {text}  [{source}]`,
    and this test asserted that exact shape. The citation is no longer sent — it was 667
    of the retrieval block's 2,190 tokens and nothing read it — so the assertion is now
    that the block is the rule text **and nothing else at all**, which is strictly
    stronger than the claim it replaces. The scan below therefore examines the residue
    after every rule text is removed: if a metadata suffix ever returns, its words land
    there.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)
    retrieved = [
        g for g in await source.guidelines_for(context=_QUERY) if isinstance(g, RetrievedGuideline)
    ]
    assert len(retrieved) >= 15, f"nothing to examine: {len(retrieved)} guidelines retrieved"

    state = TailoringState(guidelines=[dataclasses.asdict(g) for g in retrieved])

    # The declared state key is still two strings per guideline. A key widened to carry
    # `RetrievedGuideline` itself would make every extra field reachable from any node.
    annotation = {f.name: f.type for f in dataclasses.fields(TailoringState)}["guidelines"]
    assert annotation == "list[dict[str, str]]"

    rendered = _guidelines(state)
    expected = "\n".join(f"- {g.text}" for g in retrieved)
    assert rendered == expected, "the prompt renders more than the guideline's text"

    # **The omission is of data that is present**, which is what makes this a gate rather
    # than a tautology: every guideline genuinely carries a citation and a hash, and
    # neither reaches the model. A corpus that happened to have empty citations would
    # satisfy an absence check while proving nothing.
    examined = 0
    for guideline in retrieved:
        assert guideline.source and guideline.content_hash, "nothing to omit"
        assert guideline.source not in rendered, "the citation reached the prompt"
        assert guideline.content_hash[:12] not in rendered, "a content hash reached the prompt"
        examined += 1
    assert examined == len(retrieved), f"examined {examined} of {len(retrieved)}"

    # Whatever the renderer adds around the rule text — today "- " and newlines. If a
    # metadata suffix is ever reintroduced, its vocabulary lands in this residue.
    residue = rendered
    for guideline in retrieved:
        residue = residue.replace(guideline.text, "")
    lowered = residue.lower()
    for term in _RETRIEVAL_VOCABULARY:
        assert term not in lowered, f"retrieval vocabulary in the rendering: {residue!r}"

    for build in (build_plan_prompt, build_draft_prompt):
        assert rendered in build(state), "the guidelines block is not what the prompt carries"


# --------------------------------------------------------------------------------------
# T013 — two postings in different disciplines return different guidance.
#
# `StubEmbedder` above cannot express this and must not be used for it. Its vector is a
# character sum, so "a different query selects a different set" would be arithmetic about
# the double rather than a property of retrieval: it would pass against an implementation
# that had no notion of what a posting says, as long as the number moved.
#
# `LexicalEmbedder` derives its vector from the **words in the text** — the hashing trick,
# L2-normalised — so the ranking it produces comes from overlap between the posting and
# the rule, which is the thing under test. It is emphatically not a semantic model, and
# the real one is not used here on purpose: the suite must not depend on model weights
# (T008 — the unit suite quietly downloaded them twice before that was fixed).
# --------------------------------------------------------------------------------------


class LexicalEmbedder:
    """A content-derived embedding: hashed bag of words, L2-normalised.

    `zlib.crc32` rather than `hash()`, which is salted per process — a randomised bucket
    would make the ordering differ between runs and the determinism claim meaningless.
    """

    @property
    def dimensions(self) -> int:
        return 384

    @staticmethod
    def _vector(text: str) -> list[float]:
        vector = [0.0] * 384
        for token in re.findall(r"[a-z]{3,}", text.lower()):
            vector[zlib.crc32(token.encode()) % 384] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> Sequence[float]:
        return self._vector(text)


_BACKEND = GuidelineQuery(
    role_title="Senior Backend Engineer",
    requirements=(
        "Python",
        "PostgreSQL",
        "distributed systems",
        "Kubernetes",
        "API design",
        "mentoring engineers",
    ),
)

_NURSE = GuidelineQuery(
    role_title="Registered Nurse",
    requirements=(
        "patient care",
        "clinical documentation",
        "medication administration",
        "shift handover",
        "intensive care unit",
    ),
)


async def test_two_postings_in_different_disciplines_get_different_guidance(
    db_session: AsyncSession,
) -> None:
    """FR-006. The whole argument for retrieval over a fixed rubric.

    **Measured** on the 79-rule corpus with `LexicalEmbedder`: 13 non-integrity rules for
    the backend posting, 12 for the nursing one, **1 in common**. The assertion is set at
    half rather than at that figure — the claim is that guidance tracks the posting, not
    that a particular pair of postings overlaps by exactly one rule, and pinning the exact
    number would make an unrelated corpus edit look like a regression.

    **Two controls**, because "the sets differ" is also what a broken implementation
    returning noise would produce: the 15 integrity rules must be *identical* across both
    postings, and each posting must return the same set twice.
    """
    embedder = LexicalEmbedder()
    await ingest_corpus(db_session, embedder=embedder)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)

    async def retrieve(query: GuidelineQuery) -> list[RetrievedGuideline]:
        return [
            g
            for g in await source.guidelines_for(context=query)
            if isinstance(g, RetrievedGuideline)
        ]

    backend = await retrieve(_BACKEND)
    nurse = await retrieve(_NURSE)

    def advice(guidelines: list[RetrievedGuideline]) -> set[str]:
        return {g.content_hash for g in guidelines if "integrity" not in g.source}

    def safety(guidelines: list[RetrievedGuideline]) -> set[str]:
        return {g.content_hash for g in guidelines if "integrity" in g.source}

    assert advice(backend) and advice(nurse), "nothing to compare: one posting got no advice"
    shared = advice(backend) & advice(nurse)
    assert shared != advice(backend), "both postings received identical guidance"
    assert len(shared) <= len(advice(backend)) // 2, (
        f"{len(shared)} of {len(advice(backend))} rules shared — guidance barely tracks the posting"
    )

    assert safety(backend) == safety(nurse) and len(safety(backend)) == 15, (
        "control failed: integrity is product safety and must not vary with the posting"
    )
    assert advice(await retrieve(_BACKEND)) == advice(backend), (
        "control failed: the same posting returned different advice on a second call"
    )

    for guideline in backend + nurse:
        assert hashlib.sha256(guideline.text.encode()).hexdigest() == guideline.content_hash
        assert guideline.document_slug in guideline.source


# --------------------------------------------------------------------------------------
# T029 — retrieval latency (FR-039, D6).
#
# SC-007 is a **measured** ≤500ms threshold, and a threshold nobody can measure is not a
# threshold. What is asserted here is the instrumentation, not the number: that every
# exit path records a duration, that the duration covers the whole operation rather than
# the database half of it, and that it reaches `extra={…}` — because Railway blanks the
# `message` field of parsed JSON logs, so a figure interpolated into the text is a figure
# that does not exist in production.
#
# **Model initialisation is out of the measurement by construction, not by subtraction.**
# `FastEmbedSource` defers loading and T030 gives `warm_up()` its caller; until that
# wiring lands, a cold first call would fold seconds of model load into this number.
# Recorded on T030 rather than worked around here.
# --------------------------------------------------------------------------------------


class SlowEmbedder(StubEmbedder):
    """Spends a known, unmissable amount of time inside `embed_query`.

    The point is scope: a timer wrapped around the SQL alone would report a plausible
    small number and miss the half of retrieval that actually costs — which is the shape
    of a latency metric that reassures without measuring.
    """

    DELAY_SECONDS = 0.06

    async def embed_query(self, text: str) -> Sequence[float]:
        await asyncio.sleep(self.DELAY_SECONDS)
        return await super().embed_query(text)


async def test_every_retrieval_path_records_its_duration(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """FR-039 on all three exits, because the two that matter most are the failures.

    A fallback still spent the time — an embedding backend that hangs and then raises is
    the case SC-007 exists to catch, and a metric recorded only on success is blind to
    exactly that.
    """
    embedder = await _ingested(db_session)

    succeeding = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)
    await succeeding.guidelines_for(context=_QUERY)
    assert succeeding.last_fallback_reason is None
    assert isinstance(succeeding.last_retrieval_ms, float) and succeeding.last_retrieval_ms > 0

    failing = RetrievedGuidelines(db_session, embedder=ExplodingEmbedder(), token_ceiling=1500)
    await failing.guidelines_for(context=_QUERY)
    assert failing.last_fallback_reason == "retrieval_failed"
    assert isinstance(failing.last_retrieval_ms, float) and failing.last_retrieval_ms > 0

    await db_session.execute(sa.delete(KnowledgeChunk))
    await db_session.execute(sa.delete(KnowledgeDocument))
    empty = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)
    caplog.set_level(logging.INFO, logger="careerhq.retrieval")
    caplog.clear()  # the failing call above already logged a warning
    await empty.guidelines_for(context=_QUERY)
    assert empty.last_fallback_reason == "empty_corpus"
    assert isinstance(empty.last_retrieval_ms, float) and empty.last_retrieval_ms > 0

    # One retrieval, one duration. This path logs twice — the selection, then the
    # decision to fall back — and the clock is stopped once, so both records must carry
    # the same figure. Two numbers for one operation is how a metric stops being one.
    durations = [
        r.duration_ms  # type: ignore[attr-defined]
        for r in caplog.records
        if r.name == "careerhq.retrieval" and hasattr(r, "duration_ms")
    ]
    assert len(durations) == 2, (
        f"expected two records on the empty-corpus path, got {len(durations)}"
    )
    assert durations[0] == durations[1] == empty.last_retrieval_ms


async def test_the_duration_covers_the_embedding_call_not_only_the_query(
    db_session: AsyncSession,
) -> None:
    """FR-039: *from retrieval start through the final selected set being returned.*

    Asserted against a floor well below the injected delay, never against a ceiling: a
    wall-clock measurement on a shared machine has no upper bound worth asserting, and a
    flaky timing test is one that gets deleted.
    """
    await _ingested(db_session)
    slow = SlowEmbedder()
    source = RetrievedGuidelines(db_session, embedder=slow, token_ceiling=1500)

    await source.guidelines_for(context=_QUERY)

    assert source.last_retrieval_ms is not None
    floor = SlowEmbedder.DELAY_SECONDS * 1000 * 0.8
    assert source.last_retrieval_ms >= floor, (
        f"{source.last_retrieval_ms:.1f}ms recorded for an operation that slept "
        f"{SlowEmbedder.DELAY_SECONDS * 1000:.0f}ms — the timer does not cover the embedding call"
    )


async def test_the_duration_is_reset_per_call_and_never_carried_forward(
    db_session: AsyncSession,
) -> None:
    """The same discipline `last_fallback_reason` already follows.

    A stale value is worse than a missing one: it reads as a measurement of the call you
    are looking at.
    """
    await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=SlowEmbedder(), token_ceiling=1500)
    await source.guidelines_for(context=_QUERY)
    slow_reading = source.last_retrieval_ms
    assert slow_reading is not None

    source._embedder = StubEmbedder()
    await source.guidelines_for(context=_QUERY)

    assert source.last_retrieval_ms is not None
    assert source.last_retrieval_ms < slow_reading, (
        "the second call reported the first call's duration"
    )


async def test_the_duration_is_logged_in_extra_not_in_the_message(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    """**Railway blanks the `message` field of parsed JSON logs.** Structured fields
    survive; the human-readable text does not. A duration interpolated into the message
    is a duration that does not exist in production, which is where SC-007 is measured.
    """
    embedder = await _ingested(db_session)
    source = RetrievedGuidelines(db_session, embedder=embedder, token_ceiling=1500)

    caplog.set_level(logging.INFO, logger="careerhq.retrieval")
    await source.guidelines_for(context=_QUERY)

    records = [r for r in caplog.records if r.name == "careerhq.retrieval"]
    assert len(records) == 1, f"expected one retrieval log record, got {len(records)}"
    record = records[0]

    assert hasattr(record, "duration_ms"), "the duration is not in extra={}"
    assert record.duration_ms == source.last_retrieval_ms  # type: ignore[attr-defined]
    assert "duration" not in record.getMessage(), (
        "the duration was interpolated into the message, which Railway blanks"
    )
