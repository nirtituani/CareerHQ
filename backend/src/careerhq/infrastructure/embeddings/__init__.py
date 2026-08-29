"""The local embedding adapter, and the one instance of it the process shares.

See `fastembed_source.py` for why construction is deferred and what `warm_up()` buys.
"""

from functools import lru_cache

from careerhq.config import get_settings
from careerhq.domain.models.knowledge import EMBEDDING_DIMENSIONS
from careerhq.infrastructure.embeddings.fastembed_source import (
    EmbeddingDimensionMismatchError,
    FastEmbedSource,
)


@lru_cache
def get_embedding_source() -> FastEmbedSource:
    """The process-wide embedder. **One instance, warmed once** (T030).

    Cached for the same reason `get_engine` is: the expensive thing here is the ONNX
    session behind the model, and building a `FastEmbedSource` per run would reload it
    every time — the cost SC-007 excludes from its budget *because* it is paid at
    startup, which is only true if exactly one object pays it.

    The constructor is cheap and offline (a registry width check, no weights), so
    calling this before `warm_up()` costs nothing.
    """
    settings = get_settings()
    return FastEmbedSource(
        model_name=settings.embedding_model,
        cache_dir=settings.embedding_cache_dir,
        expected_dimensions=EMBEDDING_DIMENSIONS,
    )


__all__ = ["EmbeddingDimensionMismatchError", "FastEmbedSource", "get_embedding_source"]
