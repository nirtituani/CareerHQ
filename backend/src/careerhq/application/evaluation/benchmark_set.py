"""The fixed, versioned benchmark set — postings paired with profile states.

**Files, not rows** (FR-005). A benchmark reproducible from version-controlled
inputs cannot depend on what somebody seeded by hand, and a case that lives in a
Docker volume is a case that vanishes with `docker compose down -v`. The format is
YAML front-matter plus a markdown body, the same as `backend/corpus/`, so a case is
reviewable in a pull request like any other change.

**Editing a case is a new version, never an edit in place** (FR-002). The version
is the directory name. This is the rule the match criteria and the finalisation
rules already follow, for the reason all three share: an edit silently makes every
historical result incomparable, and nothing announces it.

**Fully synthetic, and that is a privacy decision rather than a convenience one**
(FR-005a, FR-039, D2). This repository is public and has twice come within one
`git add -A` of publishing real CVs. The precedent is `backend/tests/fixtures`,
whose subject is fictional precisely so it can be committed. The real-world sanity
set (FR-005c) lives in a gitignored directory and is loaded by the same code —
`load_benchmark_set` does not know or care which it was handed, which is what keeps
the comparison honest.
"""

from __future__ import annotations

import itertools
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

import yaml


class BenchmarkSetError(RuntimeError):
    """The set could not be loaded, or is not a set.

    **Raised rather than returning an empty collection.** A benchmark that loads
    zero cases and reports clean metrics is the same failure as a route
    enumeration that walks zero routes, and this project has shipped that four
    times.
    """


_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_WORD = re.compile(r"[a-z][a-z+#.-]{2,}")

#: Words that appear in every job posting ever written and so carry no signal
#: about what a posting is *about*. Used only by the overlap statistic, which
#: exists to catch a set of near-duplicate postings.
_STOPWORDS = frozenset(
    """the and for with you our are will that this have has been from their they
    role team work working experience years must nice should would can able job
    about who what when where which your not but all any into more than other
    across within using use used strong good great excellent required requirements
    responsibilities qualifications preferred plus bonus we us it its is of in on
    at to a an as be by or if we're you'll join looking seeking hiring apply""".split()
)


