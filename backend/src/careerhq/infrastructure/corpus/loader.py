"""Turning authored corpus files into chunks, and nothing else into chunks.

**A corpus document is two kinds of text and only one of them is guidance.** The
`## Rules` list items are rules. The title, the preamble, the dated change notes and the
`## Removed, and why it must not come back` sections are *commentary about the corpus* —
they carry register ids, rationale and the history of what was deleted.

Emitting any of that as a chunk breaks FR-036 immediately: retrieval would hand the Draft
node sentences like *"this file exists because two rules were inheriting institutional
standing"* as though they were resume-writing advice, and a citation would point at our
own commentary rather than at a source. Nothing else in the system can catch it — the
corpus lints parse rule items by construction, so they are structurally blind to prose
that leaks through this module.

That is why the rules block is bounded on **both** sides. Finding the rules by "everything
after `## Rules`" is the obvious implementation and it is wrong: two real corpus files end
with a `## Removed` section, and that spelling swallows both of them.

**`content_hash` is the citation identity** (FR-012), so normalisation happens before
hashing and never after: a rule re-wrapped across different lines must keep its hash, or
re-ingestion duplicates a chunk whose words nobody changed. Editing the words must change
it, which is what makes a recorded citation checkable rather than merely present.
"""

from __future__ import annotations

import functools
import hashlib
import pathlib
import re
from dataclasses import dataclass
from typing import Any

import tiktoken
import yaml

from careerhq.domain.models.knowledge import Topic

#: The authored corpus. `parents[4]` is `backend/`, which holds both `src/` and `corpus/`.
CORPUS_ROOT = pathlib.Path(__file__).resolve().parents[4] / "corpus"

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_TITLE = re.compile(r"^#\s+(.+?)\s*$", re.M)
#: A list item under `## Rules`, ending at a blank line or the next heading. The
#: closing `\n##` is what stops a `## Removed` section being read as a rule.
_RULE = re.compile(r"^-\s+(.+?)(?=\n\s*\n|\n##|\Z)", re.S | re.M)

_REQUIRED_KEYS = (
    "slug",
    "topic",
    "source_type",
    "market",
    "trust_level",
    "role_family",
    "seniority",
    "resume_section",
    "origin_source_ids",
)


class CorpusFormatError(ValueError):
    """A corpus file does not match the contract in `corpus/README.md`.

    Raised rather than skipped. A document that silently fails to load is a set of
    guidance the agent quietly stops receiving, and the symptom — slightly worse
    resumes — names nothing.
    """


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    """One authored rule, ready to become a `KnowledgeChunk`."""

    content_hash: str
    text: str
    chunk_order: int
    token_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """One corpus file, ready to become a `KnowledgeDocument`."""

    slug: str
    source_type: str
    title: str
    version: int
    market: str
    trust_level: str
    origin_source_ids: list[str]
    chunks: list[ParsedChunk]
    path: pathlib.Path


@functools.lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    """The tokenizer, loaded once.

    `cl100k_base` **approximates** Anthropic's tokenizer rather than matching it. That is
    acceptable here and the reason is worth stating: `token_count` feeds the FR-014
    ceiling, which is a cost and latency budget rather than an API limit, so being a few
    percent out spends a fraction of a cent. It is not acceptable to pretend otherwise —
    anything that reports these counts should say which tokenizer produced them.
    """
    return tiktoken.get_encoding("cl100k_base")


def _normalise(text: str) -> str:
    """Collapse whitespace so that re-wrapping a rule does not change its identity.

    Applied **before** hashing, never after. A rule is authored across several source
    lines and retrieved as one string; if the hash were taken over the source form, an
    editor re-flowing a paragraph would mint a new chunk for unchanged guidance and
    `uq_knowledge_chunks_document_content` would not stop it, because the bytes really
    would differ.
    """
    return " ".join(text.split())


