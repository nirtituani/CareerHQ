# CareerHQ Corpus V1

**Authored guidance, not ingested source material.** Every rule here is written by CareerHQ in its
own words and *cites* the source it derives from. Research digests, source registers and
Before/After examples are **evidence** and live in `specs/006-document-retrieval/corpus-research/`
— they must never appear here (FR-036).

## Format

One Markdown file per topic. YAML front-matter carries the document's metadata; each `- ` list item
under `## Rules` is **one rule and therefore one retrieval chunk** (FR-037).

```yaml
---
slug: israel-personal-details          # stable natural key; never renamed
source_type: israel_market             # resume_best_practices | ats_guidelines |
                                       # domain_specific | seniority | integrity | israel_market
market: israel                         # global | israel   (see below)
trust_level: institutional             # internal | institutional | vendor_documented | industry
role_family: any                       # or: backend, devops, data, ml, cyber, ...
seniority: any                         # or: junior, mid, senior, staff, principal
resume_section: personal_details
topic: [personal-details]              # >=1 value from the Topic vocabulary (see below)
origin_source_ids: [S-010, S-013]      # register IDs this document's rules derive from
---
```

## `topic` — a list, and why

`topic` drives **one** thing: FR-038 precedence, where market-specific guidance outranks global
guidance *on the same topic*. Two documents are on the same topic when their lists intersect.

**Values come from `domain/models/knowledge.py::Topic`, and an unknown value is refused at load.**
The 16-value vocabulary was read off the rules that exist; do not add a value for a subject the
corpus does not yet cover.

**A list rather than a single value**, because two documents legitimately span two subjects —
`israel-military-and-section-order` covers military service *and* section ordering — since rules are
grouped by trust level, which is a different axis. A scalar would force those files to split for a
reason unrelated to what they say.

**Assign a topic only where the document genuinely addresses it.** An over-broad list makes
precedence fire where it should not, reordering guidance for no reason.

**Not derived from embeddings, deliberately.** That was tried and measured insufficient
(`research.md` R13): cosine ranked the one true same-topic pair 326th of 504, below the median,
while ranking a known-complementary pair first.

## The three rules that are easy to get wrong

**1. A rule carries its own conditions.** Qualifications and exceptions belong in the *same* list
item, never a sibling. A conditional rule retrieved without its condition is a different and worse
instruction — "military service can be a credibility signal" without "where relevant to the
candidate and the role" tells the model to emphasise it universally.

**2. `market: global` means the *evidence* is global — not that the rule is inapplicable to
Israel.** Global guidance applies to Israeli-market CVs. `market: israel` means the evidence
specifically supports the Israeli market. Where authoritative Israeli evidence conflicts with
global guidance, the Israeli guidance wins for Israeli-market CVs (FR-038). **Do not manufacture an
Israeli distinction where the evidence does not support one.**

**3. Nothing here may invite fabrication.** No rule may instruct estimating a figure the profile
does not supply, meeting a keyword quota, or adding an unsupported claim (FR-030). Integrity rules
are `trust_level: internal` and are **authored here only** — never sourced externally.

## Scope

English-language CVs, Israeli high-tech market priority.

**Corpus size and retrieval count are different numbers. Do not conflate them.**

| | |
|---|---|
| **Corpus V1 size** — how many rules exist to search over | **~95–130 rules, ~7,200–9,900 tokens** |
| **Retrieval per run** — how many reach one prompt | **≤1,500 tokens, ≈19 rules** |

The 1,500-token ceiling is a **budget per run**, never a target for how large the corpus should
be. A corpus is supposed to hold far more than any single run needs — that is what there is to
retrieve *from*.

**~76 tokens/rule is the measured figure** (18-rule sample, 2026-08-28), not the ~42 an earlier
estimate used. The 42 came from the shipped 12-rule rubric, whose rules are bare imperatives.
A corpus rule carries its qualifications and exceptions in the same chunk because rule 1 above
requires it, and those qualifications are the extra tokens. **Do not shorten a rule, or move a
condition into a sibling, to bring the average down.** The longer rule is the correct one; the
estimate was what was wrong.
