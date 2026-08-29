"""SC-008 (006) stays MISSED at 3.22%, in every artifact this slice writes (T004).

**D1, approved 2026-08-29.** Slice 006's SC-008 — retrieval's cost per run against
an unchanged ≤2% threshold — is **not** reinterpreted, replaced, superseded or
re-derived by slice 007. Slice 007 has its own SC-008, which asks an entirely
different question, and the two are one careless sentence away from being read as
an old figure and a corrected one.

**Why a test and not a convention.** A flattering number is already available and
arithmetically derivable: dividing the same numerator by the older `$0.446391`
baseline gives **1.68%**, which would read as a pass. T052 measured it, wrote down
why it is not the same-session measurement, and declined to record it. Nothing but
a gate keeps a later document from quietly picking it up again.

**This test asserts the count of what it examined.** A scan that finds no files
passes forever, and this project has shipped four gates that examined nothing.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SLICE_DIR = REPO_ROOT / "specs" / "007-evaluation-benchmark"

#: Files outside `specs/007-*` that this slice also writes, and where a restated
#: verdict would be hardest to notice. `HANDOFF.md` in particular is read first by
#: every future session, so a wrong number there propagates furthest.
EXTERNAL_ARTIFACTS = ("HANDOFF.md", "CLAUDE.md")

#: The measured result and the unchanged threshold. Nothing else may be attributed
#: to slice 006's SC-008.
PERMITTED = {"3.22", "2"}

_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")

#: Artifacts exempt from the *disambiguation* rule only — never from the figure
#: rule, which is the load-bearing one and applies everywhere.
#:
#: **`HANDOFF.md` is deferred to T049, and the reason is mechanical rather than
#: editorial.** Its authoritative version is an uncommitted rewrite living in the
#: primary worktree; editing the committed copy here would collide with work that
#: is not in git and cannot be merged by git. Its every mention of SC-008 predates
#: slice 007 and means slice 006's, so it is currently correct and will become
#: ambiguous the moment this slice ships. **That is real outstanding work, named
#: here so it is visible rather than quietly excluded.**
DISAMBIGUATION_DEFERRED = frozenset({"HANDOFF.md"})


def _artifacts() -> list[pathlib.Path]:
    files = sorted(SLICE_DIR.rglob("*.md"))
    files += [REPO_ROOT / name for name in EXTERNAL_ARTIFACTS if (REPO_ROOT / name).exists()]
    return files


def test_the_scan_has_something_to_examine() -> None:
    """A gate with nothing to examine passes forever. Shipped four times here."""
    files = _artifacts()
    assert len(files) >= 8, f"expected the slice's artifacts, scanned only {len(files)}"

    mentions = sum(path.read_text().count("SC-008") for path in files)
    assert mentions >= 20, f"expected SC-008 to be discussed, found {mentions} mentions"


def test_no_artifact_attributes_any_other_figure_to_slice_006s_sc008() -> None:
    """The load-bearing assertion: 3.22% and the 2% threshold, nothing else.

    1.68% is the specific number this exists to keep out — real, derivable, and
    flattering.
    """
    offences: list[str] = []
    examined = 0

    for path in _artifacts():
        lines = path.read_text().splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "SC-008 (006)" not in line:
                continue
            examined += 1
            # History may be cited — 2.12% is the real pre-T052 figure and the
            # citation-overhead finding rests on it — but only with the current
            # value beside it. That is the difference between recording that the
            # number moved and quietly leaving a superseded one standing.
            window = " ".join(lines[max(0, lineno - 3) : lineno + 3])
            for value in _PERCENT.findall(line):
                if value in PERMITTED:
                    continue
                if "3.22" in window:
                    continue
                offences.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} attributes {value}% to "
                    f"SC-008 (006) with no 3.22% beside it; only 3.22% (the result) and "
                    f"2% (the unchanged threshold) may stand alone — {line.strip()[:110]}"
                )

    assert examined >= 10, (
        f"expected many disambiguated references to examine, found {examined}. "
        "A scan matching nothing is not a gate."
    )
    assert not offences, "\n".join(offences)


def test_every_artifact_that_discusses_both_criteria_disambiguates() -> None:
    """Two criteria share a number. A file using both must say which is which."""
    offences: list[str] = []
    examined = 0

    for path in _artifacts():
        if path.name in DISAMBIGUATION_DEFERRED:
            continue
        text = path.read_text()
        if "SC-008" not in text:
            continue
        examined += 1
        # A file that mentions slice 006 at all and then says "SC-008" without the
        # disambiguator is exactly the ambiguity this rule exists to prevent.
        mentions_006 = "006" in text or "slice 006" in text.lower()
        if mentions_006 and "SC-008 (006)" not in text:
            offences.append(
                f"{path.relative_to(REPO_ROOT)} mentions SC-008 and slice 006 but never "
                f"writes 'SC-008 (006)'. The two criteria are different questions."
            )

    assert examined >= 5, f"expected several files to examine, found {examined}"
    assert not offences, "\n".join(offences)


def test_the_verdict_is_stated_as_missed_wherever_it_is_stated_at_all() -> None:
    """3.22% recorded without 'MISSED' beside it reads as a result, not a failure."""
    offences: list[str] = []
    examined = 0

    for path in _artifacts():
        lines = path.read_text().splitlines()
        for lineno, line in enumerate(lines, start=1):
            if "3.22" not in line:
                continue
            examined += 1
            # The verdict may sit on the line itself or in its immediate
            # neighbourhood — prose wraps, and a rule that demanded both on one
            # line would be a rule about formatting rather than about meaning.
            window = " ".join(lines[max(0, lineno - 3) : lineno + 2]).lower()
            if "miss" not in window:
                offences.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno} states 3.22% with no 'missed' "
                    f"nearby — {line.strip()[:110]}"
                )

    assert examined >= 8, f"expected the figure to appear repeatedly, found {examined}"
    assert not offences, "\n".join(offences)
