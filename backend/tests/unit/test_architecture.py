"""Boundaries asserted against the source tree rather than against memory.

Some rules cannot be tested by calling anything, because what they forbid is a
*shape* — which module may import what. Those rules survive only if something
checks them, since nothing fails at runtime when they are broken. The system
keeps working; it just stops being the system that was designed.
"""

from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "careerhq"


def _modules_importing(package: str) -> set[str]:
    """Every module under src/careerhq with a direct import of `package`."""
    found: set[str] = set()

    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name == package or a.name.startswith(f"{package}.") for a in node.names):
                    found.add(str(path.relative_to(SRC)))
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod == package or mod.startswith(f"{package}."):
                    found.add(str(path.relative_to(SRC)))

    return found


def test_only_the_gateway_imports_the_provider_sdk() -> None:
    """T032 — Constitution Principle V, as a property of the import graph.

    "Business Domains ... MUST NOT call AI providers. All AI execution flows
    through the Agent Runtime and AI Gateway." That holds only while exactly one
    module can reach the provider. Nothing fails at runtime if a second one
    appears — the code works, and the boundary the architecture depends on is
    quietly gone.

    If this fails, the fix is to route the new caller through
    `application/ports.StructuredCompletion`, not to add it to this list.
    """
    importers = _modules_importing("litellm")

    assert importers == {"infrastructure/ai/litellm_gateway.py"}, (
        f"litellm must be imported by the gateway alone; found: {sorted(importers)}"
    )


def test_the_domain_layer_imports_no_framework_or_provider_code() -> None:
    """Principle V's other half, and what keeps the domain testable.

    `domain/` describes the business, so it may not depend on the web framework,
    the AI gateway, or any provider SDK. SQLAlchemy is permitted: the models are
    the schema, and the constraints they declare are where the invariants live.
    """
    forbidden = ("fastapi", "litellm", "boto3", "redis", "httpx", "authlib")
    offenders: dict[str, list[str]] = {}

    for path in (SRC / "domain").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
        hits = sorted({n for n in names if n in forbidden})
        if hits:
            offenders[str(path.relative_to(SRC))] = hits

    assert offenders == {}, f"domain/ must import no framework or provider code: {offenders}"


def test_the_application_layer_imports_no_provider_sdk() -> None:
    """`application/` orchestrates; it depends on ports, never on adapters.

    A single import here would make Principle V a matter of discipline again,
    since the layer that owns the use case would be able to reach the provider
    directly.
    """
    forbidden = ("litellm",)
    offenders: dict[str, list[str]] = {}

    for path in (SRC / "application").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module.split(".")[0])
        hits = sorted({n for n in names if n in forbidden})
        if hits:
            offenders[str(path.relative_to(SRC))] = hits

    assert offenders == {}, f"application/ must depend on ports, not adapters: {offenders}"


def test_the_uploaded_file_is_read_by_exactly_one_module() -> None:
    """T033 — FR-006 and ADR-013 both rest on an absence.

    "The uploaded file is retained for reference but is not the source of truth
    for any downstream capability. No downstream feature reads the original
    file." That is a claim about what does **not** read it, so nothing fails
    when a second reader appears — the feature works, and the architectural
    claim quietly stops being true.

    `extract_resume` writes the key; `imports.py` reads it in exactly one route,
    to serve the file back to the person who uploaded it. Nothing else may.

    **Widened once, deliberately.** The list held two entries until the profile
    gained a viewer for the original CV. The distinction that keeps ADR-013
    intact is that *looking at* the upload is not *deriving from* it: no
    extraction, scoring or tailoring path may read these bytes, and the
    structured profile remains the only thing the system reasons over. If a
    fourth entry is ever proposed, ask which of those two it is — a reader that
    feeds a capability is the thing this test exists to stop.
    """
    permitted = {
        "domain/models/imports.py",  # declares the column
        "application/extract_resume.py",  # writes it
        "api/routes/imports.py",  # serves it back, and only to its owner
    }
    readers: set[str] = set()

    # Parsed rather than grepped: a mention in a docstring or a comment is not a
    # read, and a text search would have counted this test's own explanation of
    # itself. What matters is `something.storage_key` appearing in real code.
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Attribute):
                names.append(node.attr)
            elif isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.keyword) and node.arg:
                names.append(node.arg)
            if "storage_key" in names:
                readers.add(str(path.relative_to(SRC)))

    assert readers <= permitted, (
        "the retained upload must stay write-only; unexpected readers: "
        f"{sorted(readers - permitted)}"
    )
