"""FR-017: only the Advisor capability reads or writes career memories (T046).

Memories are AI-derived interpretation *about* the user, and the moment any
other capability treats them as profile facts — tailoring reading a "strength"
memory as if it were experience, matching weighing a remembered gap — the
derived layer has become a second source of truth, which is the exact thing
Principle I forbids. The claim is an absence, and an absence decays silently:
the day someone adds the import, every behavioural test still passes.

So: **every mention of the three advisor classes anywhere in `src/` must be on
the whitelist, and anything else fails** — the `SubmittedResume` gate's
inversion, because a blacklist of forbidden operations was walked straight
through once (`_touch(session, Model, ...)` names no forbidden function).
Mentions are counted by name, attribute access, alias binding and string
literal, so a module cannot smuggle a reference through
`getattr(models, "CareerMemory")`.

Two count assertions keep the gate honest: the walk must examine files, and
the whitelisted modules must actually mention the classes — a rename that
silently emptied the gate fails it instead.

Drilled at T046: a temporary `CareerMemory` reference in
`application/tailor_resume.py` was watched failing with that file named.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "careerhq"

_ADVISOR_CLASSES = frozenset({"CareerMemory", "MemoryDisposition", "AdvisorRun"})

#: The Advisor capability, and nothing else. `domain/models/__init__.py` is
#: the re-export hub every model passes through; the rest are the modules the
#: plan names. Adding a file here is a reviewed decision, not a convenience.
_WHITELIST = frozenset(
    {
        "domain/models/advisor.py",
        "domain/models/__init__.py",
        "application/advise_career.py",
        "application/advisor_evidence.py",
        "application/advisor_grounding.py",
        "api/routes/advisor.py",
    }
)


def _mentions_advisor_classes(tree: ast.Module) -> set[str]:
    """Every advisor class this module mentions, however it spells it."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in _ADVISOR_CLASSES:
            found.add(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in _ADVISOR_CLASSES:
            found.add(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.update(_ADVISOR_CLASSES & {node.value})
        elif isinstance(node, ast.ImportFrom):
            found.update(_ADVISOR_CLASSES & {alias.name for alias in node.names})
    return found


def test_only_the_advisor_capability_touches_career_memories() -> None:
    examined = 0
    violations: list[str] = []
    whitelisted_mentions: set[str] = set()

    for path in SRC.rglob("*.py"):
        examined += 1
        relative = str(path.relative_to(SRC))
        mentioned = _mentions_advisor_classes(ast.parse(path.read_text(), filename=str(path)))
        if not mentioned:
            continue
        if relative in _WHITELIST:
            whitelisted_mentions.add(relative)
            continue
        violations.append(f"{relative} mentions {sorted(mentioned)}")

    assert not violations, (
        "career memories are the Advisor's alone (FR-017); these modules must not "
        f"touch them: {violations}"
    )
    # A gate with nothing to examine passes forever — twice over.
    assert examined > 100, f"only {examined} files walked; the walk is broken"
    assert "domain/models/advisor.py" in whitelisted_mentions, (
        "the model module itself was not seen mentioning the classes — the gate is "
        "examining a tree that no longer contains them, which is a rename, not a pass"
    )
