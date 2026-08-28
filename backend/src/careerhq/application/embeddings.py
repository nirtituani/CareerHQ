"""Turning text into vectors, without the application layer knowing how.

The same move `ports.py` made for the provider seam and `guidelines.py` made for
the 005/006 boundary, for the same reason: retrieval needs an embedder, and the
use case that performs retrieval must not be the thing that decides *which*
embedder. `test_the_application_layer_imports_no_provider_sdk` enforces it, and
was widened in this slice to name the embedding runtimes explicitly — because
this seam is unusually easy to skip. `fastembed` needs no API key, bills nothing
and runs in-process, so importing it directly here would work perfectly and
leave no trace anywhere.

**Two methods, not one.** BGE models are documented as asymmetric — a passage is
embedded bare, a short query with an instruction prefix ("Represent this
sentence for searching relevant passages:") — and getting that wrong is silent:
the vector is the right width, from the right model, and simply retrieves worse.
Nothing a type check or a shape assertion would catch.

**Measured, because the documentation and the library disagree.** For
`BAAI/bge-small-en-v1.5`, fastembed's `query_embed`, `passage_embed` and `embed`
return **byte-identical vectors** (cosine 1.0, checked on 2026-08-27); it applies
no prefix for this model. So the split buys nothing *today* — it is kept because
it is the only place the distinction can later be made without a caller change,
and because a caller that has already collapsed the two cannot be un-collapsed
without finding every call site. Whether a prefix helps here is a retrieval
quality question with no measurement behind it yet; slice 007 is where that gets
answered, not this port.

**`dimensions` is on the port** because the width is a schema commitment, not a
detail: `knowledge_chunks.embedding` is `vector(384)` and migration `0015` says
in as many words that a model of a different width is another migration. An
adapter that disagrees should be refused at startup, where the message can name
the cause, rather than at the first INSERT, where PostgreSQL reports a type
error about a column nobody was thinking about.

**What this signature deliberately does not have**: a model name, a device, a
cache directory, a batch size, a normalisation flag. Those are one adapter's
vocabulary. `guidelines.py` makes the same refusal about `top_k` and scores, and
for the identical reason — a port that carries an implementation's parameters has
already chosen the implementation.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingSource(Protocol):
    """Text in, vectors out.

    Async because every caller is inside an async request or task, not because
    the work is IO. A local ONNX model is CPU-bound, so an implementation is
    expected to keep the event loop free itself rather than block it — that is
    an adapter's problem, and stating it here is what stops each caller
    inventing its own answer.
    """

    @property
    def dimensions(self) -> int:
        """The width of every vector this source returns.

        Compared against the column's width at startup. See the module
        docstring for why that comparison is not left to the database.
        """
        ...

    async def embed_passages(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Embed corpus text — the rules that get stored and searched over.

        Batched deliberately: ingestion embeds a whole corpus at once, and the
        per-call overhead of a local model is most of the cost at this size.
        """
        ...

    async def embed_query(self, text: str) -> Sequence[float]:
        """Embed a search query — what a retrieval asks *about* the corpus.

        Not the same operation as `embed_passages` on a one-element list. See
        the module docstring: the asymmetry is in the model, and getting it
        wrong is silent.
        """
        ...


__all__ = ["EmbeddingSource"]
