# Source Register — Slice 006 Corpus

**Canonical register of every candidate source.** Append-only; IDs are permanent and never reused.
Vocabularies (claim types, dispositions, verification status, the four dimensions) are defined in
[README.md](README.md) and are not repeated here.

**Last updated**: 2026-08-27 · **Entries**: S-001 – S-022 · **Status**: open, accepting sources

> Nothing in this register has been ingested. No disposition here is final while its licensing
> column reads *unverified*.

## Summary

| ID | Source | Kind | Market | Authority | Verified | Disposition |
|---|---|---|---|---|---|---|
| S-001 | Israel Employment Service — CV structures | normative | israel | institutional | read | provisional `corpus` |
| S-002 | MOD *Hachvana* — CV without experience | normative | israel | institutional | read | provisional `corpus` |
| S-003 | Government Campus — CV course | normative | israel | institutional | unexamined | undecided |
| S-004 | Ministry of Education — CV guide (PDF) | normative | israel | institutional | unexamined | undecided |
| S-005 | Israel Employment Service — "how to write a CV" | — | israel | institutional | **dead** | `rejected` |
| S-006 | Greenhouse — ATS documentation | normative | global | vendor_documented | summary_only | `evidence` → authored rules |
| S-007 | Lever — resume parsing | normative | global | vendor_documented | summary_only | `evidence` → authored rules |
| S-008 | Workday — resume parsing | normative | global | vendor_documented | summary_only | `evidence` → authored rules |
| S-009 | career-ladders.dev (sdras) | normative | global | industry | read | `evidence` → authored rules; **MIT, cleared 2026-08-28** |
| S-010 | Telfed — CV for the Israeli market | normative | israel | community | summary_only | `evidence` only |
| S-011 | Anglo-List — Israel resume tips | normative | israel | community | summary_only | `evidence` only |
| S-012 | VisualCV — Israel resume | normative | israel | industry | summary_only | `evidence` only |
| S-013 | Metaintro — Israeli resume format | normative | israel | community | summary_only | `evidence` only |
| S-014 | EasyAliyah — adjusting your CV | normative | israel | community | summary_only | `evidence` only |
| S-015 | *(reserved)* | | | | | |
| S-016 | *(reserved)* | | | | | |
| S-017 | shahar-cv-optimizer (Claude skill) | normative | both | industry | read | **`rejected` — licence** |
| S-018 | CareerHQ house rubric (`guidelines.py`) | normative | global | internal | read | `corpus` (seed) |
| S-019 | Six Before → After CV examples | **demonstrative** | unknown | internal analysis | read | `corpus` (demonstrative), provenance open |
| S-020 | Three reference CV PDFs in `examples/` | demonstrative | global | — | read (hashes) | **course-use only; `rejected` for public/corpus** |
| S-021 | Three research digests (`sources/research/`) | **evidence** | mixed | secondary digest | read | `evidence-only` — not corpus content |
| S-022 | 13 real CV images (`examples/cv 1–6/`) | demonstrative | israel | primary artefacts | read (filenames) | **BLOCKED — privacy** |

---

## S-001 — Israel Employment Service, CV structures

**URL**: https://www.taasuka.gov.il/he/infoandpublications/cvformats/
**Type**: Resume Best Practices / Israeli market · **Market**: israel · **Role/Seniority**: any / any

**Authority**: Institutional. The national employment service, under the Ministry of Labor — it has
standing on what Israeli employers and its own placement process expect.

**Licensing**: ⚠️ **unverified.** gov.il terms of use must be checked before any text is
reproduced. Under the authored-rules model this is low-risk, but the check is still owed.

**Contributes** *(claim type: `recommendation`, some `authoritative_fact`)*:
- Chronological vs. functional CV formats and when each applies.
- Explicit warning that functional CVs are "less common and may not appeal to some readers."
- Include volunteer work, temporary positions, and **youth-movement leadership** as experience.
- List separate roles held at one employer, to show progression.
- Focus on the **past 10–15 years** for long histories.

**Explicitly absent** (checked, worth recording so nobody assumes): no guidance on length, photos,
personal details, military service, or ID numbers.

