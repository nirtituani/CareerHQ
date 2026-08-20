"use client";

/**
 * The Match tab — why this job fits, and what is missing.
 *
 * Written as a **reading surface**, per docs/09 §4: hairline rules, one line
 * per requirement, no card grid. A person opening this has often just been
 * rejected, so it stays calm and useful — never chipper, never alarming.
 *
 * Four decisions carry the design, and none would show up in a passing build:
 *
 * 1. **A section says its meaning once.** Everything under WHAT'S MISSING is
 *    missing; tagging each row "Not on your CV" restated the heading on every
 *    line and buried the one row that meant something else. The section's
 *    default verdict goes unlabelled and only the exception is marked.
 * 2. **Importance is shown, not merely implied by order.** A three-segment
 *    meter — the pattern docs/09 §5 already uses for confidence, because it is
 *    the same shape of signal: a 0–100 value that informs a person without
 *    deciding for them.
 * 3. **`unverified` sits with the gaps.** A requirement your CV does not
 *    evidence costs the interview whether or not the shortfall is provable.
 * 4. **Nothing is red.** docs/09 §3 reserves that for things that broke, and an
 *    ordinary posting produces plenty of unmet requirements.
 */

import { useState } from "react";

import {
  VERDICT_GLYPH,
  type MatchBand as Band,
  type Verdict,
  bandLabel,
} from "@/components/applications/match-score";
import { type MatchAnalysis, type MatchRequirement, type MatchState, runMatch } from "@/lib/api";

/**
 * What each verdict is called, used only where it is *not* the section default.
 *
 * Every one names the thing rather than describing it. `unverified` reads "Not
 * on your CV" — true whether or not you have the skill, and never a claim that
 * you lack it.
 */
const LABEL: Record<Verdict, string> = {
  confirmed: "On your CV",
  partial: "Partly shown",
  transferable: "Related",
  gap: "Below what they ask",
  unverified: "Not on your CV",
};

/** Three tiers, matching the bands the prompt anchors the model to. */
function tier(importance: number): { filled: number; name: string } {
  if (importance >= 70) return { filled: 3, name: "critical" };
  if (importance >= 40) return { filled: 2, name: "important" };
  return { filled: 1, name: "minor" };
}

/**
 * How much this requirement matters, as segments rather than a number.
 *
 * Twelve numbers down a column is noise; three segments is a shape you read
 * without stopping. The value still reaches assistive technology and the
 * tooltip, so the meter is never the only channel (docs/09 §7).
 */
function Priority({ requirement }: { requirement: MatchRequirement }) {
  const { filled, name } = tier(requirement.importance);

  return (
    <span
      className="mt-1.5 inline-flex shrink-0 gap-0.5"
      title={`${name} to this role (${requirement.importance}/100)`}
      aria-label={`${requirement.text} — ${name} to this role`}
    >
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          aria-hidden
          className="block h-3 w-1 rounded-[1px]"
          style={{ background: i < filled ? "var(--color-brand-500)" : "var(--border)" }}
        />
      ))}
    </span>
  );
}

function Row({ requirement, showLabel }: { requirement: MatchRequirement; showLabel: boolean }) {
  return (
    <li
      className="flex items-start gap-3 border-b py-2.5 last:border-0"
      style={{ borderColor: "var(--border)" }}
    >
      <Priority requirement={requirement} />

      <div className="min-w-0 flex-1">
        <p className="text-sm">{requirement.text}</p>
        {/* The proof, one line, clipped. It is the grounding AI-008 depends on,
            so it stays on the page rather than behind a click — but it is set
            quiet, because the requirement is what a person scans. */}
        {requirement.evidence && (
          <p
            className="truncate text-xs italic"
            style={{ color: "var(--faint)" }}
            title={requirement.evidence}
          >
            {requirement.evidence}
          </p>
        )}
      </div>

      {showLabel && (
        <span
          className="mt-0.5 shrink-0 text-xs whitespace-nowrap"
          style={{ color: "var(--muted)" }}
        >
          <span aria-hidden>{VERDICT_GLYPH[requirement.verdict]}</span> {LABEL[requirement.verdict]}
        </span>
      )}
    </li>
  );
}

