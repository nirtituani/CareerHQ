"""The AI gateway boundary.

**Principle V lives here.** `domain/` and `application/` must never import a
provider library; they depend on the `StructuredCompletion` Protocol in
`application/ports.py`, and only this package implements it. That is asserted by
a test over the import graph rather than left to review, because a rule someone
has to remember is not a boundary.

This module deliberately holds no provider imports itself — `litellm` is
imported by `litellm_gateway` alone, so importing this package (as readiness
does) does not drag the provider SDK into the import graph of everything.
"""

from __future__ import annotations

from careerhq.config import DependencyNotConfiguredError, get_settings

#: Providers this system knows how to build a client for. A name outside this
#: set is a configuration error worth catching at readiness rather than at the
#: first import, which is the only reason this check is not a tautology over
#: `ai_provider_configured`.
SUPPORTED_PROVIDERS = frozenset({"anthropic", "fixture"})


def build_completion_client() -> str:
    """Validate that a completion client can be built, and return the provider.

    Raises `DependencyNotConfiguredError` when the provider is absent or unknown.

    This performs **no network call**. Verifying the provider actually answers
    would bill a completion on every readiness check — and readiness is the
    platform's healthcheck, so it runs constantly. It would also let a provider
    outage block deployments of changes unrelated to the provider.

    What this does catch: a missing key, and a misspelled `AI_PROVIDER`. What it
    cannot catch: a key that is present and wrong. That is verified once against
    the deployed system by importing a real CV and confirming the recorded usage
    is not fixture data.
    """
    settings = get_settings()

    if not settings.ai_provider_configured:
        raise DependencyNotConfiguredError("AI provider", "ANTHROPIC_API_KEY")

    if settings.ai_provider not in SUPPORTED_PROVIDERS:
        raise DependencyNotConfiguredError(
            f"AI provider {settings.ai_provider!r}",
            f"AI_PROVIDER to one of {sorted(SUPPORTED_PROVIDERS)}",
        )

    return settings.ai_provider


__all__ = ["SUPPORTED_PROVIDERS", "build_completion_client"]
