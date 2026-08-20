"use client";

/**
 * The Match tab — why this job fits, and what is missing.
 *
 * The applications table answers *whether* with one word. This answers *why*,
 * and it is what makes the number trustworthy rather than merely present.
 *
 * Three decisions here are load-bearing and none of them would show up in a
 * passing build:
 *
 * 1. **`unverified` sits with the gaps, not in a bucket of its own.** A
 *    requirement your CV does not evidence costs you the interview whether or
 *    not the shortfall is provable — a recruiter reads the same profile the
 *    model does. Filing it separately would make the most actionable finding
 *    the least visible.
 * 2. **What's missing is ordered by importance, not by the posting.** The thing
 *    that actually costs you the role has to be first; posting order buries it
 *    under boilerplate the model already rated 15.
 * 3. **Nothing here is red.** docs/09 §3 reserves that for things that broke,
 *    and a normal posting produces plenty of unmet requirements — painting them
 *    red makes an ordinary application look like a catastrophe.
 */

import { useState } from "react";

import {
  VERDICT_GLYPH,
  type Verdict,
  bandLabel,
  type MatchBand as Band,
} from "@/components/applications/match-score";
import { type MatchAnalysis, type MatchRequirement, type MatchState, runMatch } from "@/lib/api";

/**
 * What each verdict is called on screen.
 *
 * Every one names what to do about it. `unverified` was "Not stated", which
 * read as a technicality — it is now "Not on your CV", which is true whether or
 * not you have the skill, states what it costs, and points at the fix. It never
 * says you lack the skill, because the profile does not show that.
 */
const LABEL: Record<Verdict, string> = {
  confirmed: "On your CV",
  partial: "Partly shown",
  transferable: "Related experience",
  gap: "Below what they ask",
  unverified: "Not on your CV",
};

/** What to do next, which is the whole reason `shortfall` exists (FR-011c). */
const ACTION: Record<string, string> = {
  wording: "You have this — say it in their words.",
  evidence: "Plausible from your profile, but not proven. Add the specifics.",
  capability: "A real gap. Decide whether to apply anyway.",
};

const SUPPORTED: Verdict[] = ["confirmed", "partial", "transferable"];

function Chip({ verdict }: { verdict: Verdict }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs"
      style={{ background: "var(--surface-sunken)", color: "var(--muted)" }}
    >
      {/* The glyph carries the meaning so it survives greyscale and colour
          blindness (docs/09 §7). Colour alone would collapse `unverified` and
          `gap` into one another, which is the distinction that matters most. */}
      <span aria-hidden>{VERDICT_GLYPH[verdict]}</span>
      {LABEL[verdict]}
    </span>
  );
}

function Requirement({ requirement }: { requirement: MatchRequirement }) {
  return (
    <li className="border-b py-3 last:border-0" style={{ borderColor: "var(--border)" }}>
      <div className="flex items-start justify-between gap-3">
        <span className="text-sm">{requirement.text}</span>
        <Chip verdict={requirement.verdict} />
      </div>

      {requirement.evidence && (
        <p
          className="mt-1.5 border-l-2 pl-3 text-xs italic"
          style={{ borderColor: "var(--border)", color: "var(--muted)" }}
        >
          {requirement.evidence}
        </p>
      )}

      {requirement.shortfall && (
        <p className="mt-1.5 text-xs" style={{ color: "var(--muted)" }}>
          {ACTION[requirement.shortfall]}
        </p>
      )}

      {requirement.verdict === "unverified" && (
        <p className="mt-1.5 text-xs" style={{ color: "var(--muted)" }}>
          Your profile does not mention this. If you have it, add it to your profile and score
          again.
        </p>
      )}
    </li>
  );
}

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
  // read first. `unverified` is in here with the gaps deliberately.
  const missing = analysis.requirements
    .filter((r) => !SUPPORTED.includes(r.verdict))
    .sort((a, b) => b.importance - a.importance);

  return (
    <div className="py-6">
      <div className="flex flex-wrap items-baseline gap-3">
        <span className="text-2xl font-semibold">
          {analysis.band ? bandLabel(analysis.band as Band) : "—"}
        </span>
        <span data-testid="coverage" className="text-sm" style={{ color: "var(--muted)" }}>
          {supported.length} / {analysis.requirements.length} requirements shown on your profile
        </span>
      </div>

      {analysis.verdict && <p className="mt-2 text-sm">{analysis.verdict}</p>}

      {stale && (
        <div
          className="mt-4 border-l-2 pl-3 text-sm"
          style={{ borderColor: "var(--border)", color: "var(--muted)" }}
        >
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
        </div>
      )}

      {supported.length > 0 && (
        <section className="mt-6">
          <h3 className="text-xs font-semibold tracking-wide" style={{ color: "var(--muted)" }}>
            WHY IT FITS
          </h3>
          <ul className="mt-1">
            {supported.map((r) => (
              <Requirement key={r.ordinal} requirement={r} />
            ))}
          </ul>
        </section>
      )}

      {missing.length > 0 && (
        <section className="mt-6" data-testid="whats-missing">
          <h3 className="text-xs font-semibold tracking-wide" style={{ color: "var(--muted)" }}>
            WHAT&rsquo;S MISSING
          </h3>
          <ul className="mt-1">
            {missing.map((r) => (
              <Requirement key={r.ordinal} requirement={r} />
            ))}
          </ul>
        </section>
      )}

      <p
        data-testid="analysis-provenance"
        className="mt-6 border-t pt-3 text-xs"
        style={{ borderColor: "var(--border)", color: "var(--muted)" }}
      >
        {/* Principle III: visibly AI-generated, with what produced it and what
            it cost. `is_fixture` is called out because canned content mistaken
            for a real analysis would mean acting on a score nothing produced. */}
        Scored by AI · {analysis.model ?? "unknown model"} · ${analysis.cost ?? "0"} ·{" "}
        {analysis.criteria_version}
        {analysis.is_fixture && " · FIXTURE DATA — not a real analysis"}
      </p>
    </div>
  );
}