def _rules_block(body: str) -> str:
    """The text between `## Rules` and the next heading — or the empty string.

    Both boundaries matter. Without the closing one a `## Removed, and why it must not
    come back` section is read as part of the rules, and its prose becomes retrievable
    guidance describing rules that were deleted for being wrong.
    """
    _, marker, after = body.partition("## Rules")
    if not marker:
        return ""
    return re.split(r"\n##\s", after)[0]


def load_document(path: pathlib.Path) -> ParsedDocument:
    """Parse one corpus file. Raises `CorpusFormatError` if it breaks the contract."""
    text = path.read_text(encoding="utf-8")

    match = _FRONT_MATTER.match(text)
    if match is None:
        raise CorpusFormatError(f"{path.name}: no YAML front-matter")

    try:
        meta = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:  # pragma: no cover - defensive
        raise CorpusFormatError(f"{path.name}: front-matter is not valid YAML") from exc
    if not isinstance(meta, dict):
        raise CorpusFormatError(f"{path.name}: front-matter is not a mapping")

    missing = [k for k in _REQUIRED_KEYS if k not in meta]
    if missing:
        raise CorpusFormatError(f"{path.name}: front-matter is missing {missing}")

    body = text[match.end() :]
    title_match = _TITLE.search(body)
    if title_match is None:
        raise CorpusFormatError(f"{path.name}: no `# ` title heading")
    title = title_match.group(1)

    topics = list(meta["topic"])
    unknown = [t for t in topics if t not in {v.value for v in Topic}]
    if unknown:
        # Refused rather than passed through. `topic` has exactly one consumer —
        # FR-038 precedence — and a value outside the vocabulary silently makes a
        # document share a topic with nothing, so precedence stops firing for it
        # and no test anywhere would notice.
        raise CorpusFormatError(f"{path.name}: unknown topic(s) {unknown}")
    if not topics:
        raise CorpusFormatError(f"{path.name}: topic list is empty")

    # `source_url` is absent by decision: a rule is ours, so it has no source URL —
    # the URL belongs to the evidence it derives from, and `origin_source_ids`
    # points at it. `topic` was deferred at T025 and authored at T027, once R13
    # had measured that it could not be derived from embeddings.
    shared: dict[str, Any] = {
        "topic": topics,
        "market": meta["market"],
        "trust_level": meta["trust_level"],
        "role_family": meta["role_family"],
        "seniority": meta["seniority"],
        "resume_section": meta["resume_section"],
        "source_title": title,
        "source_type": meta["source_type"],
        "origin_source_ids": list(meta["origin_source_ids"]),
    }

    encoding = _encoding()
    chunks: list[ParsedChunk] = []
    for order, raw in enumerate(_RULE.findall(_rules_block(body))):
        rule = _normalise(raw)
        chunks.append(
            ParsedChunk(
                content_hash=hashlib.sha256(rule.encode("utf-8")).hexdigest(),
                text=rule,
                chunk_order=order,
                token_count=len(encoding.encode(rule)),
                metadata=dict(shared),
            )
        )

    return ParsedDocument(
        slug=str(meta["slug"]),
        source_type=str(meta["source_type"]),
        title=title,
        # The front-matter contract has no `version` key; a document starts at 1 and
        # the column exists so a later edit can bump it (FR-012). Defaulting is
        # honest, inventing a number from a file mtime would not be.
        version=int(meta.get("version", 1)),
        market=str(meta["market"]),
        trust_level=str(meta["trust_level"]),
        origin_source_ids=list(meta["origin_source_ids"]),
        chunks=chunks,
        path=path,
    )


def load_corpus(root: pathlib.Path | None = None) -> list[ParsedDocument]:
    """Every corpus document, in a stable order.

    Sorted by path so ingestion is deterministic: two runs over an unchanged corpus must
    produce the same documents in the same order, or `chunk_order` becomes a value that
    depends on filesystem enumeration.

    `README.md` is the authoring contract, not guidance, and is excluded by name.
    """
    base = root or CORPUS_ROOT
    return [load_document(p) for p in sorted(base.rglob("*.md")) if p.name != "README.md"]
