# Contract: The Judge

**One call in, one validated object out** — the same seam as everything else. The judge is a **task
name**, not a new provider path (FR-040), so `test_the_application_layer_imports_no_provider_sdk`
continues to hold without amendment.

## Configuration

`llm_model_eval_judge` **must be set explicitly** to Opus. `model_for_task` falls back to
`llm_provider_model`, which is also Opus — so omitting the entry would be **right by accident and
wrong by process**, and the fallback is silent. `docs/08` puts the judge on Opus because it is
judging quality.

## What it is shown

| Shown | Withheld | Why withheld |
|---|---|---|
| the job posting | which arm or configuration produced the output | FR-026 — a judge that can tell the arms apart is scoring the label |
| the composed résumé | the tailoring plan | it would score intent rather than result |
| the versioned rubric | the Reviewer's findings | it would echo the Reviewer and destroy the independence coverage depends on |
| | the master profile | it would become a second Reviewer, and its score would correlate with the Reviewer's by construction |
| | any other candidate's output | this contract scores one output at a time |

## What it returns

A validated structured object: a score per rubric dimension, a brief justification per dimension,
and an overall level. **Validated against a schema before use** (Constitution VI). A judge whose
output fails validation produces **no score for that case**; the case is reported as unjudged and
the run continues.

**Every rule the schema enforces must be visible in the JSON Schema.** A `model_validator(mode="after")`
does **not** serialise, and the schema is the whole contract the gateway sends — a conditional
requirement has to live in `Field(description=...)`, which does. This project has already shipped
the other way round once.

## The rubric

**Version-controlled and versioned** (FR-023). Every score records its rubric version, because
changing a rubric silently makes every historical score incomparable — the same rule the match
criteria follow.

**The rubric must not tell the judge how to distribute its answers.** *"Most résumés are mostly
adequate…"* is the exact phrasing that made a model push verdicts down to comply, measured in slice
004. State what each level means; say nothing about how often it should occur.

## What makes a judge score evidence

**Nothing, until agreement with a human is measured** (FR-025). Until then every score is labelled
**unvalidated**, and wherever a validated score appears it carries its agreement figure.

**Absolute rating and pairwise comparison are different instruments** and the choice is explicit
(D8, research R6). The proposal is **pairwise for the regression question** — which is the relative
judgement the slice actually asks, and the more stable human task — **with a small absolute anchor
set** so scores do not drift across rubric versions.

**No sample size is fixed here.** It follows from the judged-output count, which follows from D3.
The rule stands in its place: the sample must be large enough that the agreement figure would change
if the judge were random, and the figure is always reported with its `n`.

## Audit

Judge calls are recorded like every other call — task, model, tokens, cost (FR-027, Principle V) —
and on the failure path as well as the success path. A judge call that failed was still billed.
