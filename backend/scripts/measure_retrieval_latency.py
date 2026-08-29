"""SC-007 — measure steady-state retrieval latency. **Reads T029's instrumentation.**

    docker compose exec backend python scripts/measure_retrieval_latency.py

**It measures nothing itself.** Every figure below is `RetrievedGuidelines.last_retrieval_ms`,
the number FR-039 requires the system to record — *"so SC-007 can be measured rather than
derived"*. A stopwatch wrapped around the call here would be a second implementation of
the boundary, and the two would drift.

**Why a script and not a pytest gate.** The boundary SC-007 defines includes the embedding
call, so measuring it needs the real model — and the host venv has no model cache, so an
in-suite test would either download 90 MB over the network (which no test in this project
does) or stub the embedder, which is exactly the approximation that would let a real
regression hide. Run here, in the image that has the weights and against the ingested
corpus, is the only place the *actual* boundary can be measured. The assertions below are
what a gate would have contributed, and they run every time this does.

**What SC-007's boundary is, precisely** (FR-039, D6): from the start of the retrieval
operation to the final selected guideline set — query construction, `embed_query`, the
pgvector query, ranking, market precedence and ceiling selection — and **excluding
embedding-model initialisation**, which is startup overhead and is timed separately below
so that excluding it is a measurement rather than a claim.
"""

from __future__ import annotations

import asyncio
import statistics
import time

import sqlalchemy as sa

from careerhq.api.routes.tailoring import build_guideline_source
from careerhq.application.guidelines import GuidelineQuery
from careerhq.application.retrieved_guidelines import RetrievedGuideline, RetrievedGuidelines
from careerhq.application.tailor_resume import V1_TARGET_MARKET
from careerhq.config import get_settings
from careerhq.domain.models.knowledge import KnowledgeChunk
from careerhq.infrastructure.database import get_session_factory
from careerhq.infrastructure.embeddings import FastEmbedSource, get_embedding_source

#: Enough samples for a p95 to mean something, few enough to run in seconds.
SAMPLES = 30

#: Three postings of different shapes. One query would measure one embedding length and
#: one candidate ordering; the requirement is about runs in general.
QUERIES: list[tuple[str, list[str]]] = [
    (
        "Senior Backend Engineer",
        [
            "5+ years building production backend services in Python or Go",
            "Experience owning a payments or settlement domain end to end",
            "Strong SQL and data modelling; PostgreSQL preferred",
            "Comfortable with on-call and production ownership",
            "Hebrew and English, working proficiency",
        ],
    ),
    (
        "Data Platform Engineer",
        ["Airflow or Dagster in production", "dbt and warehouse modelling", "Kubernetes"],
    ),
    (
        "Engineering Manager, Infrastructure",
        [
            "Managed a team of 5-10 engineers",
            "Cloud cost ownership",
            "Hiring and performance management",
        ],
    ),
]


