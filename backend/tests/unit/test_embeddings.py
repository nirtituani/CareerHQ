"""T007/T008 — the embedding port, and the one adapter behind it.

**Nothing here fetches model weights, and one test enforces that.**
`FastEmbedSource.__init__` constructs no `TextEmbedding` at all: it performs a
registry width lookup and stores its arguments. This was not true when first
written — `fastembed`'s own `lazy_load=True` was assumed to defer the download
and does not, so the first version of this suite quietly pulled 64 MB, twice,
including a 768-dimension model it then rejected. The suite ran green in 14.75 s
and the only symptom was that number.

A unit suite that downloads from Hugging Face fails as flakiness rather than as
a design mistake, which is why the property is asserted rather than trusted.

Vectors that a model actually produced are checked in Docker at T047, against
the image where the weights are baked in — the environment the claim is about.
"""

from __future__ import annotations

import pathlib

import pytest

from careerhq.application.embeddings import EmbeddingSource
from careerhq.domain.models.knowledge import EMBEDDING_DIMENSIONS
from careerhq.infrastructure.embeddings import (
    EmbeddingDimensionMismatchError,
    FastEmbedSource,
)

#: Deliberately unwritable and outside any temp directory. Nothing in this
#: module may create it — see `test_construction_fetches_nothing`, which uses a
#: real `tmp_path` precisely so it can assert the directory stayed empty.
_UNUSED_CACHE = "/nonexistent/careerhq-embeddings-never-populated"


def test_the_adapter_satisfies_the_port() -> None:
    """The seam holds structurally, not by assertion in a docstring.

    `EmbeddingSource` is a `Protocol`, so this is checked by mypy at the
    assignment below rather than at runtime. Written as a test anyway so that
    the conformance is visible to a reader and so `mypy` has a call site to
    check — a Protocol nothing is ever assigned to constrains nothing.
    """
    source: EmbeddingSource = FastEmbedSource(
        model_name="BAAI/bge-small-en-v1.5",
        cache_dir=_UNUSED_CACHE,
        expected_dimensions=EMBEDDING_DIMENSIONS,
    )

    assert source.dimensions == EMBEDDING_DIMENSIONS


def test_a_model_of_the_wrong_width_is_refused_at_construction() -> None:
    """The schema commits to `vector(384)`; a wider model must not reach an INSERT.

    `BAAI/bge-base-en-v1.5` is a real model of the same family emitting 768
    dimensions — the realistic mistake is upgrading to a bigger sibling for
    quality, not typing a nonsense name. Left to PostgreSQL this surfaces
    during ingestion as a type error naming a column, with nothing to connect it
    to the configuration change that caused it.
    """
    with pytest.raises(EmbeddingDimensionMismatchError) as caught:
        FastEmbedSource(
            model_name="BAAI/bge-base-en-v1.5",
            cache_dir=_UNUSED_CACHE,
            expected_dimensions=EMBEDDING_DIMENSIONS,
        )

    message = str(caught.value)
    assert "768" in message, f"the error must name the width it found: {message}"
    assert "384" in message, f"the error must name the width required: {message}"
    assert "migration" in message, (
        f"the error must say what fixing it takes, not just that it is wrong: {message}"
    )


async def test_an_empty_batch_makes_no_model_call() -> None:
    """Ingestion of an unchanged corpus embeds nothing, and must cost nothing.

    Re-running ingestion is idempotent (FR-012), so the zero-work case is the
    common one rather than an edge. It returns before touching the model, which
    is also what lets this test run without weights.
    """
    source = FastEmbedSource(
        model_name="BAAI/bge-small-en-v1.5",
        cache_dir=_UNUSED_CACHE,
        expected_dimensions=EMBEDDING_DIMENSIONS,
    )

    assert await source.embed_passages([]) == []


def test_the_schema_width_is_what_the_configured_model_emits() -> None:
    """`EMBEDDING_DIMENSIONS` and the default model must not drift apart.

    They are declared in different files for good reasons — one is a schema
    commitment, the other a setting — and nothing connects them at import time.
    If the default model changes to another width, this fails here rather than
    at the first ingestion against a real database.
    """
    from careerhq.config import Settings

    default_model = Settings.model_fields["embedding_model"].default

    FastEmbedSource(
        model_name=default_model,
        cache_dir=_UNUSED_CACHE,
        expected_dimensions=EMBEDDING_DIMENSIONS,
    )


def test_construction_fetches_nothing(tmp_path: pathlib.Path) -> None:
    """Building the source must not touch the network or the disk.

    The guard for the mistake described in the module docstring. `warm_up()` is
    where the weights arrive, and that is the whole basis of SC-007's claim to
    exclude initialisation — a constructor that fetches has moved the cost back
    into whatever first calls it, silently.

    **Drill this by putting the `TextEmbedding(...)` call back in `__init__`.**
    The cache directory fills and this fails, which is what it looked like
    before.
    """
    cache = tmp_path / "cold"

    FastEmbedSource(
        model_name="BAAI/bge-small-en-v1.5",
        cache_dir=str(cache),
        expected_dimensions=EMBEDDING_DIMENSIONS,
    )

    assert not cache.exists() or not any(cache.rglob("*")), (
        "constructing FastEmbedSource wrote to the model cache; the weights must "
        "arrive in warm_up(), not on construction"
    )
