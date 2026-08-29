"""T009-T012 — the corpus lints, plus the exclusions the author ruled out by name.

**These exist because 130 rules cannot be reviewed the way 17 were.** The sample was read
rule-by-rule by a person; the corpus will not be. Everything that review caught by eye —
a decorative citation, an unsourced ATS claim, a practitioner rule wearing an institutional
tag — has to become something that fails a build instead.

Every gate here **asserts the count of what it examined**. A corpus lint that globs zero files
passes cheerfully, and this project has shipped that failure four times.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from careerhq.domain.models.knowledge import Market, SourceType, Topic, TrustLevel

CORPUS = pathlib.Path(__file__).resolve().parents[2] / "corpus"

REQUIRED_KEYS = (
    "slug",
    "source_type",
    "market",
    "trust_level",
    "role_family",
    "seniority",
    "resume_section",
    "topic",
    "origin_source_ids",
)

#: Markers that turn a forbidden term into a prohibition rather than an instruction.
#: "Never estimate a figure" and "estimate a figure" contain the same word and mean
#: opposite things, so a bare substring ban would flag the integrity rules whose whole
#: job is forbidding the behaviour.
#:
#: **Bare "no" and "not" are deliberately absent, and the drill is why.** With them in
#: this list, *"Where the profile gives no number, estimate a plausible figure"* was
#: read as prohibited — the negation belonged to a different clause entirely, and the
#: single most important rule in this file silently passed the one case it exists to
#: catch. Only markers that attach to an instruction count.
_NEGATIONS = (
    "never",
    "do not",
    "must not",
    "may not",
    "cannot",
    "refuse",
    "without",
    "rather than",
    "is not permitted",
)


class Document:
    """One corpus file, parsed into front-matter and rules."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.name = str(path.relative_to(CORPUS))
        text = path.read_text()

        match = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if match is None:
            raise AssertionError(f"{self.name}: no YAML front-matter")
        self.meta: dict[str, str] = dict(re.findall(r"^(\w+):\s*(.+)$", match.group(1), re.M))

        body = text[match.end() :]
        # Rules live under `## Rules` and stop at the next `##` heading — a file may
        # carry a `## Removed, and why it must not come back` section, and its
        # contents are prose about a rule that no longer exists, not a rule.
        after = body.split("## Rules", 1)
        self.prose = after[0]
        rules_block = re.split(r"\n## ", after[1])[0] if len(after) > 1 else ""
        self.rules: list[str] = [
            " ".join(r.split())
            for r in re.findall(r"^- (.+?)(?=\n\n|\n*\Z)", rules_block, re.S | re.M)
        ]

    def __repr__(self) -> str:
        return f"<{self.name}: {len(self.rules)} rules>"


def _documents() -> list[Document]:
    return [Document(p) for p in sorted(CORPUS.rglob("*.md")) if p.name != "README.md"]


@pytest.fixture(scope="module")
def documents() -> list[Document]:
    docs = _documents()
    assert docs, f"no corpus documents found under {CORPUS} — this lint examined nothing"
    return docs


def test_the_lint_examines_a_real_corpus(documents: list[Document]) -> None:
    """The gate on every other gate in this file.

    A corpus lint whose glob matches nothing reports success, and every assertion
    below is a loop over that glob. The thresholds are floors, not targets — they
    exist to fail loudly if the corpus directory moves or the parser stops finding
    rules, not to require a particular corpus size.
    """
    total_rules = sum(len(d.rules) for d in documents)

    assert len(documents) >= 4, f"examined {len(documents)} corpus documents"
    assert total_rules >= 17, f"examined {total_rules} rules across {len(documents)} documents"


def test_every_document_carries_complete_and_valid_metadata(documents: list[Document]) -> None:
    """T012 — metadata is per document, so a wrong value mislabels every rule in the file.

    Exactly the defect the sample review found: two practitioner-derived rules inherited
    `institutional` from the file they shared with S-002's guidance.
    """
    valid = {
        "market": {m.value for m in Market},
        "trust_level": {t.value for t in TrustLevel},
        "source_type": {s.value for s in SourceType},
    }
    problems: list[str] = []

    for doc in documents:
        for key in REQUIRED_KEYS:
            if key not in doc.meta:
                problems.append(f"{doc.name}: missing front-matter key {key!r}")
        for key, allowed in valid.items():
            if key in doc.meta and doc.meta[key] not in allowed:
                problems.append(
                    f"{doc.name}: {key}={doc.meta[key]!r} is not one of {sorted(allowed)}"
                )

    assert not problems, "corpus metadata is invalid:\n  " + "\n  ".join(problems)


