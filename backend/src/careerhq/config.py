"""Application configuration.

Every environment-specific value is read here and nowhere else. Fields without a
default are required: constructing ``Settings`` without them raises a
``ValidationError`` naming the missing field, which is what makes the container
fail at startup rather than at the first request that needs the value (FR-006).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_core import ErrorDetails
from pydantic_settings import BaseSettings, SettingsConfigDict


class DependencyNotConfiguredError(RuntimeError):
    """Raised when a client is requested for a dependency that is not configured.

    Optional configuration trades away the fail-fast property that a missing
    required field gives: the process no longer stops at startup naming the
    setting. This moves that failure to first use rather than losing it — a
    caller that reaches for an unconfigured cache gets an error naming the
    setting to add, not an `AttributeError` on `None` several frames away.
    """

    def __init__(self, dependency: str, setting: str) -> None:
        super().__init__(
            f"{dependency} is not configured — set {setting}. "
            f"It is optional by design and unset in environments that do not use it yet."
        )


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment or a local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Core ---------------------------------------------------------------
    environment: Literal["local", "production"] = "local"
    log_level: str = "INFO"

    # The origin the *browser* uses, which is not what the backend sees. The
    # frontend proxies /api/* to http://backend:8000, so a redirect URI derived
    # from the incoming request would be the internal Docker hostname — which
    # Google rejects, and rightly so.
    #
    # It is also configuration rather than something to infer from a Host
    # header: the value has to match what is registered in the Google Cloud
    # Console exactly, and a header an attacker controls should never decide
    # where users are sent after authenticating.
    public_base_url: str = "http://localhost:3000"

    # -- Database -----------------------------------------------------------
    database_url: str

    # -- Cache. Never a source of truth. ------------------------------------
    # Optional by design, on the same terms as the Google credentials below.
    # Nothing reads the cache until slice 003, but until slice 002 this was a
    # required field — so a deployment without Redis could not start at all,
    # rather than merely reporting the cache as absent. That put the platform's
    # ability to boot behind a dependency it never called
    # (specs/002-deployment/research.md R1).
    #
    # Unset means "not configured", which readiness reports as such rather than
    # probing. Do not supply a placeholder to fill the blank: the application
    # would believe it has a cache and fail at first use instead of at startup.
    redis_url: str | None = None

    # -- Object storage -----------------------------------------------------
    # Optional on the same terms. Set all four together or none of them; a
    # half-configured client is worse than an absent one.
    s3_endpoint_url: str | None = None
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_bucket: str | None = None
    s3_region: str = "us-east-1"

    # -- Authentication -----------------------------------------------------
    # Required, and a minimum length is enforced rather than merely required:
    # .env.example ships this key present but empty, so "required" alone would
    # accept an empty string and the application would sign session tokens with
    # nothing. Rejecting it here is the difference between a startup error and
    # a forgeable session.
    session_secret: SecretStr = Field(min_length=32)
    session_ttl_days: int = Field(default=7, ge=1, le=90)

    # Optional by design. Sign-in cannot work without them, but the platform
    # starts and reports healthy so the environment can be verified before a
    # Google Cloud OAuth client exists. The auth routes fail loudly when these
    # are unset rather than blocking startup for everyone.
    google_client_id: str | None = None
    google_client_secret: SecretStr | None = None

    # -- AI ------------------------------------------------------------------
    # Slice 003 turns the seam slice 001 declared into a real dependency: CV
    # extraction is one structured-output call through the gateway.
    #
    # `anthropic` is the default provider, so supplying a key is usually all
    # that is needed. `fixture` returns canned content for demos and must be
    # chosen EXPLICITLY — never selected by the absence of a key, because
    # silently returning canned content would mean a user uploads their real CV
    # and reviews someone else's career history (research.md R3).
    ai_provider: str = "anthropic"

    # LiteLLM provider/model naming. The default when a task has no specific
    # model configured.
    llm_provider_model: str = "anthropic/claude-opus-5"
    anthropic_api_key: SecretStr | None = None

    # Per-task model selection. Read by `model_for_task`, which is how the
    # gateway resolves a model from a task NAME rather than from the caller —
    # the property that lets slice 004 express docs/08 §3.2.3 (Sonnet to
    # analyze/draft/revise, Opus for the Reviewer and for a revision that has
    # already failed once) as configuration instead of as branches inside
    # workflow code.
    #: Sonnet by default, per docs/08 §3.2.3. Defaulted here rather than left to
    #: the environment because the fallback is `llm_provider_model`, which is
    #: Opus — so an unset variable silently costs roughly four times as much per
    #: import for no measurable gain. Measured on the sample CV: Opus $0.041,
    #: Sonnet a fraction of that, with identical bullet attribution.
    llm_model_cv_extraction: str = "anthropic/claude-sonnet-5"
    #: Sonnet for the same reason, and it runs less often than the name
    #: suggests: a posting that publishes schema.org `JobPosting` data is read
    #: straight from the page with no completion at all, which covers most
    #: applicant tracking systems.
    llm_model_job_extraction: str = "anthropic/claude-sonnet-5"
    #: Sonnet, per docs/08 §3.2.3's assignment of *analyze*. Defaulted in code
    #: rather than left to the environment for the same reason as the two above,
    #: and the margin here is the widest yet: research.md R8 measures $0.022 per
    #: job on Sonnet against $0.065 on the Opus fallback, on every job added
    #: whether or not it is ever opened. A hundred applications is the
    #: difference between $2.20 and $6.50, bought silently.
    llm_model_match_analysis: str = "anthropic/claude-sonnet-5"
    # -- Slice 005: the tailoring workflow, one entry per node ---------------
    #
    # docs/08 §3.2.3 fixes the model per node, and `model_for_task` is what
    # makes that configuration rather than a branch in workflow code. All five
    # are defaulted here for the reason the three above are: the fallback is
    # `llm_provider_model`, which is Opus, so a missing entry runs at roughly
    # 2.5x the price for no gain and says nothing while doing it. That has
    # already caught CV extraction once in this project.
    #
    # Worst case for one run is seven calls — plan, draft, review, revise,
    # review, revise, review — of which three are Opus reviews of a full draft.
    # The reviews dominate the bill (research.md R5).
    #: Sonnet. Deciding what to emphasise is judgement, but it is judgement
    #: against a fit assessment that already exists rather than from scratch.
    llm_model_tailor_plan: str = "anthropic/claude-sonnet-5"
    #: Sonnet, per docs/08 §3.2.3's assignment of *draft*: rewriting existing
    #: facts against a retrieved rubric.
    llm_model_tailor_draft: str = "anthropic/claude-sonnet-5"
    #: **Opus.** The hardest judgement in the system and the one whose failure
    #: is a release blocker — it decides whether a claim is grounded in the
    #: profile at all (Principle III, AI-008).
    llm_model_tailor_review: str = "anthropic/claude-opus-5"
    #: Sonnet for the first revision: usually mechanical.
    llm_model_tailor_revise: str = "anthropic/claude-sonnet-5"
    #: **Opus** for the second. A Sonnet revision that has already failed to
    #: clear an Opus reviewer once is unlikely to clear it on a retry with the
    #: same model, and that loop would burn attempts without converging. This
    #: is a separate task NAME rather than a branch on attempt count, which is
    #: what keeps the escalation in configuration (contracts O4).
    llm_model_tailor_revise_escalated: str = "anthropic/claude-opus-5"
    # -- Slice 008: company research -----------------------------------------
    #
    #: Sonnet. Layer 1 summarises retrieved pages and quotes them; it is
    #: output-heavy but the judgement is shallow — no grounding decision, no
    #: release-blocking verdict. Opus is reserved for the nodes whose failure is
    #: a blocker, which here is nothing: the citation guarantee is a
    #: deterministic string check, not a model's opinion (FR-032).
    #:
    #: Layer 2's tasks are not registered yet — that layer is not built.
    llm_model_research_synthesise_company: str = "anthropic/claude-sonnet-5"
    # Local by default so the stack runs with no API key. Anthropic has no
    # embeddings endpoint, which is why this is not an Anthropic model.
    #
    # Run through **fastembed/ONNX**, not sentence-transformers. Same 384
    # dimensions, so `vector(384)` is unchanged and no migration is needed —
    # but 67 MB instead of a 527 MB torch wheel on top of a 1 GB image, for a
    # component whose whole job is embedding ~95-130 short rules and one query.
    # The Hugging Face Inference API is deliberately NOT used: embeddings stay
    # local, need no key, and put no network call in the retrieval path
    # (spec.md D3).
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    #: Where the ONNX model is cached. Baked into the image at build time so a
    #: cold container does not download from Hugging Face on first request —
    #: which would put a network call in exactly the path D3 keeps local.
    embedding_cache_dir: str = "/app/.model-cache"

    #: Ceiling on retrieved guidance injected into a prompt (FR-014, D5).
    #: 1,500 tokens ≈ 3x the 507-token static rubric, and ~15% of the Draft
    #: prompt's input. Sized so integrity rules — which are always retrieved —
    #: can never be crowded out by a close semantic match.
    #:
    #: **This is a budget per run, not a corpus size.** It holds **≈19 rules**
    #: at the measured 76 tokens/rule (2026-08-28) — the corpus itself is
    #: 95-130 rules. An earlier comment here said "≈ 35 rules", derived at 42
    #: tokens/rule from the rubric, whose rules carry no qualifications; a
    #: corpus rule carries its own (FR-037) and is 1.8x longer.
    #:
    #: **Do not change this number on arithmetic.** D5's floor-upward sizing no
    #: longer fits inside it, which is recorded as an open consequence in
    #: `research.md` R6 and answered by T044's measurement, not by a guess.
    retrieval_token_ceiling: int = 1500
    #: Which `GuidelineSource` implementation is wired in. `static` is the
    #: slice-005 rubric and remains the documented fallback (FR-009), so it is
    #: not dead code.
    #:
    #: **A closed set, tightened at T030 from a bare `str`.** The seam is a
    #: two-way branch, so an unrecognised value would land on one side of it
    #: silently — and `statik` selecting *retrieval* is the worse direction:
    #: it is how SC-008's static baseline would be taken against retrieval and
    #: reported as a comparison. Refused here, where every other configuration
    #: error in this project surfaces.
    guideline_source: Literal["retrieval", "static"] = "retrieval"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def google_oauth_configured(self) -> bool:
        return self.google_client_id is not None and self.google_client_secret is not None

    # The two properties below are the sole input to which dependencies the
    # readiness endpoint probes. A dependency that is not configured is
    # reported as `not_configured` — never probed, and never reported healthy,
    # which would make the endpoint claim a result it did not produce.
    # See specs/002-deployment/contracts/readiness.md.

    @property
    def ai_provider_configured(self) -> bool:
        """Whether extraction can run at all.

        Fixture mode needs no credentials; every real provider does. Absence is
        a legitimate deployment state — readiness reports `not_configured` and
        the import endpoint fails at the point of use naming the setting, which
        is what keeps `docker compose up` working on a clean clone before any
        provider account exists (docs/06 §7, FR-028).
        """
        if self.ai_provider == "fixture":
            return True
        return self.anthropic_api_key is not None

    def model_for_task(self, task: str) -> str:
        """Resolve the model for a named task.

        Callers name what they are doing, never which model does it. An unknown
        task falls back to the default rather than raising, so a new task name
        works before someone remembers to configure one for it — the failure
        mode of raising here would be a workflow that breaks on a name it has
        never seen (contracts/extraction-seam.md O3).
        """
        configured = getattr(self, f"llm_model_{task}", None)
        if isinstance(configured, str) and configured:
            return configured
        return self.llm_provider_model

    @property
    def cache_configured(self) -> bool:
        return self.redis_url is not None

    @property
    def object_storage_configured(self) -> bool:
        """All four settings, not any of them.

        A client built from a partial configuration fails at call time with an
        error about credentials rather than about configuration, which sends
        the reader to the wrong place.
        """
        return None not in (
            self.s3_endpoint_url,
            self.s3_access_key,
            self.s3_secret_key,
            self.s3_bucket,
        )


def _secret_fields() -> frozenset[str]:
    """Field names whose values must never appear in an error message.

    Derived from the annotations rather than listed by hand, so a secret added
    later is covered without anyone remembering to update this.
    """
    return frozenset(
        name
        for name, field in Settings.model_fields.items()
        if field.annotation in (SecretStr, SecretStr | None)
    )


def _describe(error: ErrorDetails, secrets: frozenset[str]) -> str:
    """One line per invalid field, with the value withheld when it is a secret.

    Pydantic puts the rejected input in its own message — `input_value='...'` —
    which for SESSION_SECRET means the secret itself is printed by the crash
    that was supposed to protect it (T068).
    """
    field = ".".join(str(part) for part in error["loc"]) or "(root)"
    if field in secrets:
        return f"{field}: {error['type']}"
    return f"{field}: {error['type']} — {error['msg']}"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings, constructed once.

    Cached so that configuration is read and validated a single time, and so
    tests can clear the cache to substitute a different environment.

    A validation failure is re-raised with the offending values stripped. The
    operator still learns which field is wrong and why — that is the whole point
    of failing at startup (FR-006) — but a rejected secret does not travel into
    the container log on its way out.
    """
    try:
        return Settings()  # values are supplied by the environment
    except ValidationError as exc:
        secrets = _secret_fields()
        details = "\n  ".join(_describe(error, secrets) for error in exc.errors())
        raise RuntimeError(
            f"Invalid configuration ({exc.error_count()} problem(s)):\n  {details}\n"
            "See .env.example for the expected values."
        ) from None  # `from None`: the original exception carries the values
