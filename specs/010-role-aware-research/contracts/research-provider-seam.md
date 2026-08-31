# Contract: the ResearchProvider seam

The artifact to understand first in this slice, as `extraction-seam.md` is for 003. One call in,
one validated object out — and the boundary refuses provider vocabulary the way
`GuidelineSource` refuses retrieval vocabulary.

## The port (`application/ports.py`)

```python
class ResearchProvider(Protocol):
    """Produce role-aware company research in one call.

    The port speaks the application's language only: an employer, a role, a
    posting. No model tiers, credit budgets, search depths, or timeouts —
    those are an adapter's configuration, and naming them here would choose
    the implementation (the GuidelineSource refusal, applied again).
    """

    async def research(
        self,
        *,
        company_name: str,
        domain: str | None,
        role_title: str | None,
        posting_text: str | None,
    ) -> ResearchOutcome: ...
```

```python
@dataclass(frozen=True, slots=True)
class ResearchOutcome:
    research: ApplicationResearch | CompanyResearch   # which one is the adapter's identity
    sources: tuple[ProviderSource, ...]               # url, title; excerpt only when verified
    produced_by: str                                  # "provider:tavily-research" | "builtin"
    prompt_version: str                               # "app-v1" | "v2-dense" (shape discriminator)
    usage: Usage | None                               # exact usage (fallback) or None (provider)
    cost_estimate: Decimal | None                     # documented-rate estimate when usage is None
```

Invariants the contract imposes (each becomes a test):

1. **Exactly one of `usage` / `cost_estimate` is non-None.** The persistence layer derives
   `cost_basis` from which one it received; an adapter returning both (or neither) is a bug the
   use case must reject, not reconcile (research.md D5).
2. **`research` shape matches `prompt_version`.** `app-v1` ⇔ `ApplicationResearch`,
   `v2-dense` ⇔ `CompanyResearch`. The use case validates the pairing before persisting.
3. **`posting_text` is optional and its absence is honest.** When None, the adapter must not
   invent role context; the role sections explain the absence (FR-011, D7).
4. **Failures raise, carrying what was spent.** A `ResearchProviderUnavailable` (config/transport)
   is distinguishable from a `ResearchProviderRejected` (bad output / schema violation) — the
   route maps the first to fallback-or-fail per configuration and both to a recorded failure.
   Mirrors `SearchUnavailable`'s honesty; adds 008's lesson that a failure after billed work must
   carry its cost basis.
5. **No profile data can enter.** The signature has no parameter for it; SC-007's sentinel test
   asserts the assembled inputs contain nothing profile-derived.

## Import rule (extends the existing architecture gate)

`application/` must not import the provider SDK or `httpx`; the Tavily Research adapter lives in
`infrastructure/research/tavily_research.py` and is chosen in `api/routes/research.py` next to
`get_web_search` — the established one-`if` selection pattern (`build_guideline_source`
precedent). `tests/unit/test_architecture.py` already walks `application/` imports; the new
adapter must appear in the route module only.

## The Tavily Research adapter (behaviour contract, not code)

- `POST https://api.tavily.com/research` with `model="mini"`, `citation_format="numbered"`, and
  `output_schema` = the `ApplicationResearch` JSON Schema. **Every schema property carries a
  `description`** — the endpoint 400s otherwise (measured), and with a provider the schema is the
  entire prompt-side contract, so descriptions also carry the conditional requirements
  (`model_validator` does not serialise — the 005 lesson applies verbatim).
- The research `input` frames company/role/posting as untrusted quoted data (FR-019) and carries
  the three instruction clauses of research.md D4 (entity resolution, primary-source preference,
  dated claims).
- Response handling: `content` may arrive as a JSON string or object — accept both; validate into
  `ApplicationResearch`; map `sources[]` to `ProviderSource` rows with minted `s1..sN` ids and no
  excerpts. A response that fails validation raises `ResearchProviderRejected`.
- Cost: `cost_estimate` from the documented mini-tier rate; the raw basis (tier, documented
  credit range) goes into `model_config_used` for the audit trail. Never poll the usage endpoint
  in-line (it lags — measured flat across an entire POC).
- Timeout from configuration; a timeout raises `ResearchProviderUnavailable`.
- Posting text longer than `research_posting_max_chars` (default 20,000 characters) is truncated
  from the end before the request is built, and the adapter contributes
  `{"posting_truncated": true, "posting_chars_sent": N}` to the snapshot's `model_config_used`.
  Untruncated postings contribute nothing (absence means "sent whole").

## The builtin adapter (fallback)

Wraps the unchanged `research_company()` call chain (queries → TavilySearch → WebSourceFetcher →
synthesis → verbatim citation check) and returns its tiered `CompanyResearch` as
`ResearchOutcome(prompt_version="v2-dense", produced_by="builtin", usage=<exact>,
cost_estimate=None)`, with verified excerpts on its sources. Its known wrong-entity risk is an
accepted property of the degraded mode (spec assumption); nothing in the adapter tries to hide
which path produced the result.
