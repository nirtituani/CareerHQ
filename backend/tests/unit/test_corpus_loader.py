"""T025 — the corpus loader and chunker.

**The gate this file exists for is F10**, from the aggregate corpus review: a corpus
document is two kinds of text, and only one of them is guidance. The `## Rules` list
items are rules. Everything else — the title, the preamble, the dated change notes, the
`## Removed, and why it must not come back` sections — is *commentary about the corpus*,
full of register ids and rationale. If any of it becomes a chunk, FR-036 breaks: the
Draft node is handed sentences like "this file exists because two rules were inheriting
institutional standing" as though they were resume-writing guidance, and a citation
points at our own commentary instead of a source.

Nothing enforced that before this file. The corpus lints parse rule items only, so they
are structurally incapable of seeing prose leak into a chunk.

**The fixture puts a list item in the preamble AND in the `## Removed` section, and that
is the whole point.** The first version of this file did not, and the F10 drill exposed
it: widening the chunker to read "everything after `## Rules`" changed nothing, because
prose paragraphs contain no `- ` bullets and were excluded by the list-item pattern alone.
The test passed the drill it was written to fail, which means it was asserting a property
the implementation did not actually have to provide. Both boundaries are only load-bearing
against list items, so the fixture has to contain them.
"""

from __future__ import annotations

import hashlib
import pathlib

import pytest

from careerhq.infrastructure.corpus import load_corpus, load_document

_FIXTURE = """---
slug: fixture-doc
source_type: integrity
market: global
trust_level: internal
role_family: any
seniority: any
resume_section: any
topic: [integrity]
origin_source_ids: [S-018, S-002]
---

# A fixture document title

This preamble mentions **S-018** by name and explains that the file exists for a reason
nobody should ever retrieve as guidance. It is prose about the corpus, not guidance.

**Amended 2026-08-28.** A dated change note, which is also not guidance. Preambles in the
real corpus carry list items too, so this one does:

- Preamble bullet: this looks exactly like a rule to any parser that finds list items
  without first bounding itself to the rules section, and it is not one.

## Rules

- The first rule says something actionable about writing a resume, at sufficient length
  that it is not mistaken for a fragment by the corpus lint.

- The second rule says something else actionable, also at a length that clears the
  minimum, and carries its own condition where that condition applies.

## Removed, and why it must not come back

A third rule was removed on 2026-08-28 because S-002 does not support it. This section
is a change note and must never be retrievable as guidance.

- Removed rule text, quoted here so a future author can see what was deleted: this reads
  as a perfectly good rule and is exactly what must never be retrieved.
"""


@pytest.fixture
def fixture_doc(tmp_path: pathlib.Path) -> pathlib.Path:
    path = tmp_path / "fixture-doc.md"
    path.write_text(_FIXTURE)
    return path


# --------------------------------------------------------------------------
# F10 — the hard invariant
# --------------------------------------------------------------------------


def test_document_prose_never_becomes_a_chunk(fixture_doc: pathlib.Path) -> None:
    """F10. The chunker emits rules; it must not emit anything else.

    **Drill this** by widening the chunker to include document prose — split on
    paragraphs rather than on `## Rules` list items — and confirm this names the
    leaked text rather than merely failing.
    """
    doc = load_document(fixture_doc)

    # The count assertion is not decoration. A chunker that emits nothing passes
    # every "prose is absent" assertion below trivially, and this project has
    # shipped a gate examining zero things four times.
    assert len(doc.chunks) == 2, (
        f"expected 2 rules, got {len(doc.chunks)}: {[c.text[:40] for c in doc.chunks]}"
    )

    forbidden = {
        "S-018": "a register id from the preamble",
        "S-002": "a register id from the removal note",
        "Amended 2026-08-28": "a dated change note",
        "A fixture document title": "the document heading",
        "must never be retrievable": "the removal note's body",
        "prose about the corpus": "the preamble's body",
        "Preamble bullet": "a LIST ITEM in the preamble, before `## Rules`",
        "Removed rule text": "a LIST ITEM in the `## Removed` section, after the rules",
    }
    for chunk in doc.chunks:
        for needle, what in forbidden.items():
            assert needle not in chunk.text, f"{what} leaked into a chunk: {chunk.text[:120]!r}"


