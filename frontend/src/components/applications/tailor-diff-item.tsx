"use client";

/**
 * One proposal in a tailored draft — what you wrote, what the agent proposes,
 * and the three things you can do about it. Rendered as an expandable card
 * per the Tailor redesign: a collapsed header row (change badge, section,
 * headline, decision, caret) opening into the Current/Recommended comparison,
 * the Reviewer's notes, and the controls.
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
export const KIND_LABEL: Record<SourceKind, string> = {
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

/** One half of the comparison, labelled by what it is rather than by who wrote
 *  it. `tone` colours the panel, never the claim. */
function Text({
  label,
  sublabel,
  value,
  tone,
  testId,
}: {
  label: string;
  sublabel?: string;
  value: string;
  tone: "current" | "recommended";
  testId: string;
}) {
  const accent = tone === "recommended" ? "var(--color-brand-500)" : "var(--color-attention)";
  return (
    <div
      className="min-w-0 overflow-hidden rounded-lg border"
      style={{ borderColor: `color-mix(in srgb, ${accent} 30%, transparent)` }}
    >
      <p
        className="px-3 py-2 text-xs tracking-wide uppercase"
        style={{ color: accent, background: `color-mix(in srgb, ${accent} 10%, transparent)` }}
      >
        {label}
        {sublabel && (
          <span className="ml-2 normal-case" style={{ color: "var(--faint)", letterSpacing: 0 }}>
            {sublabel}
          </span>
        )}
      </p>
      <p data-testid={testId} className="px-3 py-2.5 text-sm leading-relaxed">
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

/** The card's one-line headline: always the item's real content, never a
 *  manufactured summary — the agent's rationale is not persisted, and a
 *  paraphrase here would be a claim nobody made. */
function headlineFor(item: VersionItem): string {
  if (item.proposed_text !== null) return item.proposed_text;
  if (!item.included) return "Remove this line from the tailored version";
  return item.final_text;
}

/** What accepting does, stated deterministically from the proposal's shape. */
function effectFor(item: VersionItem): string | null {
  if (item.decision !== "pending") return null;
  if (item.proposed_text !== null && !item.included)
    return "Accepting replaces this line and removes it from this version.";
  if (item.proposed_text !== null) return "Accepting replaces this line.";
  if (!item.included) return "Accepting removes this line from this version.";
  return null;
}

export function TailorDiffItem({
  item,
  onDecide,
  disabled = false,
  open = true,
  onToggle,
  sectionLabel,
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
   * **Not `ready`**: FR-029 requires an approved version to remain editable.
   * The item still renders in full either way — hiding what the document says
   * would be a different claim from saying it can no longer be changed.
   */
  disabled?: boolean;
  /** Whether the card is expanded. Defaults open so the component stands
   *  alone; the tab drives the one-open-at-a-time accordion. */
  open?: boolean;
  onToggle?: () => void;
  /** "Experience — Meridian Systems" rather than the bare kind, when the tab
   *  knows the role. Falls back to the kind label. */
  sectionLabel?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.final_text);
  const [busy, setBusy] = useState(false);

  const unchanged = item.proposed_text === null && item.included;
  const isDrop = item.proposed_text === null && !item.included;

  // Whether this item was objected to across more than one review pass. Only
  // then does naming the pass tell the reader anything.
  const spansPasses = new Set(item.findings.map((f) => f.attempt)).size > 1;

  const removes = !item.included;
  const changeBadge = item.proposed_text !== null ? "REWRITE" : isDrop ? "REMOVE" : "KEPT";
  const effect = effectFor(item);

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
      className="mb-2.5 overflow-hidden rounded-xl border last:mb-0"
      style={{
        borderColor: open
          ? "color-mix(in srgb, var(--color-brand-500) 30%, transparent)"
          : "var(--border)",
        background: "var(--surface)",
        opacity: item.decision !== "pending" && !open ? 0.72 : 1,
      }}
    >
      {/* The whole header toggles — the card is the disclosure, per the
          redesign's one-open-at-a-time accordion. */}
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-3.5 px-4 py-3.5 text-left"
      >
        <span
          className="flex-none rounded px-2 py-1 text-[10px] tracking-wider"
          style={{
            fontFamily: "var(--font-mono)",
            color: removes ? "var(--color-attention)" : "var(--color-brand-500)",
            background: `color-mix(in srgb, ${
              removes ? "var(--color-attention)" : "var(--color-brand-500)"
            } 12%, transparent)`,
          }}
        >
          {changeBadge}
        </span>
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="text-sm font-semibold" style={{ color: "var(--foreground)" }}>
            {sectionLabel ?? KIND_LABEL[item.source_kind]}
          </span>
          <span className="truncate text-xs" style={{ color: "var(--muted)" }}>
            {headlineFor(item)}
          </span>
        </span>
        {item.decision !== "pending" ? (
          <span
            data-testid="decision-label"
            className="flex-none text-xs"
            style={{ color: "var(--muted)" }}
          >
            {DECIDED_LABEL[item.decision]}
          </span>
        ) : (
          !unchanged && (
            <span className="flex-none text-xs" style={{ color: "var(--faint)" }}>
              To review
            </span>
          )
        )}
        <span
          aria-hidden
          className="flex h-6 w-6 flex-none items-center justify-center rounded-md text-sm"
          style={{
            color: open ? "var(--color-brand-500)" : "var(--muted)",
            background: "color-mix(in srgb, var(--foreground) 6%, transparent)",
          }}
        >
          {open ? "−" : "+"}
        </span>
      </button>

      {open && (
        <div className="flex flex-col gap-3.5 px-4 pt-0.5 pb-4">
          {unchanged ? (
            // `final_text`, not `original_text`: for a genuinely unchanged row
            // the two are identical, but a sticky row after an edited drop
            // carries the owner's replacement in `final_text` — and this line
            // must show what the document will actually contain.
            <p className="text-sm" style={{ color: "var(--muted)" }}>
              {item.final_text}
            </p>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {/* Both, always, side by side (FR-041). A proposal shown without
                  what it replaces asks a person to approve a change they
                  cannot see. */}
              <Text
                label="Your wording"
                sublabel="in your CV today"
                value={item.original_text}
                tone="current"
                testId="original-text"
              />
              {item.proposed_text !== null ? (
                <Text
                  // A rewrite proposed *together with* exclusion must say both —
                  // the new wording under a plain "Proposed" would hide that
                  // accepting it removes the line from the document.
                  label={item.included ? "Proposed" : "Proposed — removed from this version"}
                  sublabel={item.included ? "replaces the text if accepted" : undefined}
                  value={item.proposed_text}
                  tone="recommended"
                  testId="proposed-text"
                />
              ) : (
                // A drop. What is proposed is an absence, so it is said as one —
                // rendering nothing here would make the row read as a rewrite
                // with the proposal missing.
                <div
                  className="min-w-0 overflow-hidden rounded-lg border"
                  style={{
                    borderColor: "color-mix(in srgb, var(--color-attention) 30%, transparent)",
                  }}
                >
                  <p
                    className="px-3 py-2 text-xs tracking-wide uppercase"
                    style={{
                      color: "var(--color-attention)",
                      background: "color-mix(in srgb, var(--color-attention) 10%, transparent)",
                    }}
                  >
                    Proposed
                  </p>
                  <p data-testid="proposed-removal" className="px-3 py-2.5 text-sm">
                    Remove from this version.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* "Why this change?" holds everything that explains the proposal:
              the Reviewer's notes — the only stored explanation; the agent's
              own rationale is not persisted — and the deterministic statement
              of what accepting does. Rendered only when there is something to
              say: an empty explanation panel would be a promise nobody kept. */}
          {(item.findings.length > 0 || effect !== null) && (
            <div
              className="rounded-lg border px-3.5 py-3"
              style={{
                borderColor: "var(--border)",
                background: "color-mix(in srgb, var(--foreground) 2.5%, transparent)",
              }}
            >
              <p className="text-xs font-bold" style={{ color: "var(--foreground)" }}>
                Why this change?
              </p>
              {item.findings.length > 0 && (
                <ul data-testid="item-findings">
                  {item.findings.map((finding, index) => (
                    <Finding key={index} finding={finding} showAttempt={spansPasses} />
                  ))}
                </ul>
              )}
              {effect !== null && (
                <p className="mt-1.5 text-xs" style={{ color: "var(--faint)" }}>
                  {effect}
                </p>
              )}
            </div>
          )}

          {editing && (
            <div>
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

          {/* No controls on an unchanged item: there is nothing to decide, and
              a button that changes nothing is the contradiction the import
              reviewer's old Keep button had. */}
          {!editing && !unchanged && !disabled && (
            <div className="flex gap-2">
              <Button
                size="sm"
                variant={item.decision === "accepted" ? "default" : "outline"}
                disabled={busy}
                onClick={() => decide("accepted")}
              >
                {item.decision === "accepted" ? "Accepted" : "Accept"}
              </Button>
              {/* Rejecting starts no AI work (FR-026). It is the action that
                  means "stop", and a silent re-draft here would be a provider
                  call the person explicitly declined. */}
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide("rejected")}>
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
        </div>
      )}
    </li>
  );
}
