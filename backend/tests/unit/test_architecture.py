"""Boundaries asserted against the source tree rather than against memory.

Some rules cannot be tested by calling anything, because what they forbid is a
*shape* — which module may import what. Those rules survive only if something
checks them, since nothing fails at runtime when they are broken. The system
keeps working; it just stops being the system that was designed.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib
import pkgutil

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

    **Widened in slice 005, in the same commit as the LangGraph dependency.**
    Until then this listed `litellm` alone, which was enough while every AI call
    was one `complete()` from a use case. LangGraph changes that: it pulls in
    `langchain-core`, so `langchain_anthropic` becomes one install away from
    working, and the idiomatic LangGraph example everyone copies binds a model
    *inside the node*. The dependency is what creates the hole, which is why the
    guard could not land after it (research.md R2).

    `langchain_core` is deliberately permitted — LangGraph's own types come from
    it, and forbidding it would forbid the orchestrator. The provider bindings
    are the boundary, not the abstraction.

    **Widened again in slice 006 (T007), in the same commit as `EmbeddingSource`.**
    Embedding is a second way for this layer to reach a model, and it is a
    quieter one: `fastembed` needs no API key, bills nothing, and runs in-process,
    so an import here would work perfectly and produce no signal of any kind —
    no cost line, no gateway log, nothing for `UsageRecorder` to record. The
    seam it would bypass is the one thing that makes "which model ran" answerable.

    `sentence_transformers`, `torch`, `transformers` and `huggingface_hub` are
    listed although **none is installed**. That is the point: the slice-006
    dependency decision rejected the sentence-transformers/PyTorch route on a
    measured 527 MB, and a rejection recorded only in prose is one `pip install`
    from being undone by whoever finds the obvious library first. A forbidden
    name that nothing imports costs nothing and refuses the undo.

    **Widened again in slice 008, for a different reason than the first two.**
    `httpx`, `requests`, `aiohttp`, `mcp` and `tavily` are not ways of reaching a
    *model* — they are ways of reaching the *internet*. Slice 008's entire trust
    story is that the search provider returns URLs and snippets and CareerHQ
    fetches the pages itself, through the SSRF guard in
    `infrastructure/jobs/fetch.py`. A use case that imported `httpx` directly
    could retrieve a page without the address check, the per-hop redirect
    re-check or the peer verification, and hand it to a model — and
    `SearchHit`'s no-page-content boundary would still *look* intact while being
    routed around entirely. The adapters live under `infrastructure/research/`,
    which this walk deliberately does not cover.

    **The count assertion is not decoration.** A guard with nothing to examine
    passes forever, and this project has shipped that failure four times — a
    route enumeration examining zero routes, a theme scan that never existed, an
    AST walk finding zero call sites, a `-k` selector matching no tests. This
    walk would report a clean layer if `SRC / "application"` were ever renamed.
    """
    forbidden = (
        "litellm",
        "anthropic",
        "openai",
        "langchain_anthropic",
        "langchain_openai",
        "langchain_community",
        # Slice 006: embedding runtimes. See the docstring — the last four are
        # forbidden precisely because they are absent.
        "fastembed",
        "onnxruntime",
        "sentence_transformers",
        "torch",
        "transformers",
        "huggingface_hub",
        # Slice 008: reaching the internet. See the docstring — a third way out
        # of this layer, and it leads outward rather than to a model. `mcp` is
        # listed although nothing imports it, for the same reason the PyTorch
        # names are: an MCP route was considered and dropped, and a rejection
        # recorded only in prose is one import from being undone.
        "httpx",
        "requests",
        "aiohttp",
        "mcp",
        "tavily",
    )
    offenders: dict[str, list[str]] = {}
    examined = 0

    for path in (SRC / "application").rglob("*.py"):
        examined += 1
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

    assert examined >= 15, (
        f"this guard examined {examined} files in application/; it is meant to walk the whole "
        "layer, and a walk that finds nothing passes whether or not the layer is clean"
    )
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


