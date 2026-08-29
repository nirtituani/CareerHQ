"""No committed benchmark file may carry real personal data (T047, FR-039).

**This repository is public**, and it has twice come within one `git add -A` of
publishing real CVs: `testing files/`, and thirteen screenshots carrying real given
names. Both times the files were untracked and an ignore rule was the only thing
standing between a home address and permanent publication.

**The scan asserts the count of what it examined.** A scan that finds no files
passes forever, and this project has shipped that failure four times.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
BENCHMARK = REPO_ROOT / "backend" / "benchmark"

#: Resolved absolutely: a partial executable path is resolved against PATH, which is
#: the caller's to control.
_GIT = shutil.which("git") or "git"

#: `example.com` only. pydantic's `EmailStr` rejects reserved TLDs like `.test` and
#: `.invalid`, and a scratch user seeded with one makes `/api/auth/me` return 500 —
#: which surfaces as a white-screen page and reads like an application bug.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?:\+\d{1,3}[\s-]?)?(?:\(\d{2,4}\)[\s-]?)?\d{3}[\s-]?\d{3,4}[\s-]?\d{3,4}")
_STREET = re.compile(
    r"\b\d{1,4}\s+\w+\s+(street|st\.|road|rd\.|avenue|ave\.|lane|drive|blvd)\b", re.I
)


def _committed_benchmark_files() -> list[pathlib.Path]:
    return sorted(BENCHMARK.rglob("*.md"))


def test_the_scan_has_something_to_examine() -> None:
    files = _committed_benchmark_files()
    assert len(files) >= 16, (
        f"expected the 12 cases, 4 profile states and the rubric; scanned {len(files)}"
    )


def test_no_committed_benchmark_file_carries_a_non_example_email() -> None:
    offences: list[str] = []
    examined = 0
    for path in _committed_benchmark_files():
        text = path.read_text()
        for address in set(_EMAIL.findall(text)):
            examined += 1
            if not address.endswith("example.com"):
                offences.append(f"{path.relative_to(REPO_ROOT)}: {address}")
    assert examined >= 4, f"expected the profile states' addresses; found {examined}"
    assert not offences, "\n".join(offences)


def test_no_committed_benchmark_file_carries_a_phone_number_or_street_address() -> None:
    offences: list[str] = []
    for path in _committed_benchmark_files():
        text = path.read_text()
        if _STREET.search(text):
            offences.append(f"{path.relative_to(REPO_ROOT)}: street address")
        # Dates, counts and money are not phone numbers. Only a clearly-formatted
        # international or grouped number counts, and the profile states carry none.
        for hit in _PHONE.findall(text):
            digits = re.sub(r"\D", "", hit)
            if len(digits) >= 9 and hit.strip().startswith("+"):
                offences.append(f"{path.relative_to(REPO_ROOT)}: {hit}")
    assert not offences, "\n".join(offences)


def test_the_real_sanity_set_directory_is_ignored_by_git() -> None:
    """Asked of git itself, never of `.gitignore` as text.

    A rule that is present but shadowed by a later negation reads as protection and
    is not. `git check-ignore` is the only authority on what git will do.
    """
    # S603 suppressed by code: the argument vector is a resolved `git` and two
    # literals this test wrote. Nothing is untrusted, and asking git rather than
    # reading `.gitignore` is the whole point — a rule shadowed by a later negation
    # reads as protection and is not.
    result = subprocess.run(  # noqa: S603
        [_GIT, "check-ignore", "-v", "benchmark-real/anything.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "benchmark-real/ is NOT ignored by git; a real posting placed there would be "
        f"one `git add -A` from publication. git said: {result.stdout}{result.stderr}"
    )
    assert "benchmark-real" in result.stdout


def test_the_real_set_default_lives_outside_the_repository() -> None:
    """Defence in depth: the ignore rule must not be the only thing protecting it."""
    from careerhq.application.evaluation.benchmark_set import REAL_SET_DEFAULT_ROOT

    assert REPO_ROOT not in REAL_SET_DEFAULT_ROOT.parents
    assert REAL_SET_DEFAULT_ROOT != REPO_ROOT


def test_nothing_under_the_real_set_directory_is_tracked_by_git() -> None:
    # S603 suppressed by code: a resolved `git` and two literals, as above.
    result = subprocess.run(  # noqa: S603
        [_GIT, "ls-files", "benchmark-real/"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert result.stdout.strip() == "", f"tracked files under benchmark-real/: {result.stdout}"