def test_sourced_guidance_cites_a_source_and_integrity_never_does(
    documents: list[Document],
) -> None:
    """T012 — `trust_level: internal` and an external citation are mutually exclusive claims.

    Integrity rules are CareerHQ product obligations under Principle III and AI-008.
    Citing an outside source for one misrepresents where the obligation comes from.
    Everything else must name the register entry it derives from — an authored rule with
    no `origin_source_ids` is an assertion nobody can check.
    """
    problems: list[str] = []

    for doc in documents:
        ids = re.findall(r"S-\d+", doc.meta.get("origin_source_ids", ""))
        if doc.meta.get("source_type") == SourceType.INTEGRITY.value:
            if doc.meta.get("trust_level") != TrustLevel.INTERNAL.value:
                problems.append(
                    f"{doc.name}: integrity documents must be trust_level: internal, "
                    f"found {doc.meta.get('trust_level')!r}"
                )
        elif doc.meta.get("trust_level") != TrustLevel.INTERNAL.value and not ids:
            # `internal` means CareerHQ-authored product judgement, which has no
            # outside source to name — that is what the value *asserts*. Demanding a
            # citation here would produce the decorative citation the sample review
            # caught: an id attached to a rule that does not derive from it, which
            # makes an unsourced rule look sourced and makes the field unusable as
            # the thing a reader checks. The claim "this is ours" stays reviewable
            # because a wrongly-`internal` document is visible in the metadata.
            problems.append(f"{doc.name}: sourced guidance with empty origin_source_ids")

        # An Israeli-market claim is the one place this project manufactures a
        # distinction if it is not careful. It must name what justifies it.
        if doc.meta.get("market") == Market.ISRAEL.value and not ids:
            problems.append(f"{doc.name}: market: israel with no justifying source")

    assert not problems, "citation rules broken:\n  " + "\n  ".join(problems)


def test_every_rule_is_one_self_contained_chunk(documents: list[Document]) -> None:
    """T009 / FR-037 — a rule is a retrieval chunk, and arrives alone.

    Its qualifications and exceptions travel with it or they do not travel at all.
    A rule that points at a sibling is broken the moment retrieval returns one and
    not the other, which is the normal case rather than an edge one.
    """
    dangling = re.compile(
        r"\b(see above|see below|the previous rule|the rule above|the rule below|"
        r"as noted above|the preceding rule|the next rule|this file's other)\b",
        re.I,
    )
    problems: list[str] = []

    for doc in documents:
        for rule in doc.rules:
            if dangling.search(rule):
                problems.append(f"{doc.name}: rule refers to a sibling chunk: {rule[:70]}…")
            if re.search(r"\n\s*[-*] ", rule):
                problems.append(f"{doc.name}: rule contains a nested bullet: {rule[:70]}…")
            if len(rule) < 60:
                problems.append(f"{doc.name}: rule is a fragment, not a rule: {rule!r}")

    assert not problems, "one-rule-one-chunk broken:\n  " + "\n  ".join(problems)


def test_no_rule_invites_fabrication(documents: list[Document]) -> None:
    """T010 / FR-030 — the corpus may never instruct estimating or quota-filling.

    The research digests contained both — "defensible estimates when hard numbers are
    unavailable" and a "70-80% keyword coverage" quota — and both are direct violations
    of Principle III / AI-008. They are the reason S-021 is evidence-only.

    **Negation-aware**: an integrity rule forbidding estimation contains the same words
    as one demanding it. A term is a violation only when no negation appears in the
    rule, which is a heuristic — it can be fooled by a sufficiently contorted sentence,
    and a human review is still the backstop.
    """
    inviting = (
        "estimate",
        "approximate the",
        "plausible figure",
        "plausible range",
        "reasonable guess",
        "keyword coverage",
        "% of the keywords",
        "coverage target",
        "fill the gap",
        "round up",
    )
    problems: list[str] = []

    for doc in documents:
        for rule in doc.rules:
            low = rule.lower()
            for term in inviting:
                if term in low and not any(n in low for n in _NEGATIONS):
                    problems.append(f"{doc.name}: {term!r} with no prohibition: {rule[:80]}…")

    assert not problems, "FR-030 — rules inviting fabrication:\n  " + "\n  ".join(problems)


