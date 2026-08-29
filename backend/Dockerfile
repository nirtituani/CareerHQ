FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the container healthcheck; the rest are build-time only and
# are not carried into the final layer beyond what pip needs at runtime.
#
# The libpango/libcairo/libharfbuzz set is NOT build-time — WeasyPrint binds
# Pango, Cairo and GObject through cffi and loads them at IMPORT. Without them
# the backend fails on `import weasyprint` with a dlopen error naming
# libgobject-2.0-0, which reads as a code fault rather than a missing package.
# Slice 006, T049.
#
# `fonts-dejavu-core` is declared for a different reason and must not be dropped
# as redundant (T032, amending T049). The ATS template renders in DejaVu Sans,
# and **which font resolves decides the rendered bytes** — so FR-031's
# byte-determinism, and the stable checksum FR-021 builds on it, depend on this
# package being present. It already arrived *transitively* via the libraries
# above, which is exactly the problem: a base image that stopped pulling it would
# change the output of every export, and FR-031's own failure mode is that this
# "surfaces only on a re-export", after submissions exist. Declared, it is a
# guarantee; transitive, it was a coincidence.
# `tests/unit/test_export_determinism.py` fails if this line is removed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fonts-dejavu-core \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libcairo2 \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer: copy only the project definition first so that changing
# application code does not invalidate the (slow) dependency install.
COPY pyproject.toml README.md* ./
RUN mkdir -p src/careerhq && touch src/careerhq/__init__.py README.md \
    && pip install --no-cache-dir -e ".[dev]"

# Bake the embedding weights into the image (T008). ~64 MB of ONNX weights, fetched once
# at build time so a cold container never downloads from Hugging Face — spec.md
# D3 requires no network call in the retrieval path, and a cache directory that
# is merely *configured* satisfies that only until the first cold start. Placed
# above `COPY . .` so an application-code change does not re-fetch it.
#
# The path must match `Settings.embedding_cache_dir`, and the `chown` below is
# what makes it readable to the unprivileged user the container actually runs as.
RUN python -c "from fastembed import TextEmbedding; \
    TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/app/.model-cache')"

COPY . .

# Run as an unprivileged user. Nothing in the container needs root.
RUN useradd --create-home --uid 1000 careerhq \
    && chown -R careerhq:careerhq /app
USER careerhq

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