function Section({
  title,
  note,
  requirements,
  defaultVerdict,
  testId,
}: {
  title: string;
  note: string;
  requirements: MatchRequirement[];
  /** The verdict this section is *about*. Rows carrying it go unlabelled. */
  defaultVerdict: Verdict;
  testId: string;
}) {
  if (requirements.length === 0) return null;

  return (
    <section className="mt-8" data-testid={testId}>
      <div className="flex items-baseline justify-between gap-4">
        <h3
          className="text-xs font-medium tracking-wide uppercase"
          style={{ color: "var(--muted)" }}
        >
          {title}
        </h3>
        <span className="tabular text-xs" style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}>
          {requirements.length}
        </span>
      </div>

      {/* Said once, for the section, instead of on every row. */}
      <p className="mt-1 text-xs" style={{ color: "var(--faint)" }}>
        {note}
      </p>

      <ul className="mt-2">
        {requirements.map((r) => (
          <Row key={r.ordinal} requirement={r} showLabel={r.verdict !== defaultVerdict} />
        ))}
      </ul>
    </section>
  );
}

const SUPPORTED: Verdict[] = ["confirmed", "partial", "transferable"];

export function MatchTab({
  state,
  analysis,
  stale,
  applicationId,
}: {
  state: MatchState;
  analysis: MatchAnalysis | null;
  stale: boolean;
  applicationId?: string;
}) {
  const [running, setRunning] = useState(false);

  if (state === "nothing_to_score" || analysis === null) {
    return (
      <p className="py-8 text-sm" style={{ color: "var(--muted)" }}>
        There is nothing to score against yet. Add the job posting and its requirements, and this
        job will be scored against your profile.
      </p>
    );
  }

  if (state === "failed") {
    return (
      <div className="py-8">
        <p
          role="alert"
          className="border-l-2 pl-3 text-sm"
          style={{ borderColor: "var(--color-failure)" }}
        >
          {analysis.error ?? "The analysis could not be completed."}
        </p>
        <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
          Everything else about this job is unaffected — you can still edit it and move its status.
        </p>
      </div>
    );
  }

  if (state === "running") {
    return (
      <p className="py-8 text-sm" style={{ color: "var(--muted)" }}>
        Scoring this job against your profile…
      </p>
    );
  }

  const supported = analysis.requirements.filter((r) => SUPPORTED.includes(r.verdict));
  // Importance first, so the requirement that actually costs the interview is
  // read first. Posting order buries it under boilerplate.
  const byImportance = (a: MatchRequirement, b: MatchRequirement) => b.importance - a.importance;
  const missing = analysis.requirements.filter((r) => !SUPPORTED.includes(r.verdict)).sort(byImportance);

  return (
    <div className="py-6">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        {/* A large figure, so the serif — docs/09 §2. */}
        <span
          className="text-3xl"
          style={{ fontFamily: "var(--font-display)", color: "var(--fg)" }}
        >
          {analysis.band ? bandLabel(analysis.band as Band) : "—"}
        </span>
        <span data-testid="coverage" className="text-sm" style={{ color: "var(--muted)" }}>
          <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
            {supported.length}/{analysis.requirements.length}
          </span>{" "}
          requirements shown on your profile
        </span>
      </div>

      {analysis.verdict && (
        <p className="mt-2 max-w-prose text-sm" style={{ color: "var(--muted)" }}>
          {analysis.verdict}
        </p>
      )}

      {stale && (
        <p className="mt-4 text-sm" style={{ color: "var(--muted)" }}>
          Your profile has changed since this was scored.{" "}
          {applicationId && (
            <button
              type="button"
              disabled={running}
              onClick={async () => {
                setRunning(true);
                await runMatch(applicationId).catch(() => undefined);
                setRunning(false);
              }}
              className="underline underline-offset-4 disabled:opacity-50"
            >
              {running ? "Scoring…" : "Score it again"}
            </button>
          )}
        </p>
      )}

      <Section
        testId="whats-missing"
        title="What's missing"
        note="Not on your CV — add anything you have and score again."
        requirements={missing}
        defaultVerdict="unverified"
      />

      <Section
        testId="why-it-fits"
        title="Why it fits"
        note="Quoted from your profile."
        requirements={supported}
        defaultVerdict="confirmed"
      />

      <p
        data-testid="analysis-provenance"
        className="mt-8 border-t pt-3 text-xs"
        style={{ borderColor: "var(--border)", color: "var(--faint)" }}
      >
        {/* Principle III: visibly AI-generated, with what produced it and what
            it cost. Monospace, because it is reported verbatim (docs/09 §1). */}
        <span style={{ fontFamily: "var(--font-mono)" }}>
          Scored by AI · {analysis.model ?? "unknown"} · ${analysis.cost ?? "0"} ·{" "}
          {analysis.criteria_version}
        </span>
        {analysis.is_fixture && " · FIXTURE DATA — not a real analysis"}
      </p>
    </div>
  );
}
