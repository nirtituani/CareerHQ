FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the container healthcheck; the rest are build-time only and
# are not carried into the final layer beyond what pip needs at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Dependency layer: copy only the project definition first so that changing
# application code does not invalidate the (slow) dependency install.
COPY pyproject.toml README.md* ./
RUN mkdir -p src/careerhq && touch src/careerhq/__init__.py README.md \
    && pip install --no-cache-dir -e ".[dev]"

COPY . .

# Run as an unprivileged user. Nothing in the container needs root.
RUN useradd --create-home --uid 1000 careerhq \
    && chown -R careerhq:careerhq /app
USER careerhq

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
