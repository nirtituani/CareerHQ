"use client";

/**
 * One proposal in a tailored draft — what you wrote, what the agent proposes,
 * and the three things you can do about it.
 *
 * **One component for every source kind**, and for every state an item can be
 * in. The import reviewer learned this the expensive way: it had two render
 * paths, one for grouped skills and one for everything else, and an affordance
 * went missing from the second path three separate times — Edit, then Add, then
 * Remove. A summary and an experience bullet differ only in what they are
 * called, so they differ here only in what they are called.
 *
 * Three item shapes arrive here and all are rendered by this one component:
 *
 * 1. **A rewrite.** `proposed_text` is set. The diff, and the controls.
 * 2. **A drop.** `proposed_text` is null and `included` is false — the agent
 *    proposes the line not appear in this version. A removal of existing
 *    content is exactly the change that most needs the owner's decision
 *    (FR-024), so it carries the same controls: Accept keeps it out, Reject
 *    puts the line back, Edit keeps it in the owner's own words.
 * 3. **Unchanged.** `proposed_text` null, `included` true. The agent left it
 *    alone — or its proposal was discarded at finalisation (FR-018), which
 *    persists the same way: the owner's wording stands and there is nothing
 *    to decide. The tab does not pass these here at all; if one arrives
 *    anyway it renders as unchanged, with its finding, and never with
 *    controls.
 *
 * **Nothing here is red.** docs/09 §3 reserves that for things that broke, and
 * a Reviewer note on a draft is the system working exactly as designed.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { ProposalDecision, ReviewerFinding, SourceKind, VersionItem } from "@/lib/api";

/** What each source kind is called on screen, in the owner's terms. */
const KIND_LABEL: Record<SourceKind, string> = {
  summary: "Summary",
  title: "Title",
  experience_bullet: "Experience",
  skill: "Skill",
  project: "Project",
  education: "Education",
  certification: "Certification",
  language: "Language",
};

/**
 * What each finding kind is called.
 *
 * `ungrounded` reads as a statement about the draft, not about the person. "The
 * agent claimed something your profile does not support" — the agent did it,
 * and it has already been undone.
 */
const FINDING_LABEL: Record<ReviewerFinding["kind"], string> = {
  ungrounded: "Not supported by your profile — removed",
  overstated: "Stronger than your profile shows",
  uncovered: "Not addressed",
};

/** Which review pass caught a finding. `0` is the first draft. */
function passLabel(attempt: number): string {
  return attempt === 0 ? "first pass" : `revision ${attempt}`;
}

/**
 * A Reviewer note, against the proposal it concerns (FR-042).
 *
 * Visually subordinate to the text it is about: this is a note in the margin,
 * not a verdict on the item. A finding promoted to the same weight as the
 * proposal would make every flagged item read as a failure, and on a normal
 * draft several of them are ordinary.
 */
export function Finding({
  finding,
  showAttempt = false,
}: {
  finding: ReviewerFinding;
  /**
   * Whether to say which review pass caught this one.
   *
   * True only when the item carries findings from **more than one** pass.
   * Findings persist from every pass deliberately — a fabrication caught on
   * attempt one and fixed on attempt two still happened, and the record is the
   * evidence the guardrail ran. But rendered without that context, three
   * near-identical notes on one bullet read as three simultaneous complaints
   * about the wording currently on screen. They are a history, and saying so
   * costs four words.
   *
   * Off by default for the same reason `EXTRACTED` provenance is never
   * labelled: a marker carried by every finding of every single-pass run tells
   * a reader nothing and costs a line on each.
   */
  showAttempt?: boolean;
}) {
  return (
    <li
      data-testid="finding"
      data-kind={finding.kind}
      className="mt-1.5 border-l-2 pl-2.5 text-xs"
      style={{ borderColor: "var(--color-attention)", color: "var(--muted)" }}
    >
      <span className="font-medium">{FINDING_LABEL[finding.kind]}</span>
      {" — "}
      {finding.detail}
      {finding.quoted_text && (
        <span className="italic" style={{ color: "var(--faint)" }}>
          {" "}
          “{finding.quoted_text}”
        </span>
      )}
      {showAttempt && (
        <span style={{ color: "var(--faint)" }}> ({passLabel(finding.attempt)})</span>
      )}
    </li>
  );
}

/** One block of text, labelled by what it is rather than by who wrote it. */
function Text({
  label,
  value,
  muted = false,
  testId,
}: {
  label: string;
  value: string;
  muted?: boolean;
  testId: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-xs tracking-wide uppercase" style={{ color: "var(--faint)" }}>
        {label}
      </p>
      <p
        data-testid={testId}
        className="mt-0.5 text-sm"
        style={muted ? { color: "var(--muted)" } : undefined}
      >
        {value}
      </p>
    </div>
  );
}

/** What the owner decided, once they have. Never shown while `pending`, where
 *  the controls themselves say what is available. */