**Overlap**: the format and progression advice is universal and overlaps S-018 and global sources.
The volunteer/youth-movement emphasis is distinctly Israeli.

**Disposition**: provisional `corpus`, pending licensing. Note that most of its content is
*universal advice from an Israeli source* — under the Israel-first rule it should mostly be tagged
`market: global`, not relabelled Israeli by origin.

---

## S-002 — Israeli MOD *Hachvana*, CV writing without professional experience

**URL**: https://www.hachvana.mod.gov.il/ConsultationAndDirection/Employment/Pages/cv-writing.aspx
**Type**: Domain-Specific / Israeli market · **Market**: israel · **Seniority**: junior, entry

**Authority**: Institutional. Ministry of Defence career guidance for discharged soldiers — the
body with the most standing on how Israeli military experience should be presented.

**Licensing**: ⚠️ **unverified** (gov.il).

**Contributes** *(claim type: `recommendation`)*:
- **Reframe military service from title to capability** — "operations sergeant" becomes managing
  pressure, deciding under uncertainty, coordinating complex events.
- Named transferable skills: pressure management, decision-making, communication, organisation and
  operational efficiency, leadership and mentoring, initiative.
- A 10-section CV structure that treats **informal experience** and **military service** as
  distinct sections.
- Connect volunteering, youth movements and training to specific job requirements.

**Overlap**: none — no global source found covers this.

**Disposition**: provisional `corpus`. **The single highest-value Israel-specific source found so
far**, and the clearest case where Israel-first is justified by demonstrated difference rather
than by origin.

---

## S-003 — Government Campus, full CV-writing course
**URL**: https://campus.gov.il/en/course/taasuka-gov-career-cvbuilding101-he/
**Market**: israel · **Authority**: institutional · **Verified**: unexamined
**Disposition**: undecided — needs examination. Course format may not decompose into atomic rules.

## S-004 — Ministry of Education, CV writing guide (PDF)
**URL**: https://meyda.education.gov.il/files/Pop/0files/Financial-Education/middle-high-school/Writing-resume.pdf
**Market**: israel · **Authority**: institutional · **Verified**: unexamined
**Disposition**: undecided. School-level material aimed at students; may be too basic for a
professional software-engineering audience. Examine before investing.

## S-005 — Israel Employment Service, "how to write a CV"
**URL**: https://www.taasuka.gov.il/he/Applicants/JobSearchStages/pages/howtowritecv.aspx
**Verified**: **dead — HTTP 404** (checked 2026-08-27), despite appearing in search results.
**Disposition**: `rejected`. Recorded so it is not re-proposed from a stale search result.

---

## S-006 — Greenhouse, ATS documentation

**URLs**:
- https://support.greenhouse.io/hc/en-us/articles/360052218132-Supported-formats-for-resumes-cover-letters-and-other-candidate-uploads
- https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse
- https://support.greenhouse.io/hc/en-us/articles/205019689-Resume-parsing-with-non-English-languages

**Type**: ATS Guidelines · **Market**: global · **Authority**: vendor_documented — primary source
on its own parser's behaviour. **Verified**: summary_only ⚠️ primary pages not individually read.

**Licensing**: copyrighted help content. **Do not reproduce text.** Extract facts (uncopyrightable)
and author our own rules citing the URL.

**Contributes** *(claim type: `authoritative_fact`)*:
- Accepted upload formats: doc, docx, pdf, rtf, txt; 100 MB maximum.
- Parsing fails on graphics, photos, word art, and image-based resumes.
- Letter-spacing inside words breaks word recognition.
- A dedicated article on non-English parsing — directly relevant to Hebrew names and mixed-script
  content on an English CV for the Israeli market.

**Overlap**: high with S-007/S-008 on general parser behaviour; unique on formats and limits.

**Disposition**: `evidence` → authored rules. **This is the evidentiary floor for ATS claims.**
Anything we assert about ATS behaviour should trace here or to S-007/S-008; everything else is
industry folklore and must be phrased as risk-reduction, not fact.