async def main() -> int:
    settings = get_settings()

    factory = get_session_factory()
    async with factory() as session:
        # **The corpus must actually be there.** An unpopulated corpus retrieves nothing,
        # falls back to the static rubric and would otherwise be measured as a very fast
        # retrieval — the exact reading this measurement was blocked on until T050.
        chunks = await session.scalar(sa.select(sa.func.count()).select_from(KnowledgeChunk))
        if not chunks:
            print("REFUSED: the corpus is empty. Run `python -m careerhq.ingest` first.")
            return 1

        # **The path `run_tailoring` uses**, built through the same seam rather than
        # constructed here — a measurement of a hand-assembled object is a measurement of
        # something nothing runs.
        source = build_guideline_source(session, settings)
        if not isinstance(source, RetrievedGuidelines):
            print(f"REFUSED: guideline_source={settings.guideline_source!r} is not retrieval.")
            return 1
        embedder: FastEmbedSource = get_embedding_source()
        # **Checked by name, not by `isinstance`.** The annotation already says
        # `FastEmbedSource`, so mypy proves an `isinstance` branch unreachable and deletes
        # the guarantee along with the dead code — while a stub embedder returning
        # instantly is exactly what would make this measurement meaningless. A name
        # comparison mypy cannot narrow keeps the check alive at run time.
        if type(embedder).__name__ != "FastEmbedSource" or embedder.dimensions != 384:
            print(f"REFUSED: {type(embedder).__name__} is not the real embedder.")
            return 1

        print(f"model    {settings.embedding_model}   cache {settings.embedding_cache_dir}")
        print(f"corpus   {chunks} chunks   ceiling {settings.retrieval_token_ceiling} tokens")

        # Initialisation, timed and reported **separately**. SC-007 excludes it, and the
        # only honest way to exclude something is to know what it costs.
        started = time.perf_counter()
        await embedder.warm_up()
        warm_ms = (time.perf_counter() - started) * 1000
        print(f"\ninitialisation, EXCLUDED from SC-007: warm_up {warm_ms:8.0f} ms")

        role, requirements = QUERIES[0]
        query = GuidelineQuery(role_title=role, requirements=requirements, market=V1_TARGET_MARKET)
        await source.guidelines_for(context=query)
        print(f"first call after warm-up, reported separately: {source.last_retrieval_ms:8.1f} ms")

        samples: list[float] = []
        selected_counts: set[int] = set()
        for index in range(SAMPLES):
            role, requirements = QUERIES[index % len(QUERIES)]
            selected = await source.guidelines_for(
                context=GuidelineQuery(
                    role_title=role, requirements=requirements, market=V1_TARGET_MARKET
                )
            )

            # **No sample may be a fallback.** A static rubric returns in microseconds, so
            # a run that fell back would improve this figure while measuring the thing
            # SC-007 exists to bound.
            if source.last_fallback_reason is not None:
                print(f"REFUSED: sample {index} fell back ({source.last_fallback_reason}).")
                return 1
            if not all(isinstance(g, RetrievedGuideline) for g in selected):
                print("REFUSED: a sample returned static guidance.")
                return 1
            assert source.last_retrieval_ms is not None
            samples.append(source.last_retrieval_ms)
            selected_counts.add(len(selected))

        # **The ceiling being exercised is the configured one**, read off the source
        # rather than off the settings a second time: a hard-coded 1,500 in
        # `build_guideline_source` would leave FR-014's limit looking configurable while
        # quietly not being, and this measurement would never notice.
        if source._ceiling != settings.retrieval_token_ceiling:
            print(f"REFUSED: the source is capped at {source._ceiling}, not the configured value.")
            return 1

        # Reported, **not** asserted against the ceiling — and a drill is why. At a
        # ceiling of 300 the selection came to 795 tokens, which looks like a violation
        # and is not one: the pinned integrity set is deliberately never trimmed to fit,
        # because safety rules and no advice is the honest outcome under a ceiling too
        # small to hold both. A refusal here would have been this script asserting the
        # opposite of the documented rule.
        tokens = sum(g.token_count for g in selected if isinstance(g, RetrievedGuideline))

    ordered = sorted(samples)
    percentile = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]

    print(f"\nsteady state, n={len(ordered)}   guidelines per call {sorted(selected_counts)}")
    print(f"  last selection {tokens} tokens of {settings.retrieval_token_ceiling}")
    print(f"  min  {min(ordered):8.1f} ms")
    print(f"  p50  {statistics.median(ordered):8.1f} ms")
    print(f"  p95  {percentile:8.1f} ms")
    print(f"  max  {max(ordered):8.1f} ms")
    print(f"  mean {statistics.fmean(ordered):8.1f} ms")

    verdict = "MET" if max(ordered) <= 500 else "MISSED"
    print(f"\nSC-007 (<= 500 ms, initialisation excluded): {verdict}")
    print(f"  worst sample {max(ordered):.1f} ms against a 500 ms threshold")
    return 0 if verdict == "MET" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
