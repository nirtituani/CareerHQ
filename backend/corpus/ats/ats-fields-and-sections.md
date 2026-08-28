---
slug: ats-fields-and-sections
source_type: ats_guidelines
market: global
trust_level: vendor_documented
role_family: any
seniority: any
resume_section: any
topic: [ats-parsing]
origin_source_ids: [S-006, S-007, S-008]
---

# The fields a parser extracts

`market: global` records that **the evidence** is global — every ATS source in the register is a
global vendor documenting its own parser. It is **not** a claim that these rules do not apply in
Israel (FR-038).

Each rule states something a vendor documents about its own product. **Where a widely repeated
piece of ATS advice has no such backing, it is absent from this file** rather than included with a
hedge — including anything about which regions of a page parse and anything about file formats,
which the register records as unresolved and time-dependent.

## Rules

- Make sure the candidate's name, email address and telephone number each appear as ordinary
  selectable text somewhere in the document. These are among the fields a parser extracts into a
  candidate record, and one that is missing or unreadable leaves a profile that cannot be contacted
  however well the rest of it parses.

- Give each role an explicit employer name and job title as separate readable text rather than
  combining them into one styled line. Current title and current employer are extracted as distinct
  fields, and a combined line gives the parser one string where it expects two.

- Keep education, skills and work history in distinct labelled sections rather than blending them
  into a single narrative. Parsers extract these into separate structured collections, so content
  that sits in the wrong section is filed under the wrong heading in the resulting profile rather
  than simply looking unusual.

## Removed, and why it must not come back

A fourth rule was drafted and **removed on 2026-08-28**: *"where a CV mixes scripts or languages,
keep the candidate's name, employers and titles consistent with the language the rest of the
document uses."*

S-006 documents that non-English parsing is a **distinct documented behaviour** — it publishes a
dedicated article on it. It does **not** document what an author should therefore do, and no other
register source does either. The prescription was mine, presented as if it followed from the
vendor's evidence.

This is the same defect as the header/footer rule removed from `ats-parseable-structure`, and it
survived a first review because the *fact* it cites is real. **The fact being sourced does not make
the instruction sourced.** It returns only with a vendor documenting how mixed-script content should
be prepared, cited as a new register entry.