## S-007 — Lever, understanding resume parsing
**URL**: https://help.lever.co/s/article/Understanding-Resume-Parsing
**Type**: ATS Guidelines · **Market**: global · **Authority**: vendor_documented · **Verified**: summary_only
**Contributes** *(`authoritative_fact`)*: parsers use standard resume structure as an interpretation
guide; extracted fields include name, email, phone, mailing address, current title, current company.
**Disposition**: `evidence` → authored rules. Supports "use conventional section headings" as a
*parser-grounded* rule rather than an aesthetic preference.

## S-008 — Workday, resume parsing concept
**URL**: https://doc.workday.com/admin-guide/en-us/human-capital-management/recruiting/candidates/set-up-prospects-and-candidates/hdc1552497830785.html
**Type**: ATS Guidelines · **Market**: global · **Authority**: vendor_documented · **Verified**: summary_only
**Contributes**: parsing extracts education, skills, work history into structured profiles.
**Overlap**: largely covered by S-006/S-007. **Disposition**: `evidence`; low marginal value.

## S-009 — career-ladders.dev — **licensing RESOLVED 2026-08-28**
**URL**: https://career-ladders.dev/ · **Source**: https://github.com/sdras/career-ladders
**Type**: Seniority Guidelines · **Market**: global · **Authority**: industry · **Verified**: read
(site and licence file)
**Contributes** *(`recommendation`)*: recurring level dimensions — technical skill, **scope of
impact** (individual → team → multi-team → org), independence, leadership, communication. Scope is
the primary differentiator across levels.

**Licensing**: ✅ **MIT.** `LICENSE.md` in `sdras/career-ladders` reads *"Copyright 2021 Sarah
Drasner. Permission is hereby granted, free of charge, to any person obtaining a copy of this
software…"* — derivative works and commercial use are both permitted, with the copyright notice
required in copies or substantial portions.

### Two corrections to this entry, both material

**1. It is not an aggregator, and that error created the licensing problem.** This entry described
career-ladders.dev as an *"aggregator of company ladders"* whose *"per-ladder licences differ"*, and
therefore required resolution **per ladder before any is used**. That premise was wrong. The site
publishes **one author's own three ladders** — Engineering, Developer Experience, Documentation —
open-sourced as templates by Sarah Drasner. There is one author, one repository and one licence, so
there was never a per-ladder question to resolve.

**2. "Search did not confirm Creative Commons" was true and misleading.** It is not CC; it is MIT,
which is *more* permissive for this use. The earlier check looked for the wrong licence and read its
absence as unresolved risk. **This is the same trap S-017/fastembed recorded from the other
direction — the licence file governs, and it has to be read rather than inferred from a search.**

### What CareerHQ's 8 seniority rules actually derive from

**No individual ladder.** `corpus/role-seniority/seniority-early-career.md` and
`seniority-senior-and-above.md` were authored from the one-line observation recorded in this entry —
that scope of impact is the primary differentiator across levels — and not from any ladder's text.
No ladder was opened during authoring, and no wording is reproduced.

That is stated plainly because it cuts both ways: it means **no substantial portion is copied**, so
MIT's attribution condition is not triggered by anything in the corpus; and it means the eight
rules rest on a *summary* rather than on read primary material, which is an evidence-quality limit
recorded under F9, not a licensing one.

**Disposition**: `evidence` → authored rules. **Cleared for use.** The eight existing rules remain
in Corpus V1. Reproducing ladder *text*, or deriving level definitions from a specific ladder, would
be a new question — permitted by MIT, but requiring the copyright notice.

---

## S-010 – S-014 — Commercial and community Israeli CV guidance

| ID | Source | URL |
|---|---|---|
| S-010 | Telfed | https://www.telfed.org.il/resume-writing-for-the-israeli-job-market/ |
| S-011 | Anglo-List | https://anglo-list.com/your-israel-resume/ |
| S-012 | VisualCV — Israel | https://www.visualcv.com/international/israel-resume/ |
| S-013 | Metaintro | https://www.metaintro.com/blog/israeli-resume-format-guide |
| S-014 | EasyAliyah | https://www.easyaliyah.com/blog/adjusting-your-resume-cv-for-the-israeli-job-market |