def test_a_removed_section_contributes_no_chunk(fixture_doc: pathlib.Path) -> None:
    """The `## Removed` section is a list-free prose block, but it follows `## Rules`.

    A chunker that finds the rules block by "everything after `## Rules`" swallows it.
    Two real corpus files carry such a section, so this is the live case rather than a
    hypothetical one.
    """
    doc = load_document(fixture_doc)

    assert not any("removed on 2026-08-28" in c.text.lower() for c in doc.chunks)
    assert not any("Removed rule text" in c.text for c in doc.chunks)
    assert len(doc.chunks) == 2


# --------------------------------------------------------------------------
# FR-037 — one rule, one chunk
# --------------------------------------------------------------------------


def test_each_rule_becomes_exactly_one_chunk_in_order(fixture_doc: pathlib.Path) -> None:
    doc = load_document(fixture_doc)

    assert [c.chunk_order for c in doc.chunks] == [0, 1]
    assert doc.chunks[0].text.startswith("The first rule")
    assert doc.chunks[1].text.startswith("The second rule")


def test_a_rules_paragraph_wrap_is_normalised_away(fixture_doc: pathlib.Path) -> None:
    """A rule spans several source lines; a chunk is one string.

    Without this the hash changes whenever someone re-wraps a paragraph, and
    re-ingestion stops being idempotent for a change that altered no words.
    """
    doc = load_document(fixture_doc)

    for chunk in doc.chunks:
        assert "\n" not in chunk.text
        assert "  " not in chunk.text


# --------------------------------------------------------------------------
# FR-012 — content_hash is the citation identity
# --------------------------------------------------------------------------


def test_content_hash_is_sha256_of_the_normalised_text(fixture_doc: pathlib.Path) -> None:
    doc = load_document(fixture_doc)

    for chunk in doc.chunks:
        expected = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert chunk.content_hash == expected
        assert len(chunk.content_hash) == 64


def test_rewrapping_a_rule_keeps_its_hash_and_editing_it_changes_it(
    tmp_path: pathlib.Path,
) -> None:
    """Re-ingestion is idempotent for unchanged text and honest about changed text.

    The whole of FR-012 rests on this: recompute the hash over the recorded text and a
    match proves the guidance existed unaltered, while a miss proves drift, loudly.
    """
    rewrapped = _FIXTURE.replace(
        "- The first rule says something actionable about writing a resume, at sufficient length\n"
        "  that it is not mistaken for a fragment by the corpus lint.",
        "- The first rule says something actionable about writing a resume,\n"
        "  at sufficient length that it is not mistaken for a fragment\n"
        "  by the corpus lint.",
    )
    edited = _FIXTURE.replace("something actionable about writing", "something different about")

    base = tmp_path / "a.md"
    base.write_text(_FIXTURE)
    wrap = tmp_path / "b.md"
    wrap.write_text(rewrapped)
    edit = tmp_path / "c.md"
    edit.write_text(edited)

    original = load_document(base).chunks[0].content_hash
    assert load_document(wrap).chunks[0].content_hash == original, (
        "re-wrapping a rule changed its hash; re-ingestion would create a duplicate chunk"
    )
    assert load_document(edit).chunks[0].content_hash != original, (
        "editing a rule kept its hash; a corpus edit would be invisible to a citation check"
    )


# --------------------------------------------------------------------------
# FR-005 — metadata from front-matter
# --------------------------------------------------------------------------


