"""T032 — assertion 6: byte-determinism (FR-031), and the font the claim rests on.

**Scope: the same runtime environment.** Rendering identical approved content twice on
one runtime must produce byte-identical output. That is what FR-021 and Constitution IV
actually need — verification compares *stored bytes* against a recorded checksum and
never re-renders — and it is the failure FR-031 names: a **re-export**, which happens on
the deployed runtime, silently producing different bytes after submissions exist.

**It is deliberately not a claim about arbitrary machines.** A macOS developer host has
no DejaVu and resolves to Verdana, so its bytes differ from the image's. Nothing in the
specs asks a laptop to reproduce production bytes, and pretending otherwise would mean
vendoring a font to satisfy a requirement nobody stated.

**Separate processes, not two calls in one.** A creation timestamp captured at import
would make an in-process comparison pass while every re-export differed — the exact
defect this asserts against. The two renders are therefore two `subprocess` runs fed the
same serialized document.

**Measured before anything was written (2026-08-28): WeasyPrint 69.0 is already
deterministic.** No `/CreationDate`, no `/ModDate`, no `/ID` in the trailer; the only
metadata is `Producer`. **So no normalization code was added** — R10's premise that
"PDFs embed a creation timestamp and document ID by default" does not hold at this
version. These tests are the gate that catches a version bump reintroducing one, and
they are drilled rather than trusted.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import struct
import subprocess
import sys
import time
import zlib

import pdfplumber
import pytest

from careerhq.domain.schemas.document import (
    ResumeDocument,
    ResumeGroup,
    ResumeRole,
    ResumeSection,
)
from careerhq.infrastructure.documents.render import render_resume_pdf

_BACKEND = pathlib.Path(__file__).resolve().parents[2]

#: The font the ATS template asks for. Declared in the image so the guarantee does not
#: rest on a transitive dependency — see the Dockerfile comment and T049.
_REQUIRED_FONT_PACKAGE = "fonts-dejavu-core"

#: The system packages the rendered bytes actually depend on (T055).
#:
#: **Not "what the Dockerfile installs"** — that list also carries `curl`, which the
#: healthcheck needs and rendering does not. This is the render contract specifically, so
#: an unrelated addition to either file does not have to be mirrored in the other.
#:
#: WeasyPrint binds Pango, Cairo and HarfBuzz through cffi **at import**, and resolves the
#: family the template names through fontconfig. Which font resolves decides the rendered
#: bytes — measured at T032 as an 8,885-byte document becoming 11,499 when the family
#: changed — so an environment that asserts anything about a rendered document has to
#: declare these, or it is asserting against whatever its base image happened to ship.
_RENDER_PACKAGES = frozenset(
    {
        _REQUIRED_FONT_PACKAGE,
        "libpango-1.0-0",
        "libpangoft2-1.0-0",
        "libharfbuzz0b",
        "libcairo2",
    }
)

#: The repository root — `ci.yml` is above `backend/`, unlike everything else here.
_REPO = _BACKEND.parent


def _declared_packages(path: pathlib.Path) -> set[str]:
    """Package names that appear as their own instruction line in an install list.

    **Comments are stripped first, and the drill is why** — the same trap
    `test_the_image_declares_the_font_the_template_depends_on` documents. A search of the
    whole file passes after a package is deleted, because the comment above the list still
    names it. A test that a *word appears somewhere in a file* is not a test that a
    package is installed.

    Line-oriented rather than a YAML or Dockerfile parse: both files write one package per
    continued line, and a real parser would still have to make exactly this judgement
    about which shell words are package names.
    """
    lines = path.read_text().splitlines()
    instructions = [line for line in lines if not line.strip().startswith("#")]
    assert len(instructions) > 10, f"{path.name} parsed to almost nothing; the scan is empty"
    return {line.strip().rstrip("\\").strip() for line in instructions}


def _sample() -> ResumeDocument:
    return ResumeDocument(
        full_name="Dana Levi",
        contact=("dana@example.com", "+972 50 000 0000", "Tel Aviv"),
        sections=(
            ResumeSection.of_lines(
                "Summary",
                ("Senior Backend Engineer with six years on payment platforms.",),
            ),
            # **Carries a role group on purpose (T051).** Determinism has to hold for the
            # structure that actually ships, and role context added three new block
            # elements per job to the rendered document.
            ResumeSection(
                heading="Experience",
                groups=(
                    ResumeGroup(
                        role=ResumeRole(
                            employer="Sapiens",
                            title="C++ Developer",
                            dates="10/2017 – 01/2026",  # noqa: RUF001
                        ),
                        lines=(
                            "Owned the settlement service end to end, from schema to on-call.",
                            "Cut reconciliation time from six hours to twenty minutes.",
                        ),
                    ),
                ),
            ),
        ),
    )


def test_the_image_declares_the_font_the_template_depends_on() -> None:
    """A1. The rendered bytes depend on which font resolves, so the font is a dependency.

    **It was reaching the image transitively** — `python:3.12-slim` plus WeasyPrint's
    native libraries happens to pull DejaVu today. A base image that stopped doing so
    would change every rendered document, and FR-031's own failure mode is that this
    surfaces only on a re-export. Declared explicitly, it is a guarantee rather than a
    coincidence; asserted here so removing it is a test failure rather than a discovery.
    """
    lines = (_BACKEND / "Dockerfile").read_text().splitlines()

    # **Comments are stripped first, and the drill is why.** The first version of this
    # test searched the whole file, and passed after the package was deleted from the
    # `apt-get install` list — because the comment above that list still named it. A test
    # that a *word appears somewhere in a file* is not a test that a package is installed.
    instructions = [line for line in lines if not line.strip().startswith("#")]
    declared = [
        line for line in instructions if line.strip().rstrip("\\").strip() == _REQUIRED_FONT_PACKAGE
    ]

    assert len(instructions) > 10, "the Dockerfile parsed to almost nothing; the scan is empty"
    assert declared, (
        f"{_REQUIRED_FONT_PACKAGE} is not an installed package in the backend image — it "
        "appears in no instruction line. The ATS template renders in DejaVu Sans, and "
        "relying on the base image to supply it makes the output of every export depend "
        "on an undeclared transitive dependency."
    )


def _render_in_subprocess(script: pathlib.Path, payload: str, out: pathlib.Path) -> bytes:
    # S603 suppressed by code: the argument vector is this test's own interpreter, a
    # script this test wrote, and a payload this test serialized. Nothing is untrusted,
    # and a separate process is exactly what makes the determinism claim meaningful.
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(script), payload, str(out)],
        cwd=_BACKEND,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, f"the render subprocess failed: {result.stderr.decode()}"
    return out.read_bytes()


@pytest.fixture
def render_script(tmp_path: pathlib.Path) -> pathlib.Path:
    """A standalone renderer, so each render is a genuinely fresh interpreter."""
    script = tmp_path / "render_once.py"
    script.write_text(
        "import json, sys\n"
        "sys.path.insert(0, 'src')\n"
        "from careerhq.domain.schemas.document import (\n"
        "    ResumeDocument, ResumeGroup, ResumeRole, ResumeSection,\n"
        ")\n"
        "from careerhq.infrastructure.documents.render import render_resume_pdf\n"
        "raw = json.loads(sys.argv[1])\n"
        "document = ResumeDocument(\n"
        "    full_name=raw['full_name'],\n"
        "    contact=tuple(raw['contact']),\n"
        "    sections=tuple(\n"
        "        ResumeSection(heading=s['heading'], groups=tuple(\n"
        "            ResumeGroup(\n"
        "                role=(ResumeRole(**g['role']) if g['role'] else None),\n"
        "                lines=tuple(g['lines']),\n"
        "            )\n"
        "            for g in s['groups']\n"
        "        ))\n"
        "        for s in raw['sections']\n"
        "    ),\n"
        ")\n"
        "open(sys.argv[2], 'wb').write(render_resume_pdf(document))\n"
    )
    return script


def test_rendering_the_same_document_twice_is_byte_identical(
    render_script: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """FR-031, in the same runtime, across two interpreters.

    The document is serialized once and handed to both runs, so "identical content" is a
    property of the input rather than of two constructions that might differ.
    """
    document = _sample()
    payload = json.dumps(
        {
            "full_name": document.full_name,
            "contact": list(document.contact),
            "sections": [
                {
                    "heading": s.heading,
                    "groups": [
                        {
                            "role": (
                                {
                                    "employer": g.role.employer,
                                    "title": g.role.title,
                                    "dates": g.role.dates,
                                }
                                if g.role
                                else None
                            ),
                            "lines": list(g.lines),
                        }
                        for g in s.groups
                    ],
                }
                for s in document.sections
            ],
        }
    )

    first = _render_in_subprocess(render_script, payload, tmp_path / "first.pdf")
    # **Separated by more than a second, and that is the whole of what this test learned
    # the hard way.** The failure it exists to catch is a wall-clock timestamp inside the
    # embedded font subset, whose resolution is one second — so two renders that happen to
    # land in the same second are identical *whether or not the bug is present*. Without
    # this sleep the assertion passed on the dev host for months while every render in the
    # container and in CI was nondeterministic: measured at five distinct hashes from eight
    # consecutive renders. The second is bought back many times over by not shipping that.
    time.sleep(1.1)
    second = _render_in_subprocess(render_script, payload, tmp_path / "second.pdf")

    assert first, "the renderer produced no bytes"
    assert first == second, (
        f"two renders of identical content differ: {len(first)} vs {len(second)} bytes; "
        f"first difference at offset "
        f"{next((i for i, (a, b) in enumerate(zip(first, second, strict=False)) if a != b), 'n/a')}"
    )


def test_the_document_carries_no_time_varying_metadata() -> None:
    """The mechanism behind the claim, asserted separately from the claim itself.

    Byte-identity could hold today and break on a version bump that starts stamping a
    creation date. Naming the specific keys means the failure says *what* changed rather
    than only that two blobs differ.
    """
    rendered = render_resume_pdf(_sample())

    # **Drilled unevenly, and that is recorded rather than smoothed over.** `/ID` is
    # proven load-bearing: rendering with `pdf_identifier=os.urandom(16)` is named by this
    # test, and `pdf_variant="pdf/a-3b"` is named too. **`/CreationDate` and `/ModDate`
    # could NOT be induced** through WeasyPrint 69's public options — neither a
    # `dcterms.created` meta tag, nor that tag with `custom_metadata=True`, nor the PDF/A
    # variant put one in the file. They are kept as guards against a version that starts
    # emitting one, not as clauses a drill has exercised.
    for marker in (b"/CreationDate", b"/ModDate", b"/ID"):
        assert marker not in rendered, (
            f"{marker.decode()} appears in the rendered PDF; it varies per render and "
            "makes FR-021's stable checksum unenforceable"
        )

    with pdfplumber.open(io.BytesIO(rendered)) as pdf:
        metadata = dict(pdf.metadata)

    time_varying = {k for k in metadata if k in {"CreationDate", "ModDate", "ID"}}
    assert not time_varying, f"time-varying metadata present: {sorted(time_varying)}"
    assert metadata, "no metadata at all — the assertion above would pass on any document"


def _embedded_font_head_modified(pdf: bytes) -> int | None:
    """The `head.modified` timestamp of the first embedded font program, or `None`.

    Reads the PDF by hand rather than through a library because the field is three levels
    down — a Flate-compressed object carrying an sfnt font, whose table directory locates
    a `head` table, 28 bytes into which sits a `LONGDATETIME`. No extractor exposes it,
    and it is the exact value that broke FR-031.
    """
    for match in re.finditer(rb"(<<[^>]*?/Length1 \d+[^>]*?>>)\s*stream\r?\n", pdf, re.S):
        length = int(re.search(rb"/Length (\d+)", match.group(1)).group(1))  # type: ignore[union-attr]
        font = zlib.decompress(pdf[match.end() : match.end() + length])
        tables = struct.unpack(">H", font[4:6])[0]
        for index in range(tables):
            entry = 12 + index * 16
            if font[entry : entry + 4] == b"head":
                offset = struct.unpack(">I", font[entry + 8 : entry + 12])[0]
                return int(struct.unpack(">q", font[offset + 28 : offset + 36])[0])
    return None


def test_the_embedded_font_carries_no_render_time_timestamp() -> None:
    """The root cause, named — so a regression says *what* broke, not just that bytes differ.

    `fontTools` stamps the font subset it embeds with `head.modified = now` unless
    `SOURCE_DATE_EPOCH` is set. That one value moves two derived checksums with it, changes
    the compressed length of the font object, and shifts every offset after it. The
    byte-identity test above would catch a regression; this says which field caused it.

    **Asserted as stability, not as a specific value.** The pinned epoch is what a Linux
    render produces, but macOS resolves a different font and preserves its original 2007
    date instead of restamping — so demanding a particular number would fail on the dev
    host for a reason that has nothing to do with the bug. What must hold everywhere is
    that the value does not move between renders.
    """
    first = render_resume_pdf(_sample())
    time.sleep(1.1)
    second = render_resume_pdf(_sample())

    before = _embedded_font_head_modified(first)
    after = _embedded_font_head_modified(second)

    assert before is not None, "no embedded font program found; this test examined nothing"
    assert before == after, (
        "the embedded font's head.modified changed between two renders "
        f"({before} then {after}) — SOURCE_DATE_EPOCH is not reaching fontTools, and every "
        "re-export will record a different checksum"
    )


def test_the_renderer_pins_the_font_timestamp_on_import() -> None:
    """The mechanism is a module-level side effect, so it is asserted as one.

    Importing the renderer is what sets `SOURCE_DATE_EPOCH`. Setting it in the Dockerfile,
    CI and `conftest.py` instead would be three places to forget, and forgetting is silent
    until somebody re-exports — so the boundary that owns the guarantee (D7) sets it.
    `setdefault` leaves an operator's own value alone, which is why this asserts the
    variable is populated rather than that it equals the pin.
    """
    import careerhq.infrastructure.documents.render as renderer

    assert os.environ.get("SOURCE_DATE_EPOCH"), (
        "SOURCE_DATE_EPOCH is unset after importing the renderer; fontTools will stamp "
        "the embedded font with the current time"
    )
    assert renderer.PINNED_SOURCE_DATE_EPOCH == "0"


def test_ci_installs_the_same_render_dependencies_as_the_production_image() -> None:
    """T055. The environment that asserts about rendered documents must render like production.

    **The gap this closes.** `ci.yml` installed no system packages at all, so WeasyPrint
    bound whatever Pango, Cairo and fontconfig `ubuntu-latest` happened to ship and
    resolved whatever fonts happened to be present. The six ATS assertions and the
    byte-determinism assertion were therefore green against a document production does not
    produce — and a runner base-image change could have altered CI's output without
    touching anything this repository declares, which is the exact failure mode declaring
    the font in the Dockerfile was meant to prevent.

    **Asserted as an equality between two files, not as a list in one.** Installing the
    packages in CI is only half a fix: two lists that must stay in step will not, and the
    drift is silent because both environments keep working. This makes the drift a test
    failure in whichever direction it happens.

    **This is not FR-031.** Determinism is a claim about two renders on *one* runtime and
    is already satisfied everywhere by the timestamp pin. This is about *which* runtime CI
    is making its other assertions on.
    """
    in_image = _declared_packages(_BACKEND / "Dockerfile")
    in_ci = _declared_packages(_REPO / ".github" / "workflows" / "ci.yml")

    missing_from_image = _RENDER_PACKAGES - in_image
    assert not missing_from_image, (
        f"the production image no longer declares {sorted(missing_from_image)} — every "
        "exported document's bytes depend on these, and dropping one makes the output "
        "depend on an undeclared transitive dependency"
    )

    missing_from_ci = _RENDER_PACKAGES - in_ci
    assert not missing_from_ci, (
        f"CI does not install {sorted(missing_from_ci)}, which `backend/Dockerfile` "
        "declares for production. The export tests would then assert against a document "
        "rendered with different libraries and possibly a different font than the one an "
        "employer receives."
    )
