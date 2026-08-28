"""`EmbeddingSource` over a local ONNX model, via fastembed.

The only module permitted to import fastembed, in the same way
`litellm_gateway.py` is the only one permitted to import litellm — and asserted
the same way, by `test_the_application_layer_imports_no_provider_sdk`.

**Nothing here reaches the network at request time.** The weights are ~64 MB of
ONNX on disk; `cache_dir` points at a directory baked into the image at build
time, so a cold container reads them rather than downloading them (spec.md D3).

**`fastembed`'s own `lazy_load=True` does not defer the download — measured.**
Constructing `TextEmbedding(..., lazy_load=True)` against an empty cache fetched
64 MB and took 4.8 s (2026-08-27); the flag defers building the ONNX *session*,
not fetching the files. So this class does the deferral itself: `__init__`
constructs nothing and only checks the width, and the model is built by
`warm_up()`. That is what makes "load at startup, not per call" (T008) true
rather than merely intended, and what keeps the unit suite off the network.

**The width is checked before anything is fetched.** The check used to run after
construction, which meant configuring a 768-dimension model downloaded it in
full and *then* rejected it. Ordering is the whole fix.

**The work is CPU-bound and runs off the event loop.** ONNX inference holds the
thread for its duration; called directly from a coroutine it would stall every
other request on the worker, and the symptom would be unrelated endpoints
getting slow whenever anyone tailors a resume. `asyncio.to_thread` keeps that
contained. It is also why the port is async while the library is not.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from fastembed import TextEmbedding

logger = logging.getLogger("careerhq.embeddings")


class EmbeddingDimensionMismatchError(RuntimeError):
    """The configured model does not emit the width the schema commits to.

    Raised at construction, before any weights are fetched.
    `knowledge_chunks.embedding` is `vector(384)`; a model of another width is a
    migration, not a configuration change, and migration `0015` says so. Left to
    the database, this surfaces during ingestion as a type error naming a
    column, long after the decision that caused it.
    """


class FastEmbedSource:
    """A local `BAAI/bge-small-en-v1.5` embedder.

    Constructed once and warmed once. Building the model per call would reload
    and re-initialise the ONNX session every time — the cost SC-007 explicitly
    excludes from its ≤500 ms budget *because* it is paid at startup, which is
    only true if something actually pays it there.
    """

    def __init__(self, *, model_name: str, cache_dir: str, expected_dimensions: int) -> None:
        # A registry lookup, not a probe embedding: it costs nothing, needs no
        # weights, and therefore refuses a wrong model *before* 64 MB of it is
        # downloaded. It must stay above everything else in this constructor.
        actual = TextEmbedding.get_embedding_size(model_name)
        if actual != expected_dimensions:
            raise EmbeddingDimensionMismatchError(
                f"embedding model {model_name!r} emits {actual} dimensions; "
                f"knowledge_chunks.embedding is vector({expected_dimensions}). "
                "Changing the model to another width requires a migration."
            )

        self._model_name = model_name
        self._cache_dir = cache_dir
        self._expected_dimensions = expected_dimensions
        self._model: TextEmbedding | None = None

    @property
    def dimensions(self) -> int:
        return self._expected_dimensions

    async def warm_up(self) -> None:
        """Build the model and load its weights now, so no request pays for it.

        Embeds one throwaway string, because constructing `TextEmbedding` fetches
        the files while the ONNX session is still built on first use. Asking the
        model to exist is not the same as asking it to work, and only the second
        one is what a request would otherwise wait for.
        """
        await asyncio.to_thread(lambda: list(self._loaded().embed(["warm up"])))
        logger.info(
            "embedding model ready",
            extra={"model": self._model_name, "dimensions": self._expected_dimensions},
        )

    def _loaded(self) -> TextEmbedding:
        """The model, built on first use.

        Not thread-safe, and deliberately not locked: two concurrent first calls
        would build two models and one would be discarded — wasteful for a few
        seconds, harmless afterwards, and impossible once `warm_up()` has run at
        startup, which is the intended path. A lock here would buy correctness
        the design already provides and hold a thread while a model loads.
        """
        if self._model is None:
            self._model = TextEmbedding(model_name=self._model_name, cache_dir=self._cache_dir)
        return self._model

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        if not texts:
            # Re-ingesting an unchanged corpus is idempotent (FR-012), so the
            # zero-work case is the common one. Returning here keeps it free —
            # and keeps it from looking like a model call in a log or a timing.
            return []
        return await asyncio.to_thread(self._embed_passages_sync, list(texts))

    async def embed_query(self, text: str) -> Sequence[float]:
        return await asyncio.to_thread(self._embed_query_sync, text)

    def _embed_passages_sync(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._loaded().passage_embed(texts)]

    def _embed_query_sync(self, text: str) -> list[float]:
        # `query_embed` returns a generator of one. Measured 2026-08-27: for
        # this model fastembed applies no query prefix, so this is currently
        # identical to `passage_embed` — see `application/embeddings.py` for why
        # the call is made through the query method anyway.
        # `list(map(float, ...))` rather than `.tolist()`: numpy's method is
        # untyped, so the return would be `Any` and mypy strict would stop
        # checking every caller of this function from here down.
        return list(map(float, next(iter(self._loaded().query_embed([text])))))


__all__ = ["EmbeddingDimensionMismatchError", "FastEmbedSource"]