**Market**: israel · **Authority**: community / industry · **Verified**: summary_only
**Licensing**: copyrighted, no redistribution.

**Contribute** *(claim type: `community_opinion` — none cite evidence)*: a shared set of claims
about the Israeli market, listed under *Claims awaiting verification* below.

**Overlap**: near-total with each other. Several appear aimed at olim rather than at the
domestic Israeli tech market, which is CareerHQ's actual audience.

**Disposition**: **`evidence` only, never `corpus`.** They are the origin of most "Israeli CVs
are like X" beliefs, and not one substantiates them. Their value is telling us what to verify.

---

## S-017 — shahar-cv-optimizer (Claude skill) — REJECTED

**URL**: https://github.com/shahar84/shahar-polaks-career-studio/tree/main/plugins/shahar-polaks-career-studio/skills/shahar-cv-optimizer
**Verified**: read (licence, and the guidance-bearing reference files)

**Licensing — the disqualifying finding.** "Shahar Polak Personal Use License 1.0" grants use
"solely for your own personal career development and job-search activities" and prohibits, without
written permission: redistribution "including by creating a fork, mirror, or hosted copy";
"modify, translate, adapt… or create derivative works based on the plugin, its skills, templates,
**references**, prompts, or other materials"; and use of "the plugin **or its materials in a
commercial product, service, workflow, dataset, or model-training process**."

CareerHQ is a deployed, publicly reachable service, and a RAG corpus is squarely "materials in a
workflow or dataset." **Ingesting, quoting, or paraphrasing this into corpus content would breach
at least three clauses.**

**Substance, independent of licence** — it would be a weak source anyway. Its guidance files are
very small (`geographic-market-guidelines.md` is 326 bytes, its entire Israel content one unsourced
clause about Israeli writing style; `ats-guidelines.md` is 618 bytes of conventional advice with no
citations). Its job-analysis verdict taxonomy is near-identical to CareerHQ's own slice-004
verdicts, which were derived independently with recorded rationale — convergent validation, but no
new contribution.

**Disposition**: **`rejected`.** Recorded permanently so it is not re-proposed. Do not ingest,
quote, or paraphrase.

---

## S-018 — CareerHQ house rubric

**Location**: `backend/src/careerhq/application/guidelines.py` (`_RUBRIC`)
**Type**: Resume Best Practices + Integrity · **Market**: global · **Authority**: internal
**Licensing**: ours. **Verified**: read.

**Contributes**: 12 atomic rules, **507 tokens measured** — the only corpus-shaped content that
exists today. Three cite `AI-008` and are integrity rules rather than style advice. Its shape
(one self-contained rule, ~42 tokens, carrying its own `source`) is the proven template for the
whole corpus.

**Disposition**: `corpus` — the seed. Integrity rules stay internally authored permanently; they
are product-safety obligations under Principle III, not advice to be sourced.

---

# S-019 — Six Before → After CV examples *(demonstrative knowledge)*

**Analysis**: [`before-after-analysis.md`](before-after-analysis.md) — **canonical**. The register
summarises and cross-references it; it does not restate it, and the analysis is authoritative where
the two differ.

**Kind**: demonstrative · **Authority**: internal analysis of external examples ·
**Verified**: read (analysis; the underlying CVs were analysed outside this repository)

**Raw CVs are NOT stored in this repository.** `examples/` is empty and must stay that way unless
the material is synthetic or fully de-identified — a real CV carries a home address, phone number
and employment history, this repository is public, and `testing files/` is gitignored for exactly
this reason.

**Role families covered** (usefully broad): Senior Android/Mobile (Ex. 1), technical
customer-facing / presales (Ex. 2), Customer Success / Technical Account Management (Ex. 3),
CFO / VP Finance (Ex. 4), Backend / Blockchain (Ex. 5), Data & Analytics project management
(Ex. 6).

