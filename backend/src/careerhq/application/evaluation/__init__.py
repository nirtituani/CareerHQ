"""The evaluation harness — how well the tailoring agent works.

**This package computes numbers; it never changes the system it measures.** Every
module here reads persisted records and returns a value with the count it was
computed over. Nothing writes to a user's professional data, nothing approves a
proposal, and nothing edits an existing run.

**No provider SDK may be imported from here.** The judge — the one component that
needs a model — reaches it through `complete()` like every other caller, so
`test_the_application_layer_imports_no_provider_sdk` covers this package the
moment it exists (Principle V).

**Two criteria named SC-008 exist and they are different questions.** Slice 006's
SC-008 is retrieval's cost per run against a ≤2% threshold, and it is
**MISSED at 3.22%** — unchanged, not reinterpreted, and not superseded by
anything here. Slice 007's SC-008 is about whether *the measurement can resolve
its own threshold*. Wherever both appear, slice 006's is written `SC-008 (006)`.
`tests/unit/test_sc008_is_not_relabelled.py` is the gate on that.
"""
