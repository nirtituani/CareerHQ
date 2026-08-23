"""Every task name a caller uses must have a model configured for it.

`model_for_task` deliberately does **not** raise on an unknown task — a
workflow that breaks on a name it has never seen is a worse failure than one
that runs (contracts/extraction-seam.md O3). The cost of that choice is that a
missing entry is invisible: the call succeeds, the output is fine, and it
silently runs on `llm_provider_model`, which is **Opus**.

That is roughly 2.5x the price for no gain, and it has already happened once in
this project — CV extraction ran on the fallback until someone measured it.

So the safety net is here rather than in `model_for_task`: the source tree is
read for every `task=` literal in `application/`, and each one must resolve to a
setting that is not the fallback. Four lines of test against a failure mode that
costs real money and announces nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

from careerhq.config import Settings

SRC = Path(__file__).resolve().parents[2] / "src" / "careerhq"


def _module_level_strings(tree: ast.Module) -> dict[str, str]:
    """Module-level `NAME = "literal"` assignments, by name.

    Needed because no call site passes a bare literal. Every one of them reads
    `task=TASK`, where `TASK` is a module constant — which is the better style,
    and which made the first version of this walk find nothing at all.
    """
    constants: dict[str, str] = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = node.value.value

    return constants


def _task_names_used_in_application() -> set[str]:
    """Every task name passed as `task=` under `application/`.

    Resolves both a bare literal and a module-level constant. A task name
    computed at run time would be missed — and would also defeat the point of
    naming tasks statically, so if one ever appears the fix is at the call site.
    """
    names: set[str] = set()

    for path in (SRC / "application").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        constants = _module_level_strings(tree)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "task":
                    continue
                value = keyword.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    names.add(value.value)
                elif isinstance(value, ast.Name) and value.id in constants:
                    names.add(constants[value.id])

    return names


def test_every_task_name_has_its_own_model_configured() -> None:
    """A task with no entry falls back to Opus, silently and expensively."""
    settings = Settings()
    used = _task_names_used_in_application()

    # A guard on the guard: if the AST walk stops finding call sites — because
    # a helper starts wrapping `complete()`, say — this test would pass by
    # examining nothing at all, which is the failure mode it exists to prevent.
    assert used, "found no `task=` call sites in application/ — the walk is broken, not the config"

    unconfigured = sorted(
        task for task in used if getattr(settings, f"llm_model_{task}", None) in (None, "")
    )

    assert unconfigured == [], (
        "these tasks have no `llm_model_<task>` setting and will run on the "
        f"Opus fallback at ~2.5x the cost, without saying so: {unconfigured}"
    )


def test_the_fallback_is_still_the_expensive_one() -> None:
    """The premise of the test above, asserted rather than assumed.

    If `llm_provider_model` were ever changed to a cheap model, the test above
    would still pass while protecting nothing — and the comment explaining why
    it exists would quietly become false.
    """
    assert "opus" in Settings().llm_provider_model.lower()
