"""T052 — the guidance block sends rule text, and the citation stays in the record.

**What this changes and what it deliberately does not.** The prompt used to render
`- {text}  [{slug} v{n} · {locator} · {hash12}]` per guideline. Measured on the real
recorded snapshot with the corpus's own tokenizer (`cl100k_base`, the one
`corpus/loader.py` counts with): the retrieval block was **2,190 tokens — 1,523 rule
text and 667 citation**, 30% of the block. The static block was 492 (358 + 134).

**Nothing consumed those 667 tokens.** No output schema has a citation field — every
`source_*` in `domain/schemas/tailoring.py` is `source_item_id`, a *profile* item. No
prompt instructs the model about the bracket. No test asserted it. Nothing in the
frontend renders `guidelines_used`. The model was being sent a content hash per rule
and asked to do nothing with it.

**Resolvability was never the prompt's job.** FR-012 governs *"the citations **recorded**
by earlier runs"* and SC-002 governs items *"**shown or recorded**"* — `guidelines_used`,
written by `citation_snapshot()` from the retrieved objects, never from the prompt state.
That snapshot is **untouched** by this change and still carries `document_slug`,
`document_version`, the **full** `content_hash`, `locator` and `market` as structured
fields. `tests/integration/test_guideline_snapshot.py` is the gate on it and was not
edited, which is the point: the record's guarantees are independent of the prompt's.

**Out of scope, deliberately**: retrieval selection, the FR-014 token ceiling, the
`citation_snapshot` schema, and SC-008's definition or target. This removes waste; it
does not move a threshold.
"""

from __future__ import annotations

import re

import tiktoken

from careerhq.application.agents.tailoring.prompts import (
    build_draft_prompt,
    build_plan_prompt,
)
from careerhq.application.agents.tailoring.state import TailoringState

#: A hash prefix as `_citation` renders it — twelve hex characters. This is the single
#: most expensive part of the old citation per character, because a hex run tokenizes
#: into many short pieces where prose does not.
_HASH12 = "6f35f48fd2e9"

#: Shaped exactly like a real entry in `TailoringState.guidelines`: the state still
#: carries `source`, because narrowing the state key is a 005/006 boundary change this
#: task has no mandate to make. What changed is only whether the prompt renders it.
_GUIDELINES = [
    {
        "text": "Lead each bullet with the outcome, not the responsibility.",
        "source": f"universal-experience-bullets v1 · rule 3 · {_HASH12}",
    },
    {
        "text": "Never state a tool the profile does not evidence.",
        "source": f"integrity-no-fabrication v1 · rule 1 · {_HASH12}",
    },
]


def _state() -> TailoringState:
    return TailoringState(
        job={"title": "Senior Backend Engineer"},
        master="[id: 11111111-1111-1111-1111-111111111111] BULLET: Ran payments.",
        match={},
        plan={"strategy": "Lead with payments."},
        guidelines=list(_GUIDELINES),
    )


def _prompts() -> dict[str, str]:
    state = _state()
    return {"plan": build_plan_prompt(state), "draft": build_draft_prompt(state)}


def test_no_content_hash_reaches_the_model() -> None:
    """The regression gate. A twelve-character hash per rule, that nothing reads."""
    for name, prompt in _prompts().items():
        assert _HASH12 not in prompt, f"the {name} prompt still carries a content hash"


def test_no_citation_metadata_reaches_the_model() -> None:
    """Not just the hash — the slug, version and locator went with it.

    Asserted against the **whole** citation rather than the hash alone, because dropping
    only the hash would leave most of the tokens: the slug is hyphenated and the locator
    is `rule N`, and both fragment badly.
    """
    for name, prompt in _prompts().items():
        for guideline in _GUIDELINES:
            assert guideline["source"] not in prompt, (
                f"the {name} prompt still carries the citation {guideline['source']!r}"
            )
        assert "universal-experience-bullets" not in prompt, f"{name}: slug leaked"
        assert re.search(r"\brule 3\b", prompt) is None, f"{name}: locator leaked"


def test_the_rule_text_itself_still_reaches_the_model() -> None:
    """**The half that must not be lost.** Removing the citation is only correct if the
    guidance itself is untouched — an empty guidance block would also pass every
    assertion above."""
    for name, prompt in _prompts().items():
        for guideline in _GUIDELINES:
            assert guideline["text"] in prompt, f"{name} lost the rule text"


def test_the_guidance_block_is_still_a_labelled_list() -> None:
    """FR-013 treats retrieved content as data. The block keeps its heading and its list
    markers, so a rule is still visibly one item of quoted guidance rather than a
    sentence merged into the surrounding instructions."""
    for name, prompt in _prompts().items():
        assert "## Resume-writing guidance" in prompt, f"{name} lost the guidance heading"
        for guideline in _GUIDELINES:
            assert f"- {guideline['text']}" in prompt, f"{name} lost the list marker"


def test_the_saving_is_the_measured_citation_overhead() -> None:
    """Quantified with the corpus's own tokenizer, so the claim is a number rather than
    an adjective. Measured on the real snapshot for run `7c1d64d4`: 27 guidelines,
    2,190 tokens rendered, of which **667 were citation**. This asserts the *shape* of
    that saving on a fixture — the block is now the rule text plus list punctuation, and
    carries no citation tokens at all.
    """
    encoding = tiktoken.get_encoding("cl100k_base")
    old_block = "\n".join(f"- {g['text']}  [{g['source']}]" for g in _GUIDELINES)
    new_block = "\n".join(f"- {g['text']}" for g in _GUIDELINES)

    old_tokens = len(encoding.encode(old_block))
    new_tokens = len(encoding.encode(new_block))
    saved = old_tokens - new_tokens

    assert saved > 0
    # The citation was ~30% of the real retrieval block. On this fixture the rules are
    # short, so the share is higher; the assertion is that it is a substantial fraction
    # rather than a rounding difference.
    assert saved / old_tokens > 0.20, (
        f"expected the citation to be a substantial share of the block, got {saved}/{old_tokens}"
    )
    assert new_block in build_plan_prompt(_state()), "the rendered block is text-only"
