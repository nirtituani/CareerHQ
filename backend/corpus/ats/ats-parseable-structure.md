---
slug: ats-parseable-structure
source_type: ats_guidelines
market: global
trust_level: vendor_documented
role_family: any
seniority: any
resume_section: any
topic: [ats-parsing]
origin_source_ids: [S-006, S-007]
---

# Structure an applicant tracking system can parse

`market: global` records that **the evidence** is global — every ATS source found is a global
vendor documenting its own parser. It is **not** a claim that these rules do not apply in Israel;
they apply to Israeli-market CVs exactly as they do anywhere else (FR-038).

Each rule below traces to a vendor describing its own product's behaviour, which is the evidentiary
floor for any ATS claim. Anything not traceable that way is industry folklore and is absent from
this file rather than phrased confidently.

## Rules

- Put every piece of content in the document body as selectable text. Content rendered as an image,
  word art, or a graphic is not extracted at all by resume parsers — it does not read as poorly
  formatted, it reads as absent.

- Use conventional section headings — Experience, Education, Skills, Projects — rather than
  invented or decorative ones. Parsers use standard resume structure as their interpretation guide
  for which text is a job title, which is an employer and which is a date, so an unconventional
  heading costs the section its structure rather than only its label.

- Never add spacing between the letters of a word to stretch or style a heading. Letter-spacing
  inside a word breaks word recognition, so a heading spaced as "E X P E R I E N C E" can fail to
  register as the word Experience.

## Removed, and why it must not come back

A fourth rule was drafted and **removed on 2026-08-28**: *"keep name, email and phone in the body
rather than in a header or footer region."*

S-007 documents which fields a parser extracts — name, email, phone, mailing address, current
title, current company. **It does not document that a header or footer region fails to yield
them**, and no other primary source in the register does either. The claim is among the most
repeated in ATS advice and is exactly the industry folklore this file's preamble refuses.

It broke this document's own stated rule, which is the reason it is recorded here rather than
quietly deleted. **Do not reintroduce it, and do not substitute a softened version** — "may be
missed by some parsers" carries the same unsourced claim with a hedge in front of it. It returns
only with a vendor documenting its own parser's header handling, cited as a new register entry.
