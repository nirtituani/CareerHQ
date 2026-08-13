"""A deliberately failing test, merged on purpose to watch the deployment gate hold.

This file exists for the length of one CI run and is reverted immediately after.
CLAUDE.md requires that a gate be watched failing before it is trusted: a gate
nobody has seen fail is a claim about configuration, not a control. Slice 002's
Wait for CI setting was observed *releasing* a deployment in T041, which shows
it is wired up — but not that it withholds one, which is the property the site
actually depends on.

Deleting this file restores the suite; it touches nothing else.
"""


def test_deliberate_failure_for_t042() -> None:
    """Fail loudly and unambiguously, so the CI log names this drill."""
    assert False, "T042 gate drill — this failure is intentional and is reverted immediately"