**Contributes** *(claim type: `example`)*: eleven candidate patterns, each recorded with its
supporting examples, a strength rating and an explicit caution — §1.1–§1.11 of the analysis.

**What makes this source unusually good**: §2 records **six over-generalisations that must NOT
become rules** — always add metrics, always one page, always add technologies, always remove
non-relevant information, always use one structure, always rewrite every bullet. Recording the
rejected reading beside the supported one is the discipline that stops demonstrative material
being laundered into normative rules, and it is why this set is safe to keep.

**Disposition**: `corpus` as **demonstrative** knowledge only. An example shows a transformation;
it never asserts the transformation is required. These must be retrievable and citable
*differently* from rules, and slice 007 must judge them differently.

**Open — provenance and licensing** ⚠️: the origin, consent status and licence of the six source
CVs are **not recorded**. Until they are, this cannot ship as corpus content even though the
analysis is sound. Required before disposition is final: are the CVs real or synthetic; if real,
is there consent and are they de-identified; who holds copyright in the "after" versions.

---

## S-020 — Three reference CV PDFs (`corpus-research/examples/`) — REJECTED

**Files**: `classic-reference.pdf`, `crimson-reference.pdf`, `warm-reference.pdf`

**Finding (measured, 2026-08-27)**: these are **byte-identical** to the design assets of S-017,
the source already rejected on licensing. Verified by size and SHA-256 against
`.../shahar-cv-optimizer/assets/cv-design-examples/`:

| File | Bytes | SHA-256 (first 16) | Upstream match |
|---|---|---|---|
| `classic-reference.pdf` | 30,949 | `ff706b3f55b11b2a` | ✅ identical |
| `crimson-reference.pdf` | 25,231 | `9d5817c9186c342c` | ✅ identical |
| `warm-reference.pdf` | 25,213 | `e8c0882e0ecc92af` | ✅ identical |

**Why this matters**: the S-017 licence prohibits copying, redistributing or mirroring the
materials, creating derivative works from them, and using them "in a commercial product, service,
workflow, **dataset**, or model-training process." Placing them in this repository is a copy;
analysing them to extract corpus patterns would be a derivative work and a dataset use.

**Status**: untracked, uncommitted, unpushed as of this entry — **nothing has been published**, so
the exposure is fully recoverable by deleting the files.

**Disposition**: `rejected`. Not analysed, not ingested, not to be used as demonstrative material.
Recorded permanently so the same assets are not re-proposed under a different filename.

---

# Cross-check: candidate patterns vs. the existing rubric (S-018)

Consolidating S-019 against the 12 rules already in `guidelines.py`. This is the highest-value
output of the pass: it shows what is corroboration, what is genuinely new, and — most importantly
— **where the two disagree**.

| Analysis pattern | Existing rubric | Reading |
|---|---|---|
| §1.4 Quantified impact | "Quantify ONLY where the profile supplies the number" (AI-008) | **Strong corroboration.** Both independently insist on the same integrity constraint, and §2.1 rejects "always add metrics" in the rubric's own words |
| §1.6 Action-oriented language | "Open bullets with a concrete verb, not 'responsible for'" | **Direct overlap.** No new rule needed |
| §1.8 Focused summary | "The summary states what the person is and has done… not ambition" | **Direct overlap** |
| §1.1 Role positioning | Partially covered by the summary rule | **Extends it** — positioning is a whole-CV property, not just the summary |
| §1.3 Achievements over responsibilities | Partially — the verb rule is about phrasing | **Extends it** — this is bullet *structure* (did X resulting in Y), not word choice |
| §1.11 Emphasis and hierarchy as tailoring | "Lead each role with the most relevant work" | **Corroborates, and independently validates slice 005's T095**: reordering is a real tailoring action, not inaction |
| §1.5 Technical specificity | — none — | **Gap.** No rubric rule addresses role-specific technical depth. Directly relevant to CareerHQ's audience |
| §1.7 Generic → specific | — none — | **Gap.** Nothing covers replacing generic self-description with evidence |
| §1.10 Skills → evidence | "Order skills by relevance; add none the profile lacks" | Compatible; adds nuance, and its caution (keep a Skills section for ATS scanning) agrees with S-006/S-007 |
| **§1.2 / §1.9 Compress and deprioritise** | **"Drop items that serve no requirement rather than compressing them"** | ⚠️ **CONFLICT — see below** |

