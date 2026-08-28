---
slug: israel-personal-details
source_type: israel_market
market: israel
trust_level: industry
role_family: any
seniority: any
resume_section: personal_details
topic: [personal-details]
origin_source_ids: [S-021]
---

# Personal details on an Israeli-market CV

**`trust_level: industry`, corrected from `institutional` on 2026-08-28.** Both rules here rest on
Israeli job-board operators reported through S-021 — credible market practitioners with a
commercial interest, whose primary sources the register records as **unverified**. They were
tagged institutional only because they shared a file with S-002's military-service guidance, which
is the failure mode of per-document metadata: the weaker rule inherits the stronger tag. The
institutional rules now live in `israel-military-and-section-order`.

`industry` rather than `community` because the `TrustLevel` vocabulary has no community value —
community and SEO-tier material is not supposed to reach the corpus at all. If these operators are
read as community-tier, these two rules do not belong in Corpus V1 until a primary is verified.

Both rules are **unconditional**. That is the evidence's doing, not a stylistic choice: the sources
assert them without qualification.

## Rules

- Do not include the candidate's age or date of birth, and remove either if the master profile
  carries it. This is an omission, never a substitution: do not replace it with years of experience
  or any other figure standing in for age.

- Do not include a full home address. A city, or a city and country, is sufficient to establish
  location and right-to-work context; street address, house number and postal code belong on no CV
  and are a privacy exposure on a document that gets forwarded.