const DECIDED_LABEL: Record<Exclude<ProposalDecision, "pending">, string> = {
  accepted: "Using the proposal",
  rejected: "Keeping your wording",
  edited: "Using your words",
};

export function TailorDiffItem({
  item,
  onDecide,
  disabled = false,
}: {
  item: VersionItem;
  onDecide: (
    decision: Exclude<ProposalDecision, "pending">,
    text?: string,
  ) => Promise<void> | void;
  /**
   * True once the version's **content is locked** — `exported` or `submitted`,
   * the two states in `application/immutability.py`'s `LOCKED_STATUSES`.
   *
   * **Not `ready`**, which this comment used to say while no caller passed the
   * prop at all, so the wrong set was never exercised. FR-029 requires an
   * approved version to remain editable; locking it here would be the stricter
   * reading that removes the ability to fix a typo before exporting.
   *
   * The item still renders in full either way — hiding what the document says
   * would be a different claim from saying it can no longer be changed.
   */
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.final_text);
  const [busy, setBusy] = useState(false);

  const unchanged = item.proposed_text === null && item.included;

  // Whether this item was objected to across more than one review pass. Only
  // then does naming the pass tell the reader anything.
  const spansPasses = new Set(item.findings.map((f) => f.attempt)).size > 1;

  async function decide(decision: Exclude<ProposalDecision, "pending">, text?: string) {
    setBusy(true);
    try {
      await onDecide(decision, text);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li
      data-testid="diff-item"
      data-decision={item.decision}
      data-kind={item.source_kind}
      className="border-b py-3.5 last:border-0"
      style={{ borderColor: "var(--border)" }}
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="text-xs tracking-wide uppercase" style={{ color: "var(--muted)" }}>
          {KIND_LABEL[item.source_kind]}
        </p>

        {item.decision !== "pending" && (
          <span data-testid="decision-label" className="text-xs" style={{ color: "var(--muted)" }}>
            {DECIDED_LABEL[item.decision]}
          </span>
        )}
      </div>

      {unchanged ? (
        <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          {item.original_text}
        </p>
      ) : (
        <div className="mt-1.5 grid gap-3 sm:grid-cols-2">
          {/* Both, always, side by side (FR-041). A proposal shown without what
              it replaces asks a person to approve a change they cannot see. */}
          <Text
            label="Your wording"
            value={item.original_text}
            muted
            testId="original-text"
          />
          {item.proposed_text !== null ? (
            <Text
              // A rewrite proposed *together with* exclusion must say both —
              // rendering the new wording under a plain "Proposed" would hide
              // that accepting it removes the line from the document.
              label={item.included ? "Proposed" : "Proposed — removed from this version"}
              value={item.proposed_text}
              testId="proposed-text"
            />
          ) : (
            // A drop. What is proposed is an absence, so it is said as one —
            // rendering nothing here would make the row read as a rewrite
            // with the proposal missing.
            <div className="min-w-0">
              <p className="text-xs tracking-wide uppercase" style={{ color: "var(--faint)" }}>
                Proposed
              </p>
              <p data-testid="proposed-removal" className="mt-0.5 text-sm">
                Remove from this version.
              </p>
            </div>
          )}
        </div>
      )}

      {item.findings.length > 0 && (
        <ul data-testid="item-findings">
          {item.findings.map((finding, index) => (
            <Finding key={index} finding={finding} showAttempt={spansPasses} />
          ))}
        </ul>
      )}

      {editing && (
        <div className="mt-2.5">
          <label className="block">
            <span className="text-xs" style={{ color: "var(--faint)" }}>
              Your words
            </span>
            <textarea
              rows={3}
              autoFocus
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              aria-label={`Edit ${KIND_LABEL[item.source_kind]}`}
              className="mt-0.5 w-full rounded-md border px-2 py-1 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}
            />
          </label>
          <div className="mt-1.5 flex gap-2">
            <Button
              size="sm"
              disabled={busy || draft.trim() === ""}
              onClick={() => decide("edited", draft)}
            >
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* No controls on an unchanged item: there is nothing to decide, and a
          button that changes nothing is the contradiction the import
          reviewer's old Keep button had. */}
      {!editing && !unchanged && !disabled && (
        <div className="mt-2.5 flex gap-2">
          <Button
            size="sm"
            variant={item.decision === "accepted" ? "default" : "outline"}
            disabled={busy}
            onClick={() => decide("accepted")}
          >
            {item.decision === "accepted" ? "Accepted" : "Accept"}
          </Button>
          {/* Rejecting starts no AI work (FR-026). It is the action that means
              "stop", and a silent re-draft here would be a provider call the
              person explicitly declined. */}
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => decide("rejected")}
          >
            {item.decision === "rejected" ? "Rejected" : "Reject"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              setDraft(item.final_text);
              setEditing(true);
            }}
          >
            Edit
          </Button>
        </div>
      )}
    </li>
  );
}