## The conflict, stated plainly

Rubric rule 6 currently instructs: *"Drop items that serve no requirement in this posting **rather
than compressing them**. A shorter resume that answers the posting beats a complete one that does
not."*

The example evidence points the other way. §1.2 observes that less relevant material is "reduced,
moved lower, or compressed **rather than necessarily being deleted**"; §1.9 records compression as
the observed behaviour; and §2.4 explicitly **rejects** "always remove non-relevant information."

**This is a genuine disagreement between an existing shipped rule and six worked examples**, not a
wording nit — the rule tells the Draft node to delete where the examples show practitioners
compressing. It must be resolved deliberately, and it is now the strongest candidate for a rule
change arising from this research. It is **not** resolved here: six examples of unrecorded
provenance are not automatically stronger than a rule that has been in production, and slice 007
is the instrument that should settle it.

---

# Open decisions arising from S-019

1. **Resolve rule 6 (drop vs. compress).** Blocking for corpus authoring, not for planning.
2. **Establish provenance, consent and licensing for the six CVs.** Blocking for S-019 shipping.
3. **Decide how demonstrative knowledge is represented and retrieved** — an example is a
   before/after/transformation triple, not a rule sentence. This shape affects `ChunkMetadata` and
   is a second reason the metadata model needs work beyond the missing `market` field.
4. **Decide whether §1.5 and §1.7 become new authored rules**, since nothing currently covers them.

---

# Claims awaiting verification

Repeated across S-010 – S-014 with **no evidence given by any of them**. None may become corpus
content until independently supported.

| Claim | Status | Why it matters |
|---|---|---|
| Israeli CVs are 1 page (mid-level) / 2 pages (senior) | unverified | Would be a concrete length rule |
| Hebrew CV generally expected; English accepted at multinationals/tech | **unverified, high-stakes** | CareerHQ produces English CVs for this market — the premise deserves a real source |
| Military service belongs in the *education* section | unverified, **conflicts with S-002** | S-002 (institutional) makes it its own section |
| Israeli employers favour direct, impact-focused writing | unverified | Style generalisation; risks stereotype-as-rule |

# Known gaps — no source yet

1. **Israeli technology-sector hiring conventions** specifically, as distinct from the general
   Israeli market. This is CareerHQ's actual audience and the weakest-covered area.
2. **Whether English CVs are genuinely standard in Israeli tech** — see the table above.
3. **Role-family specifics** (backend, DevOps, data, ML, cyber) — no *external* source yet.
   Partially addressed by S-019, which spans six role families, but as examples rather than
   guidance, and with unresolved provenance.
4. **Israeli ATS/recruitment ecosystem** — which systems Israeli employers actually run. All ATS
   evidence so far is from global vendors.
5. ~~Before → After examples~~ — **addressed by S-019** (six examples, six role
   families). Provenance and licensing remain open.

# Standing conclusion on size

**Superseded 2026-08-28.** This read: *at the measured ~42 tokens/rule, ~120–170 rules,
~5,000–7,200 tokens.* The 42 came from the shipped rubric (S-018), whose rules are bare
imperatives; authored corpus rules carry their qualifications in the same chunk (FR-037) and
measure **~76 tokens/rule** over an 18-rule sample. Current estimate: **~95–130 rules,
~7,200–9,900 tokens**. The rule count is unchanged and no rule was shortened to recover the old
figure. Full account in `research.md` R6.

Either way the conclusion below is unaffected — both projections sit below the ~200-rule threshold
at which retrieval becomes necessary on context grounds. **RAG in Slice 006 is justified by the graded course requirement and by
headroom for growth, not by a context limit.** This must be stated plainly in the plan so that
slice 004's unverified "genuinely too large for context" claim is not inherited as measured fact.


---

# S-021 — Three research digests (`sources/research/`)

