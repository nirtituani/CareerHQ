# The optimised synthesis prompt — **candidate, measured on Gemini only**

The exact text benchmarked in OQ-J. Recorded here because it lives nowhere else: the experiment
built it as a delta on `research_company._PROMPT` in a scratch harness, and that harness is not
version-controlled.

**Insert both blocks immediately before .** Nothing else in the prompt
changes; the sources block and every other instruction stay byte-identical.

**Do not adopt the first block without the second.** The density instructions are what raised
Gemini from 50% to 76% of Claude's claim count and tripled its citations; the anti-fabrication
block is what kept the rejection rate at 1.7% while that happened. Separated, the first is an
instruction to pad.

**Measured on Gemini 3.6 Flash only.** Adopting it changes the production default's behaviour on an
untested assumption — one Claude pass to verify costs about /bin/zsh.70 and has not been authorised.

**One word changed on adoption.** The benchmarked text said "something a *candidate* would want to
know"; `test_the_prompt_never_mentions_a_role_or_a_job` forbids `candidate` in the Layer 1 prompt,
because FR-021 requires this layer to read identically for two different jobs at the same employer
and that word nudges the model toward one applicant. It now reads "a *reader*", matching the framing
the prompt already uses above. The gate was **not** loosened to accommodate the text.

---

## How much to extract

**Extract every materially useful fact the sources contain — not a summary of them.**
A reader should not have to open the sources afterwards to learn something important
that was there. Aim for completeness over brevity: if a source states something a
reader would want to know before an interview, it belongs in the profile.

Concrete particulars are the most valuable and the most often omitted. Include, wherever
a source states them:

- **people** — founders, executives, their names, roles and previous companies
- **customers and partners**, named
- **products**, each one distinctly, with what it actually does
- **numbers and dates** — headcount, funding rounds and amounts, valuations, revenue,
  customer counts, growth figures, founding year, launch dates
- **locations** — headquarters, offices, where roles are based
- **technology, methods and stack**, where described

Prefer several specific claims over one general one. "Acme raised $65M in a Series B led
by X in March 2026" is worth more than "Acme is well funded", and both may be supported
by the same passage.

**Where several sources support the same fact, cite them all** in `evidence` rather than
picking one — independent corroboration is information in itself.

**Say so when sources disagree.** If two sources give different figures, dates or
descriptions, do not silently choose one and do not average them. State the discrepancy
as its own claim, quoting both, or record it as an `interpretation` naming the facts it
rests on. A contradiction a reader would want to know about is a finding, not noise.

**Fill all five sections with real content** where the sources allow it. `empty_reason`
is for a section the sources genuinely do not cover, not for one that would take effort.

## The one thing that overrides all of the above

**Never invent anything to raise the count.** Every `fact` must quote a passage that
appears WORD FOR WORD in the retrieved page; a fabricated or paraphrased quotation is
discarded automatically and is worse than a missing claim. Do not stretch a source to
cover a claim it does not make, do not merge two sources into a fact neither states, and
do not promote an `inference` to a `fact` because it sounds better. If the sources are
thin, a short honest profile is the correct output.
