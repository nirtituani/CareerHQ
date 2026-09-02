"""A snapshot field must be consumed where the row is built, not merely computed.

**A pure source check, in `unit/` because it needs no database.** It exists because a
field was added to the master item and the one construction site that turns that item
into a row never read it: `source_category` was calculated for every skill, discarded,
and persisted NULL — invisible until a real export came back with a flat Skills block.
"""

from __future__ import annotations

import ast
import pathlib

import careerhq.application.tailor_resume as careerhq_tailor_resume


def test_every_snapshot_field_the_master_item_carries_is_consumed() -> None:
    """A field can be computed and then silently discarded — this is that bug, generalised.

    `_render_master` builds each master item as a dict and one construction site turns it
    into a row. Nothing connected the two, so `source_category` was added to the dict,
    never read, and wrote NULL for every skill on every version.

    **A source read, deliberately, and a narrow one.** The two functions are compared by
    name only: every key the master item can carry must appear as a `master_item.get(...)`
    or `master_item[...]` at the construction site. That is a text check rather than a
    framework, and it is the smallest thing that fails when the next snapshot field is
    added and forgotten.
    """
    source = pathlib.Path(
        careerhq_tailor_resume.__file__  # type: ignore[name-defined]
    ).read_text()
    tree = ast.parse(source)

    render_master = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_render_master"
    )
    produced = {
        key.value
        for node in ast.walk(render_master)
        if isinstance(node, ast.Dict)
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert "source_category" in produced and "role_ordinal" in produced, (
        "the master item no longer carries the fields this gate exists to protect; "
        f"found {sorted(produced)}"
    )

    consumed = {
        node.slice.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "master_item"
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    } | {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "master_item"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    dropped = produced - consumed
    assert not dropped, (
        f"{sorted(dropped)} are put on a master item and never read when the row is "
        "built, so they are computed and discarded — exactly how source_category "
        "persisted NULL for every skill"
    )
