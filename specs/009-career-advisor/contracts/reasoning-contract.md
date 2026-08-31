# Contract — the reasoning seam (evidence in, operations out)

Two `complete()` tasks. Rule that governs both schemas: **a validator's rules must be
visible in the JSON Schema** — `model_validator(mode="after")` does not serialise, so every
conditional requirement lives in `Field(description=...)`. The deterministic gate
(`advisor_grounding.py`) is the enforcement; the descriptions are the instruction.

## Task `advisor_grouping` (Haiku) — optional step

**Input rendering** (prompt): enumerated distinct titles as
`[app: <uuid>] <title text>` and, when ≥2 analysed applications exist, requirement rows as
`[req: <uuid>] <verbatim text> (verdict: gap, importance: 70)`.

**Output schema — `GroupingProposal`**:

```python
class ProposedGroup(BaseModel):
    group_id: str        # Field(description="Short slug you assign, unique in this response.")
    label: str           # Field(description="Human name for the group, e.g. 'AWS' or 'Backend'.")
    group_kind: str      # Field(description="'role_family' for title groups, 'skill' for requirement groups.")
    member_ids: list[UUID]  # Field(description="Only ids listed in the input. Never invent an id. A group with fewer than 2 members should usually be omitted.")

class GroupingProposal(BaseModel):
    groups: list[ProposedGroup]
```

**Deterministic validation**: every `member_ids` entry must be an id that was rendered in
the prompt (unknown ids → the group is dropped and the drop recorded); an id may appear in
at most one group of the same `group_kind`. Counting then runs over surviving groups only.
The proposal is **evidence, not truth**: it is frozen into any memory that relies on it.

## Task `advisor_reason` (Sonnet) — the run's judgment step

**Input rendering** (prompt), in order:
1. The rules: floor (5), cap (25), no-causal-language, digits-must-come-from-facts,
   denominators-in-claims.
2. The evidence pack: every fact as
   `[fact: <fact_id>] <value> (n=<numerator>/<denominator>, <date range>)`.
3. Every **active/tentative** memory:
   `[memory: <uuid>] (<status>, kind=…, scope=…, confirmed <date>) "<claim>"` with its
   frozen evidence figures.
4. Every **dismissed** memory, marked:
   `[dismissed: <uuid>] "<claim>" — dismissed by the user; do not recreate.`
5. The instruction: disposition every `[memory: …]` id; propose creations only for
   patterns the facts support.

**Output schema — `AdvisorReasoning`**:

```python
class ProposedMemory(BaseModel):
    claim: str          # Field(description="One falsifiable sentence. Every number in it must appear verbatim in the cited facts. State the denominator. No causal language.")
    kind: str           # Field(description="Pattern kind slug, e.g. 'recurring_gap', 'strength', 'trend'. Open vocabulary.")
    scope_kind: str     # Field(description="'global', 'role_family', 'skill', 'status' or 'source'.")
    scope_value: str | None  # Field(description="Required unless scope_kind is 'global'; then it must be omitted.")
    cited_fact_ids: list[str]  # Field(description="At least one fact_id from the evidence. Cite only facts that directly support the claim.")
    grouping_ids: list[str]    # Field(description="group_ids the cited facts depend on, if any.")
    priority: int | None       # Field(description="0-100 when the memory is actionable (something the user could act on); omit otherwise. State the reason for the priority in priority_reason.")
    priority_reason: str | None  # Field(description="Required exactly when priority is set.")
    tentative: bool     # Field(description="Must be true when any cited fact's denominator is below the floor of 5.")

class Disposition(BaseModel):
    memory_id: UUID     # Field(description="An id rendered as [memory: …] in the input. Every such id must appear in exactly one disposition.")
    action: str         # Field(description="'confirm', 'supersede', 'retire' or 'leave_open'.")
    reason: str | None  # Field(description="Required for 'retire' and 'leave_open'; omit for 'confirm'.")
    superseding_index: int | None  # Field(description="For 'supersede' only: index into created[] of the memory that replaces this one, which must state what changed.")
    fresh_fact_ids: list[str]  # Field(description="For 'confirm': current facts showing the claim still holds; recorded as the confirmation's evidence delta.")

class AdvisorReasoning(BaseModel):
    created: list[ProposedMemory]
    dispositions: list[Disposition]
    nothing_found_reason: str | None  # Field(description="Required exactly when created is empty and no disposition supersedes: say honestly why the evidence supports no new memory.")
```

## The deterministic gate (what must survive to be persisted)

Applied in `advisor_grounding.py`, in order, each refusal recorded
(`extra={run_id, gate, detail}`) and counted into `ops_discarded`:

1. **Citation existence**: every `cited_fact_ids`/`fresh_fact_ids` entry is in this run's
   pack; every `grouping_ids` entry survived grouping validation.
2. **Numeral grounding**: every numeral token in `claim` appears among the cited facts'
   rendered numbers (numerator, denominator, value, date-range years). A claim with no
   cited facts is refused outright.
2a. **Denominator presence** (SC-003's teeth): every persisted claim must contain at
   least one cited fact's explicit `numerator/denominator` pair (rendered as "N of M" or
   "N/M"). **A claim containing no numbers at all does not bypass this check — it fails
   it**: an evidence-backed claim that cannot state its denominator is not persisted.
3. **Causality**: refusal on the versioned phrase list when applied to co-occurrence.
4. **Floor**: `tentative` must be true when any cited denominator < 5 (gate forces it
   true rather than refusing — the honest downgrade).
5. **Disposition completeness**: `set(active+tentative ids) == set(disposition
   memory_ids)`, exactly once each (FR-013 — a shortfall fails the run, not just the op:
   an unaccounted-for memory is a run defect).
6. **Contradiction**: no two surviving active claims share `(kind, scope)` (supersession
   resolves; two fresh creates on one subject → higher-priority one survives, the other
   is discarded-with-record).
7. **Dismissal**: a create matching a dismissed memory's `(kind, scope)` is refused
   unless its cited `(fact_id, numerator, denominator)` tuples differ from the dismissed
   memory's frozen tuples; a surviving recreation carries `recreates_dismissed_id`.
8. **Cap** — with a defined evaluation order: dispositions are applied **conceptually
   first** (supersedes and retires shrink the active set), and creates are then counted
   against the **post-disposition** active set. So at 25 active, a run proposing one
   create *and* one retire is **valid** and ends at 25 — a gate that counted creates
   against the pre-disposition set would wrongly discard that create. Only after this
   ordering does `count(active+tentative) ≤ 25` refuse excess creates, dropped in
   priority order, recorded.

**Terminology mapping** (deliberate, and mapped in exactly one place): the schema's
disposition action is the verb **`leave_open`** (what the model chooses to do); the
`memory_dispositions.action` value is the participle **`left_open`** (what the run
recorded). `advisor_grounding.py` owns the translation table for all four actions and is
the only module that performs it; the T022 tests cover the mapping so the two vocabularies
cannot drift silently.

Everything that survives is applied **in one transaction**: memory inserts, status
transitions, disposition rows, run completion with counts/usage/cost. A failure anywhere
before commit leaves the memory set byte-for-byte unchanged (SC-005).

## Test-double rule

The scripted seam for these tasks must **read the ids and figures out of the rendered
prompt** (testing rule 4) — a double fed by the test author proves plumbing, not that a
model could ever satisfy the contract. And it must raise on repeat calls (`ScriptedSeam`
precedent) so a loop can never look convergent.