`hitech-cv-rag-sources.md` (18 KB), `Sources for Hi-Tech CV Guidelines (Israel Focus).pdf` (3 pp),
`hitech-cv-rag-corpus.pdf` (15 pp, ~32,000 chars, 70+ URLs). Text extracted locally with
pdfplumber; no provider calls.

**Kind: `evidence`, not `corpus`.** These are *secondary digests* — per-source entries of the form
"Source / URL / Summary". A chunk from them reads "Indeed presents a 6-part framework…", which is
*about* guidance rather than *being* guidance. That is a poor retrieval unit for the Draft node,
and a citation would point at our summary rather than at the source.

**Authority is mixed and the digest format flattens it.** Genuinely authoritative entries
(Technion Career Development Center; university career centres ONU/PCC/UIC/UT-Austin on ATS) sit
in the same visual form as resume-tool vendors and SEO content farms (resumly.ai,
resumeoptimizerpro.com, atsresumeschecker.com, jobwizard.ai, agenticjobboard.com, manyoffer.com,
rockstardeveloperuniversity.com). Israeli market operators (Drushim, AllJobs, GotFriends, Log-On,
Techmonster, Jolt, TechJob, DevJobs) have real standing on Israeli recruiter behaviour *and* a
commercial interest.

**Disposition**: `evidence-only`. Use as the input to authoring rules; do not ingest.

## ⚠️ Two safety-critical conflicts inside S-021

1. **"Defensible estimates when hard numbers are unavailable"** (STAR/PAR cluster) **directly
   contradicts rubric rule 3 and AI-008** ("Never estimate, round up, or introduce a figure the
   profile does not contain"). Ingested naively this would instruct the Draft node to invent
   metrics — the exact failure Principle III makes a release blocker.
2. **"Target 70–80% coverage of required keywords"** (keyword-tailoring cluster) is a *quota*.
   Quotas pressure fabrication when the profile cannot meet them. Rule 4 and rule 9 already bound
   mirroring to what the profile supports; the quota must not be imported.

## Unreconciled conflicts (recorded, not resolved)

| Topic | Claim A | Claim B |
|---|---|---|
| Recruiter first-scan time | Drushim: **20–30 seconds** | ResumeFlex: **~6 seconds** |
| CV length | Techmonster: **strict one page** | Drushim: **1–2 pages**; global: 1p <5–10 yrs, 2p senior |
| File format | University centres: **.doc/.txt/.rtf** (older ATS) | 2025–26 sources: **PDF is fine** |

The file-format conflict is explicitly time-dependent and the digest itself flags it — that one is
a versioning problem, not a contradiction. The first two are genuine and unresolved.

## New Israel-specific material (secondary; primaries need verification)

Omit age and home address (Drushim); military service / IDF unit as a credibility signal
(TechJob, ResumeFlex, Techmonster) — corroborating S-002; work experience placed **top** of
document (Techmonster); anonymised submissions on DevJobs; agency-vs-direct submission etiquette
(JobMob); peer review as an expected step (Jolt: 3–4 contacts; Facebook-group directory);
company-specific expectations (Wix, Wiz, Check Point).

---

# S-022 — Thirteen real CV images (`examples/cv 1–6/`) — BLOCKED

Six before/after pairs as PNG screenshots. **These are real people's CVs**: the filenames carry
real given names (`elnatan`, `michael`, `roni`, `ori`, `igal`), and the images will contain
whatever contact details the originals did.

**Status: the repository is PUBLIC** (`gh repo view` → `visibility: PUBLIC`,
github.com/nirtituani/CareerHQ) and these files are **not gitignored** — `git status` lists them
as untracked, one `git add -A` from permanent publication.

`CLAUDE.md` records this exact near-miss already: *"`testing files/` holds real CVs and is
gitignored. A CV carries a home address, a phone number and an employment history, and this
repository is public. It sat untracked for a while with `git add -A` in regular use, which is one
keystroke from publishing it permanently."*

**Disposition: BLOCKED pending consent and de-identification.** They are the evidentiary basis of
`before-after-analysis.md`, which stands on its own; the images themselves must not be committed.