@dataclass(frozen=True, slots=True)
class ProfileState:
    """A synthetic professional profile one or more cases are tailored from.

    Held as plain data rather than as ORM objects: a state is an input to a run,
    and materialising it is the runner's job, done against a scratch user.
    """

    state_id: str
    full_name: str
    email: str
    headline: str
    summary: str
    experiences: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, str]] = field(default_factory=list)
    education: list[dict[str, str]] = field(default_factory=list)
    languages: list[dict[str, str]] = field(default_factory=list)
    certifications: list[dict[str, str]] = field(default_factory=list)
    projects: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One posting paired with one profile state."""

    case_id: str
    discipline: str
    role: str
    seniority: str
    profile_state: str
    company: str
    posting_text: str
    requirements: tuple[str, ...]
    must_have: tuple[str, ...]
    #: Requirements this profile genuinely does not cover.
    #:
    #: **The AI-008 test material.** A case with no gap gives the agent nothing to
    #: be honest *about* — the temptation to fabricate exists only where there is
    #: something missing — so at least one case in a set must have some (FR-005b).
    #: It is an authored property of the pairing, not a model's opinion of it.
    expected_gaps: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkSet:
    """A version of the set: its cases, and the profile states they pair with."""

    version: str
    cases: tuple[BenchmarkCase, ...]
    profiles: dict[str, ProfileState]

    @property
    def case_count(self) -> int:
        """Read by the runner's projection.

        **A count, never a constant.** D3 approved twelve cases; a projection that
        assumed twelve would authorise a ceiling check for a run that was about to
        do something else entirely.
        """
        return len(self.cases)


def _parse(path: pathlib.Path) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(path.read_text())
    if match is None:
        raise BenchmarkSetError(f"{path.name}: expected YAML front-matter delimited by ---")
    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise BenchmarkSetError(f"{path.name}: front-matter is not valid YAML: {exc}") from exc
    if not isinstance(meta, dict):
        raise BenchmarkSetError(f"{path.name}: front-matter must be a mapping")
    return meta, match.group(2).strip()


def _required(meta: dict[str, Any], key: str, path: pathlib.Path) -> Any:
    if key not in meta or meta[key] in (None, ""):
        raise BenchmarkSetError(f"{path.name}: missing required front-matter key {key!r}")
    return meta[key]


#: Where the D2 real-world sanity set lives **by default: outside the repository.**
#:
#: `benchmark-real/` inside the repo is gitignored as defence in depth, but the
#: default is a directory that is not in the working tree at all — because this
#: project has twice come within one `git add -A` of publishing real CVs, and both
#: times the file was untracked and the ignore rule was the only thing standing
#: between a home address and a public repository. A path outside the tree removes
#: that single point of failure rather than relying on it. The backups at
#: `~/CareerHQ-backups/` already follow the same rule for the same reason.
REAL_SET_DEFAULT_ROOT = pathlib.Path.home() / "CareerHQ-benchmark-real"


def load_real_set(version: str = "v1", *, root: pathlib.Path | None = None) -> BenchmarkSet:
    """Load the gitignored real-world sanity set (D2, FR-005c).

    **Identical loading, deliberately.** It goes through `load_benchmark_set`, which
    has no idea which set it was handed — if the two were parsed differently their
    metrics would not be comparable, and comparability is the sanity set's entire
    purpose. It answers one question: *does the synthetic set overstate the system?*

    **Only the aggregate comparison may ever be committed** (FR-005d), labelled as
    coming from an unreproducible source.
    """
    base = root or REAL_SET_DEFAULT_ROOT
    if not (base / version).is_dir():
        raise BenchmarkSetError(
            f"no real sanity set at {base / version}. It is populated by hand from real "
            "postings and a real profile, it lives OUTSIDE this repository on purpose, "
            "and it is never committed — see specs/007-evaluation-benchmark/"
            "real-sanity-set.md."
        )
    return load_benchmark_set(version, root=base)


def load_benchmark_set(version: str, *, root: pathlib.Path | None = None) -> BenchmarkSet:
    """Load one version of the set, or refuse.

    `root` defaults to `backend/benchmark/`. Passing the gitignored real-world
    directory loads it identically — the loader has no idea which it was given,
    and it must not, or the two would stop being comparable.
    """
    base = (root or pathlib.Path(__file__).resolve().parents[4] / "benchmark") / version
    if not base.is_dir():
        raise BenchmarkSetError(
            f"no benchmark set {version!r} at {base}. Editing a case is a new version, "
            "never an edit in place — so a missing version is a missing directory."
        )

    profiles: dict[str, ProfileState] = {}
    for path in sorted((base / "profiles").glob("*.md")):
        meta, _ = _parse(path)
        state_id = str(_required(meta, "state_id", path))
        profiles[state_id] = ProfileState(
            state_id=state_id,
            full_name=str(_required(meta, "full_name", path)),
            email=str(_required(meta, "email", path)),
            headline=str(meta.get("headline") or ""),
            summary=str(meta.get("summary") or ""),
            experiences=list(meta.get("experiences") or []),
            skills=list(meta.get("skills") or []),
            education=list(meta.get("education") or []),
            languages=list(meta.get("languages") or []),
            certifications=list(meta.get("certifications") or []),
            projects=list(meta.get("projects") or []),
        )

    cases: list[BenchmarkCase] = []
    for path in sorted((base / "cases").glob("*.md")):
        meta, body = _parse(path)
        requirements = tuple(str(r) for r in (meta.get("requirements") or []))
        must_have = tuple(str(r) for r in (meta.get("must_have") or []))
        unknown = [r for r in must_have if r not in requirements]
        if unknown:
            raise BenchmarkSetError(
                f"{path.name}: must_have names requirements the case does not state: {unknown}"
            )
        cases.append(
            BenchmarkCase(
                case_id=str(_required(meta, "case_id", path)),
                discipline=str(_required(meta, "discipline", path)),
                role=str(_required(meta, "role", path)),
                seniority=str(_required(meta, "seniority", path)),
                profile_state=str(_required(meta, "profile_state", path)),
                company=str(_required(meta, "company", path)),
                posting_text=body,
                requirements=requirements,
                must_have=must_have,
                expected_gaps=tuple(str(g) for g in (meta.get("expected_gaps") or [])),
            )
        )

    if not cases:
        raise BenchmarkSetError(
            f"benchmark set {version!r} holds no cases. A set that loads nothing and "
            "reports clean metrics is not a benchmark."
        )

    ids = [c.case_id for c in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise BenchmarkSetError(f"duplicate case ids in {version!r}: {sorted(duplicates)}")

    missing = sorted({c.profile_state for c in cases} - set(profiles))
    if missing:
        raise BenchmarkSetError(f"cases reference unknown profile states: {missing}")

    return BenchmarkSet(version=version, cases=tuple(cases), profiles=profiles)


def _vocabulary(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOPWORDS}


def difficulty_report(benchmark: BenchmarkSet) -> dict[str, Any]:
    """Whether the set can measure anything, as numbers rather than as a claim.

    **A synthetic posting is cleaner than a real one** — better structured, less
    redundant, requirements actually enumerated — so retrieval quality and
    requirement coverage can both be flattered by the benchmark rather than earned
    by the system, with nothing noticing. These figures are what T016 asserts on.

    **The overlap statistic is computed over the stated requirements, not over the
    posting prose, and that correction came from a measurement.** Run over the full
    body, the most similar pair in this set was `fi-02-audit-senior` and
    `rn-01-icu-senior` — external audit and intensive care — at 0.205, against a
    least-similar pair of 0.097. A metric that ranks audit and ICU as the closest
    two postings in a set containing three backend roles is measuring the author's
    voice and the scaffolding every advert shares ("Essential:", "We are looking
    for"), not what the postings are about. The requirements are authored per case,
    carry the domain vocabulary, and contain none of that scaffolding.

    It remains a **crude** measure used as a floor rather than a score: its job is
    to catch twelve variations on one backend role. The sharper version of this
    question — do two postings actually retrieve different guidance? — is answered
    for free by retrieval itself, and belongs to the retrieval-quality metric.
    """
    vocabularies = {
        c.case_id: _vocabulary(" ".join((*c.requirements, c.role, c.discipline)))
        for c in benchmark.cases
    }
    prose = {c.case_id: _vocabulary(c.posting_text) for c in benchmark.cases}

    worst = 0.0
    worst_pair: tuple[str, str] | None = None
    best = 1.0
    best_pair: tuple[str, str] | None = None
    for left, right in itertools.combinations(benchmark.cases, 2):
        a, b = vocabularies[left.case_id], vocabularies[right.case_id]
        union = a | b
        if not union:
            continue
        overlap = len(a & b) / len(union)
        if overlap > worst:
            worst, worst_pair = overlap, (left.case_id, right.case_id)
        if overlap < best:
            best, best_pair = overlap, (left.case_id, right.case_id)

    return {
        "cases": len(benchmark.cases),
        "disciplines": len({c.discipline for c in benchmark.cases}),
        "seniorities": len({c.seniority for c in benchmark.cases}),
        "profile_states": len({c.profile_state for c in benchmark.cases}),
        "cases_with_expected_gaps": sum(1 for c in benchmark.cases if c.expected_gaps),
        "cases_with_must_haves": sum(1 for c in benchmark.cases if c.must_have),
        "max_pairwise_vocabulary_overlap": round(worst, 3),
        "most_similar_pair": worst_pair,
        # The floor that actually matters: a set whose least-similar pair is still
        # similar has one register, and a guidance difference between two of its
        # cases cannot be attributed to the posting.
        "min_pairwise_vocabulary_overlap": round(best, 3) if best_pair else 0.0,
        "least_similar_pair": best_pair,
        # Kept because it is what the first draft asserted on, and because a rising
        # prose overlap would mean the postings are drifting into one voice even
        # while their requirements stay distinct.
        "max_pairwise_prose_overlap": round(
            max(
                (
                    len(prose[a.case_id] & prose[b.case_id])
                    / len(prose[a.case_id] | prose[b.case_id])
                    for a, b in itertools.combinations(benchmark.cases, 2)
                    if prose[a.case_id] | prose[b.case_id]
                ),
                default=0.0,
            ),
            3,
        ),
    }


__all__ = [
    "REAL_SET_DEFAULT_ROOT",
    "BenchmarkCase",
    "BenchmarkSet",
    "BenchmarkSetError",
    "ProfileState",
    "difficulty_report",
    "load_benchmark_set",
    "load_real_set",
]