def test_document_metadata_comes_from_the_front_matter(fixture_doc: pathlib.Path) -> None:
    doc = load_document(fixture_doc)

    assert doc.slug == "fixture-doc"
    assert doc.source_type == "integrity"
    assert doc.market == "global"
    assert doc.trust_level == "internal"
    assert doc.origin_source_ids == ["S-018", "S-002"]
    assert doc.title == "A fixture document title"
    assert doc.version == 1


def test_every_chunk_carries_the_documents_metadata(fixture_doc: pathlib.Path) -> None:
    """`ChunkMetadata` travels with the chunk because retrieval returns chunks, not files.

    A chunk that arrives without its market or trust level cannot be weighed by the
    market-precedence rule (FR-038) or shown with its standing.
    """
    doc = load_document(fixture_doc)

    for chunk in doc.chunks:
        assert chunk.metadata["market"] == "global"
        assert chunk.metadata["role_family"] == "any"
        assert chunk.metadata["seniority"] == "any"
        assert chunk.metadata["resume_section"] == "any"
        assert chunk.metadata["source_title"] == "A fixture document title"
        assert chunk.metadata["topic"] == ["integrity"]


def test_token_count_is_positive_and_proportionate(fixture_doc: pathlib.Path) -> None:
    """`token_count` exists so the FR-014 ceiling needs no re-tokenising at query time."""
    doc = load_document(fixture_doc)

    for chunk in doc.chunks:
        assert chunk.token_count > 0
        # A sanity band, not a tokenizer reimplementation: English prose runs
        # roughly 3-6 characters per token, so anything outside that means the
        # count is measuring something other than this text.
        assert len(chunk.text) / 6 <= chunk.token_count <= len(chunk.text) / 2


# --------------------------------------------------------------------------
# The real corpus
# --------------------------------------------------------------------------


def test_the_real_corpus_loads_and_matches_the_authored_rule_count() -> None:
    """The loader and the corpus lints must agree about what a rule is.

    They parse the same files by different code paths, so a disagreement means one of
    them is wrong about the corpus — which is exactly the discrepancy T025 is meant to
    surface before anything is ingested.
    """
    docs = load_corpus()

    assert len(docs) == 18, f"expected 18 corpus documents, found {len(docs)}"
    total = sum(len(d.chunks) for d in docs)
    assert total == 79, f"expected 79 authored rules, chunker produced {total}"

    slugs = [d.slug for d in docs]
    assert len(slugs) == len(set(slugs)), f"duplicate slugs: {slugs}"

    for doc in docs:
        hashes = [c.content_hash for c in doc.chunks]
        assert len(hashes) == len(set(hashes)), (
            f"{doc.slug}: duplicate content hashes would violate "
            "uq_knowledge_chunks_document_content on ingestion"
        )


def test_an_unknown_topic_is_refused(tmp_path: pathlib.Path) -> None:
    """`topic` has one consumer — FR-038 precedence — and a typo silences it.

    A value outside the vocabulary makes a document share a topic with nothing, so
    precedence quietly stops firing for it and no other test would notice. Refused at
    load rather than passed through.
    """
    from careerhq.infrastructure.corpus import CorpusFormatError

    path = tmp_path / "bad.md"
    path.write_text(_FIXTURE.replace("topic: [integrity]", "topic: [sectionorder]"))

    with pytest.raises(CorpusFormatError) as caught:
        load_document(path)
    assert "sectionorder" in str(caught.value)


def test_every_real_document_declares_topics_from_the_vocabulary() -> None:
    """All 18 shipped documents, checked against the enum rather than a copy of it."""
    from careerhq.domain.models.knowledge import Topic

    known = {t.value for t in Topic}
    docs = load_corpus()

    assert len(docs) == 18
    for doc in docs:
        topics = doc.chunks[0].metadata["topic"]
        assert topics, f"{doc.slug} declares no topic"
        assert set(topics) <= known, f"{doc.slug} declares unknown topics: {topics}"
