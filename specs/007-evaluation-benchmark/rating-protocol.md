# The human-rating protocol *(T030, D8)*

**The smallest defensible design, and no sample size assumed.**

## Pairwise, not absolute — and why the choice is explicit

They are different instruments answering different questions, and picking one by
implication is how a sample size gets chosen by accident.

| | Absolute rating | **Pairwise comparison** |
|---|---|---|
| The human is asked | "score this résumé 1–5 against the rubric" | "which of these two is better for this posting?" |
| Agreement statistic | correlation, or exact/adjacent agreement | proportion of pairs ordered the same way |
| Stability | lower — people anchor differently between sittings, and drift within one | higher — a relative judgement is the easier task |
| Answers | "how good is the system?" | **"did this change help?"** |

**Pairwise is chosen** because the slice's central claim is the second question.
T057 is a before/after; the regression report is a before/after; the noise floor is
a comparison of two runs of an unchanged system. Every one of those is relative.

**A small absolute anchor set is kept** — a handful of résumés rated 1–5 — for one
narrow purpose: giving the rubric a fixed reference so scores do not drift when the
rubric is versioned. It is not used for agreement.

## What the rater sees, and what they must not

Shown: the posting, and two résumés, labelled A and B.

Withheld: which arm, configuration or version produced either; which one the judge
preferred; and any earlier rating of the same pair. **A/B order is randomised per
pair**, because a rater who notices that the newer version is always B is no longer
rating résumés.

## The sample size, and why it is not written down here

`agreement()` reports `comparable_pairs` alongside every figure, and the rule stands
in place of a number:

> **The sample must be large enough that the agreement figure would change if the
> judge were random.**

With *k* judged outputs, pairwise comparison offers *k(k−1)/2* pairs, so the count
follows arithmetically from the judged-output count — which follows from D3. It is
computed when that number is fixed, not guessed now. **An earlier draft set 15
outputs and 70% by analogy with SC-001 (006); both were guesses wearing a
threshold's clothes**, and the analogy does not hold — SC-001 (006) asks one
reviewer to compare two *guidance sets*, a different task with a different error
rate from rating generated résumés.

## Ties are excluded, and that is not a detail

`agreement()` drops any pair where either side scored them equal. **A judge that
scored everything identically would otherwise agree perfectly with any human at
all** — the single most flattering failure available to this metric, and it is
closed by construction rather than by watching for it.

`agreed` is `None` when no pair is comparable. Never `0.0`, which would read as
total disagreement where the truth is that there was nothing to compare.

## What a rating is worth before agreement is measured

**Nothing** (FR-025). Until agreement has been computed on a sample, every judge
score is labelled **unvalidated**, and no conclusion in this slice rests on one.
