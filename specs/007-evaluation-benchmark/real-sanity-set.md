# The real-world sanity set *(T047, D2, FR-005c/FR-005d)*

**It answers exactly one question: does the synthetic benchmark overstate the
system?** It is not a source of headline numbers, and nothing in this slice's
success criteria depends on it.

## Why it is needed at all

A synthetic posting is cleaner than a real one — better structured, less redundant,
requirements actually enumerated. Both retrieval quality and requirement coverage
can be flattered by that, and **nothing in the harness would notice**, because the
harness only ever sees the benchmark. The real set is the control on the benchmark
itself.

## Where it lives, and why not here

**`~/CareerHQ-benchmark-real/` — outside the repository.**

`benchmark-real/` inside the repo is gitignored as well, but the default is a
directory that is not in the working tree at all. This repository is public and has
twice come within one `git add -A` of publishing real CVs; both times the files were
untracked and the ignore rule was the only thing standing between a home address and
permanent publication. **A path outside the tree removes that single point of failure
rather than depending on it.** The evaluation backups at `~/CareerHQ-backups/` follow
the same rule for the same reason.

## It is deliberately unpopulated

Populating it means copying real job postings and a real profile — the author's own
CV, carrying a home address, a phone number and an employment history — onto disk.
**That is the author's action on the author's data, and it is not automated here.**
Nothing in the non-paid phases needs it.

`load_real_set()` loads it through exactly the same code path as the committed set
(`load_benchmark_set`), which does not know or care which it was handed. If the two
were parsed differently their metrics would not be comparable, and comparability is
the whole point.

## What may be committed from it

**Only the aggregate comparison** (FR-005d) — metric levels on the synthetic set
beside metric levels on the real one — labelled as coming from an unreproducible
source, so a reproducible figure and an unreproducible one are never presented as
the same kind of evidence.

**Never**: a posting, a profile, a résumé, a case file, or any per-case number from
which content could be reconstructed.

## How to read the result

If the synthetic set scores **materially better**, the benchmark is flattering the
system and the cases need hardening — `difficulty_report` and FR-005b are where that
work goes. If they are close, the synthetic set is doing its job and the committed,
reproducible baseline can be trusted on its own.

## Enforcement

`tests/unit/test_no_committed_pii.py` scans every committed benchmark file for
address, phone and non-`example.com` email patterns, and asserts the count of files
it examined — a scan that finds nothing must not pass silently.