def test_every_writer_of_approved_item_content_asks_whether_it_may() -> None:
    """T039, FR-022 — the invariant is owned by one guard, and this is what keeps it so.

    A lock enforced by two functions remembering to call it stops being enforced the
    moment a third is written, and nothing fails: the new path works, the tests stay
    green, and a submitted resume becomes editable through a route nobody thought about.
    That is the same class of claim as the retained-upload rule above — a statement about
    what does **not** happen, which decays silently.

    So the writers are enumerated rather than bounded. `final_text`, `decision`,
    `included` and `position` are the columns that decide what an exported document says;
    every `application/` function that assigns to one must call `ensure_version_mutable`.
    **The list is explicit, not a minimum**: the value of the gate is that an unplanned
    writer fails it, and `>= 2` would have let a third through.

    A route may not appear here in its place. `api/` translates the refusal into 409, but
    a check that lives only in a route is exactly the arrangement this test refuses.
    """
    columns = {"final_text", "decision", "included", "position"}
    writers: dict[str, int] = {}
    guarded: set[str] = set()

    for path in (SRC / "application").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            written = sum(
                1
                for node in ast.walk(function)
                if isinstance(node, ast.Assign)
                for target in node.targets
                if isinstance(target, ast.Attribute) and target.attr in columns
            )
            if not written:
                continue
            writers[function.name] = written
            calls = {
                node.func.id
                for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            if "ensure_version_mutable" in calls:
                guarded.add(function.name)

    assert set(writers) == {"decide_item", "approve_version"}, (
        "a function writes approved item content that this gate has never seen: "
        f"{sorted(set(writers) - {'decide_item', 'approve_version'})}"
    )
    # The gate examined something. A walk that matched nothing would pass every
    # assertion above it and report a boundary it never looked at.
    assert sum(writers.values()) >= 5, f"the walk found almost nothing: {writers}"

    assert guarded == set(writers), (
        "these write approved item content without asking whether the version is locked: "
        f"{sorted(set(writers) - guarded)}"
    )


#: The model and its table, by name, for the modules that never import either.
_SUBMISSION_MODEL = "SubmittedResume"
_SUBMISSION_TABLE = "submitted_resumes"

#: The only modules permitted to name a submission at all.
#:
#: Enumerated rather than bounded, because the value of this list is that an unplanned
#: fifth module fails rather than quietly joining it. `submissions.py` reads (T040),
#: `submit_resume.py` writes exactly one row (T038), and the two `domain/models` entries
#: declare and re-export the class.
_MAY_NAME_A_SUBMISSION = {
    "domain/models/tailoring.py",
    "domain/models/__init__.py",
    "application/submit_resume.py",
    "application/submissions.py",
    # **Widened once, at T043, and the gate is what forced the decision to be made
    # deliberately.** `submission_out` renders a submission for a client and therefore has
    # to name its type. It is a read: the classifier below accounts for every mention in
    # it as an annotation or an attribute, and the module constructs nothing. Adding an
    # entry here is not a way past this gate — a module that names a submission and then
    # *does* something with it still fails on the classification.
    "api/routes/tailoring.py",
}


def _snapshot_columns() -> frozenset[str]:
    """Every column of both snapshot records, read off the models rather than listed.

    **Both**, and that is deliberate rather than sloppy: an export's checksum is exactly
    as sensitive as a submission's, and a gate covering one of the two would leave the
    same bytes reachable through the other. Derived so a column added later is covered
    without anyone remembering to come here.
    """
    from careerhq.domain.models import ExportedDocument, SubmittedResume

    return frozenset(
        {c.name for c in SubmittedResume.__table__.columns}
        | {c.name for c in ExportedDocument.__table__.columns}
    )


def _names_bound_to(tree: ast.AST, target: str) -> set[str]:
    """Every local name this module could refer to `target` by, aliases included.

    `from careerhq.domain.models import SubmittedResume as SR` is the cheapest way to hide
    a write from a gate that greps for a class name, so the binding is resolved rather
    than assumed.
    """
    bound: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            bound |= {a.asname or a.name for a in node.names if a.name == target}
        elif isinstance(node, ast.Import):
            bound |= {
                a.asname or a.name.split(".")[-1]
                for a in node.names
                if a.name.endswith(f".{target}")
            }
    return bound


def _mentions_a_submission(tree: ast.AST) -> bool:
    """Whether this module names the submission at all — by binding, attribute or string.

    All three, because all three reach it: `models.SubmittedResume` needs no import of the
    name, and a string is enough for `getattr` or for raw SQL against the table.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == _SUBMISSION_MODEL:
            return True
        if isinstance(node, ast.Attribute) and node.attr == _SUBMISSION_MODEL:
            return True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SUBMISSION_MODEL in node.value or _SUBMISSION_TABLE in node.value:
                return True
    return bool(_names_bound_to(tree, _SUBMISSION_MODEL))


def _annotation_nodes(tree: ast.AST) -> set[int]:
    """Ids of every node appearing inside a type annotation.

    Annotations mention the class constantly — `-> SubmittedResume | None` — and mentioning
    a type is not an operation on a row. Collected up front so the classifier below can
    treat every *remaining* mention as something that has to be accounted for.
    """
    inside: set[int] = set()
    for node in ast.walk(tree):
        annotations: list[ast.expr | None] = []
        if isinstance(node, ast.AnnAssign):
            annotations = [node.annotation]
        elif isinstance(node, ast.arg):
            annotations = [node.annotation]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            annotations = [node.returns]
        for annotation in annotations:
            if annotation is not None:
                inside |= {id(child) for child in ast.walk(annotation)}
    return inside


def test_a_submitted_resume_is_insert_only() -> None:
    """T042, FR-022 — **an absence claim**, and the reason it needs a gate of its own.

    T038 proves the insert happens, T039 locks *version content*, T041 proves the revision
    path does not disturb the record. **None of those is this claim.** This one is that no
    path anywhere can UPDATE an existing row — and an absence decays silently: the day
    someone adds one, every test above still passes, the feature works, and the only
    symptom is that the record of what a person sent to an employer stops being the record
    of what they sent. Constitution IV: *"A Submitted Resume is an immutable snapshot with
    a stable file checksum."*

    **Every mention of the class is classified, and the default is failure.** A blacklist
    of `update(...)` and `delete(...)` was the first shape of this gate, and a drill walked
    straight through it: `_touch(session, SubmittedResume, checksum_sha256=...)` names no
    forbidden function, so nothing fired. The rule is therefore inverted — construction,
    column reference, `select(...)` and type annotations are the accounted-for uses, and
    **anything else fails**, including handing the class to a helper whose body the gate
    never reads.

    **Three things are checked, because an update can arrive three ways.**

    1. **Who may name it at all**, aliases, attribute access and strings included, so a new
       module cannot quietly become a writer.
    2. **What the permitted modules do with it** — the whitelist above, plus `session.add`
       counted (the legitimate INSERT, which must stay singular) and `merge` refused
       outright, since it is an upsert wearing the clothes of a save.
    3. **Whether any snapshot column is assigned as an attribute anywhere in `src/`** —
       not only in the permitted modules. This is the half that survives what a syntax tree
       cannot do, which is infer that some local variable holds a submission. It does not
       need to: `record.checksum_sha256 = ...` is the only shape such an update can take,
       and there are zero of them in the tree.
    """
    permitted_add = "application/submit_resume.py"
    columns = _snapshot_columns()

    naming: set[str] = set()
    constructions = 0
    inserts = 0
    reads = 0
    unaccounted: list[str] = []
    forbidden: list[str] = []
    assignments: list[str] = []
    examined = 0

    for path in SRC.rglob("*.py"):
        examined += 1
        relative = str(path.relative_to(SRC))
        tree = ast.parse(path.read_text(), filename=str(path))

        # (3) Whole-tree, and deliberately not limited to the permitted modules.
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in columns:
                    assignments.append(f"{relative}:{node.lineno} .{target.attr} = ...")

        if not _mentions_a_submission(tree):
            continue
        if relative.startswith("domain/models/"):
            # The declaration itself. Every mention here is the class being defined or
            # re-exported, and the model's own columns are what (3) is derived from.
            naming.add(relative)
            continue
        naming.add(relative)

        aliases = _names_bound_to(tree, _SUBMISSION_MODEL) | {_SUBMISSION_MODEL}
        annotated = _annotation_nodes(tree)
        parents: dict[int, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[id(child)] = parent

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                called = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if called == "merge":
                    forbidden.append(f"{relative}:{node.lineno} session.merge")
                elif called in {"add", "add_all"} and relative == permitted_add:
                    # **Counted only where a submission is actually constructed.** A
                    # module that never builds one cannot add one, and counting every
                    # `session.add` in every module that merely *names* the class would
                    # fail on an unrelated insert — a false positive that teaches people
                    # to widen the gate rather than to read it.
                    inserts += 1
                elif called == "delete" and isinstance(node.func, ast.Attribute):
                    forbidden.append(f"{relative}:{node.lineno} session.delete")

            if not isinstance(node, ast.Name) or node.id not in aliases:
                continue
            if id(node) in annotated:
                continue

            parent = parents.get(id(node))
            if isinstance(parent, ast.Attribute):
                continue  # `SubmittedResume.application_id` — a column reference
            if isinstance(parent, ast.Call) and parent.func is node:
                constructions += 1
                if relative != permitted_add:
                    forbidden.append(f"{relative}:{node.lineno} a second writer")
                continue
            if isinstance(parent, ast.Call) and node in parent.args:
                called = (
                    parent.func.attr
                    if isinstance(parent.func, ast.Attribute)
                    else parent.func.id
                    if isinstance(parent.func, ast.Name)
                    else ""
                )
                if called == "select":
                    reads += 1
                    continue
                unaccounted.append(f"{relative}:{node.lineno} passed to {called}()")
                continue
            if isinstance(parent, ast.BinOp | ast.Subscript | ast.Tuple):
                continue  # a type expression the annotation walk could not reach
            unaccounted.append(f"{relative}:{node.lineno} used as {type(parent).__name__}")

    assert examined >= 40, f"the walk examined almost nothing: {examined} modules"
    assert naming == _MAY_NAME_A_SUBMISSION, (
        "a module that was not supposed to know submissions exist now names one: "
        f"{sorted(naming - _MAY_NAME_A_SUBMISSION)}; missing: "
        f"{sorted(_MAY_NAME_A_SUBMISSION - naming)}"
    )
    assert forbidden == [], f"a submission can be modified after it is written: {forbidden}"
    assert unaccounted == [], (
        "the submission is used in a way this gate cannot account for; if it is a read, "
        f"say so here, and if it can write, it may not exist: {unaccounted}"
    )
    assert assignments == [], (
        "a snapshot column is assigned as an attribute, which is an UPDATE the moment the "
        f"row is persistent: {assignments}"
    )
    assert (constructions, inserts) == (1, 1), (
        f"expected exactly one construction and one session.add, found {constructions} and "
        f"{inserts} — the insert is legitimate and must stay singular"
    )
    assert reads >= 1, "the read path vanished; the gate is no longer looking at anything"


def test_no_generic_writer_can_be_pointed_at_a_submitted_resume() -> None:
    """The blind spot a syntax tree cannot see, closed at runtime.

    `api/routes/profile.py` writes through a **registry**: `REMOVABLE` maps a URL segment
    to a model and `setattr` does the rest. A gate that reads syntax cannot tell that such
    a helper will never be handed a submission — the model is a value, and a value can be
    added by any line of code, including one built at import time.

    So this asks the objects rather than the source: every module-level container in
    `careerhq` is walked, and `SubmittedResume` must appear in none of them. A drill that
    registers it — under any key, in any dict, list or dataclass field — fails here even
    though nothing in the syntax says `SubmittedResume` at the point of the write.
    """
    import careerhq
    from careerhq.domain.models import SubmittedResume

    def _reaches(value: object, depth: int = 0) -> bool:
        if value is SubmittedResume:
            return True
        if depth > 3:
            return False
        if isinstance(value, dict):
            return any(_reaches(v, depth + 1) for v in (*value.keys(), *value.values()))
        if isinstance(value, list | tuple | set | frozenset):
            return any(_reaches(v, depth + 1) for v in value)
        slots = getattr(value, "__dict__", None)
        if slots and not isinstance(value, type) and not inspect.ismodule(value):
            return any(_reaches(v, depth + 1) for v in slots.values())
        return False

    holders: list[str] = []
    scanned = 0
    for info in pkgutil.walk_packages(careerhq.__path__, prefix="careerhq."):
        module = importlib.import_module(info.name)
        scanned += 1
        for name, value in vars(module).items():
            if name.startswith("__") or inspect.ismodule(value) or isinstance(value, type):
                continue
            if _reaches(value):
                holders.append(f"{info.name}.{name}")

    assert scanned >= 30, f"the scan imported almost nothing: {scanned} modules"
    assert holders == [], (
        "a generic writer can be handed a submission through a registry, which makes it "
        f"updatable without any module naming it at the point of the write: {holders}"
    )


def test_only_the_renderer_imports_weasyprint() -> None:
    """T035, D7 — the rendering engine behind one boundary, as an import-graph property.

    The same rule `test_only_the_gateway_imports_the_provider_sdk` states for the
    provider SDK, and for the same reason: nothing fails at runtime when a second module
    starts importing WeasyPrint. The code works, and the boundary that lets the renderer
    be replaced — or lets a caller be sure it cannot render — is quietly gone.

    If this fails, the fix is to call `render_resume_pdf`, not to add a module here.
    """
    examined = list(SRC.rglob("*.py"))
    assert len(examined) > 40, f"the import walk examined {len(examined)} files; it found nothing"

    importers = _modules_importing("weasyprint")

    assert importers == {"infrastructure/documents/render.py"}, (
        f"weasyprint must be imported by the renderer alone; found: {sorted(importers)}"
    )


def test_the_renderer_is_not_a_back_door_to_weasyprint() -> None:
    """The half an import guard cannot see, and it was open until T035.

    `_modules_importing("weasyprint")` finds modules importing the *package*. It says
    nothing about a module that imports WeasyPrint's names and then re-exports them: with
    `from weasyprint import HTML` at the top of `render.py`, any caller could write
    `from careerhq.infrastructure.documents.render import HTML` and drive the engine
    directly, while the guard above stayed green.

    Asserted on the module's actual namespace rather than on `__all__`, because `__all__`
    governs `import *` and nothing else — a public name is reachable whatever it says.
    """
    import careerhq.infrastructure.documents.render as renderer

    leaked = []
    for name in dir(renderer):
        if name.startswith("_"):
            continue
        value = getattr(renderer, name)
        origin = getattr(value, "__module__", None) or getattr(value, "__name__", "")
        if str(origin).split(".")[0] == "weasyprint":
            leaked.append(name)

    assert not leaked, (
        f"{renderer.__name__} publicly re-exports WeasyPrint objects {sorted(leaked)}; a "
        "caller can import them from here and bypass the boundary entirely"
    )

    assert renderer.__all__ == ["render_resume_pdf"], (
        f"the renderer's declared surface is {renderer.__all__}; the boundary is one "
        "function that takes content and returns bytes"
    )