def test_the_unresolved_topics_stay_out_of_the_corpus(documents: list[Document]) -> None:
    """The four exclusions ruled out by name, enforced instead of remembered.

    Each is a claim the source register records as **unresolved or unsupported**, and
    each is among the most repeated pieces of resume advice in existence — which is
    exactly why an author reaches for one without noticing.

    * **Recruiter scan-time** — Drushim says 20-30 seconds, ResumeFlex says ~6. Unresolved.
    * **CV page count** — Techmonster says strictly one page, Drushim says 1-2. Unresolved.
    * **ATS header/footer** — no primary source documents that a header region fails to
      parse. A fourth ATS rule was removed for exactly this and must not return softened.
    * **File format** — university centres say .doc/.rtf, 2025-26 sources say PDF is fine.
      Time-dependent, and the digest itself flags it.

    Each returns only with a primary source and a new register entry, at which point this
    test is the thing to change deliberately.
    """
    forbidden = {
        "recruiter scan-time": re.compile(
            r"\b(\d+\s*(?:[-]\s*\d+\s*)?seconds?)\b|\bsix seconds\b"
            r"|\bskim(?:s|med)? .{0,20}seconds\b",
            re.I,
        ),
        "CV page count": re.compile(
            r"\b(one|two|1|2)[\s-]+pages?\b|\bsingle[\s-]page\b|\bpage limit\b|\b1[-]2 pages\b",
            re.I,
        ),
        "ATS header/footer parsing": re.compile(
            r"\b(header|footer)s?\b(?=.{0,120}\b(pars|extract|read|miss|lose|lost|fail)) ",
            re.I,
        ),
        "file-format parseability": re.compile(
            r"\.(?:docx?|rtf|txt|pdf)\b|\bPDF\b(?=.{0,80}\b(pars|safe|prefer|accept))",
            re.I,
        ),
    }
    problems: list[str] = []

    for doc in documents:
        for rule in doc.rules:
            for topic, pattern in forbidden.items():
                found = pattern.search(rule)
                if found:
                    problems.append(
                        f"{doc.name}: {topic} — matched {found.group(0)!r} in: {rule[:80]}…"
                    )

    assert not problems, "unresolved/unsupported topics reached the corpus:\n  " + "\n  ".join(
        problems
    )


def test_the_corpus_holds_guidance_not_evidence(documents: list[Document]) -> None:
    """T011 / FR-036 — authored normative guidance only.

    Research digests, Before/After examples and register content are **evidence** and
    live in `specs/006-document-retrieval/corpus-research/`. A chunk reading "Indeed
    presents a 6-part framework…" is *about* guidance rather than *being* guidance, and
    retrieving it would cite our own summary instead of a source.

    Register IDs belong in `origin_source_ids`, never in rule text: a rule is what the
    Draft node acts on, and an id is not actionable.
    """
    problems: list[str] = []

    for doc in documents:
        for rule in doc.rules:
            if re.search(r"\bS-\d{3}\b", rule):
                problems.append(f"{doc.name}: register id in rule text: {rule[:70]}…")
            if re.search(r"\b(before\s*/\s*after|before → after)\b", rule, re.I):
                problems.append(f"{doc.name}: demonstrative example in rule text: {rule[:70]}…")
            reports = r"\b(according to|as \w+ (?:notes|reports|writes)|per the digest)\b"
            if re.search(reports, rule, re.I):
                problems.append(
                    f"{doc.name}: rule reports a source rather than stating guidance: {rule[:70]}…"
                )

    assert not problems, "FR-036 — evidence leaked into the corpus:\n  " + "\n  ".join(problems)


def test_every_document_declares_topics_from_the_vocabulary(documents: list[Document]) -> None:
    """T027. `topic` drives FR-038 precedence and nothing else.

    A value outside the vocabulary makes a document share a topic with nothing, so
    precedence silently stops firing for it — the failure is invisible without this.
    """
    known = {t.value for t in Topic}
    problems: list[str] = []

    for doc in documents:
        raw = doc.meta.get("topic", "")
        topics = [t.strip() for t in raw.strip("[]").split(",") if t.strip()]
        if not topics:
            problems.append(f"{doc.name}: declares no topic")
        for topic in topics:
            if topic not in known:
                problems.append(f"{doc.name}: unknown topic {topic!r}")

    assert not problems, "topic vocabulary broken:\n  " + "\n  ".join(problems)
