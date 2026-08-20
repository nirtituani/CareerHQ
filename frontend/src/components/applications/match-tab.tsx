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

/**
 * What each dimension is called on screen, and what it means.
 *
 * Deliberately not the names from the reference this borrows its shape
 * from: those measure a *document* (impact, brevity, style), while these
 * measure a *fit*. The sub-labels matter more than the names — nobody knows
 * what "adjacent" means until they are told.
 */
const DIMENSION: { key: keyof MatchAnalysis["dimensions"]; name: string; means: string }[] = [
  { key: "direct", name: "Direct experience", means: "Same work, same domain" },
  { key: "transferable", name: "Transferable", means: "Same skill, different context" },
  { key: "adjacent", name: "Adjacent", means: "Secondary or related work" },
  { key: "impact", name: "Impact fit", means: "Outcomes this role values" },
];

/**
 * The score, shown as the four judgements it is made of.
 *
 * This is what earns the number. A bare "56%" implies a measurement nobody
 * took — the pseudo-scientific fit percentage one of the rubric sources warns
 * against. The same 56 beside its parts and their weights is arithmetic a
 * person can check against stated judgements, and disagree with.
 *
 * No red-to-green gradient: docs/09 §3 reserves red for things that broke,
 * and warns specifically against someone later reaching for semantic red. A
 * low dimension is not an error.
 */
function Breakdown({ analysis }: { analysis: MatchAnalysis }) {
  const rated = DIMENSION.filter((d) => analysis.dimensions[d.key] !== null);
  // An analysis scored before the parts were kept has a correct total that
  // cannot be explained. Inventing parts that sum to it would fabricate the
  // explanation, so it simply shows no breakdown.
  if (rated.length === 0) return null;

  return (
    <dl className="mt-5 space-y-2" data-testid="breakdown">
      {rated.map(({ key, name, means }) => {
        const value = analysis.dimensions[key] ?? 0;
        const weight = Math.round((analysis.weights[key] ?? 0) * 100);
        return (
          <div key={key} className="flex items-baseline gap-3 text-sm">
            <dt className="w-40 shrink-0">
              {name}
              <span className="ml-1.5 text-xs" style={{ color: "var(--faint)" }}>
                {weight}%
              </span>
            </dt>
            <dd className="flex min-w-0 flex-1 items-center gap-3">
              <span
                aria-hidden
                className="h-1 w-28 shrink-0 overflow-hidden rounded-full"
                style={{ background: "var(--border)" }}
              >
                <span
                  className="block h-full rounded-full"
                  style={{ width: `${value}%`, background: "var(--color-brand-500)" }}
                />
              </span>
              <span
                className="tabular w-8 shrink-0 text-xs"
                style={{ fontFamily: "var(--font-mono)", color: "var(--muted)" }}
              >
                {value}
              </span>
              <span className="truncate text-xs" style={{ color: "var(--faint)" }}>
                {means}
              </span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** r=32, matching the `score-sweep` keyframe in globals.css. */
const RADIUS = 32;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/**
 * The score as a ring, with the figure inside it.
 *
 * The one place a large figure belongs on this screen, so it is set in the
 * serif (docs/09 §2). Brand teal at a single weight rather than a red-to-green
 * sweep: §3 reserves red for things that broke, and a 54 is not a fault.
 *
 * **The finished offset is the element's own style; the keyframe supplies only
 * the start.** The global `prefers-reduced-motion` rule collapses animations to
 * 0.01ms, so the ring snaps to its true value. Had the base style been the
 * empty circle with the animation drawing it in, reduced motion would have
 * left every score reading zero — visible to nobody who tested with motion on.
 */
function ScoreRing({ score, band }: { score: number; band: string }) {
  return (
    <svg
      width="84"
      height="84"
      viewBox="0 0 84 84"
      role="img"
      aria-label={`Match score ${score} out of 100 — ${band}`}
      className="shrink-0"
    >
      <circle
        cx="42"
        cy="42"
        r={RADIUS}
        fill="none"
        strokeWidth="4"
        stroke="var(--border)"
      />
      <circle
        data-testid="score-arc"
        className="score-arc"
        cx="42"
        cy="42"
        r={RADIUS}
        fill="none"
        strokeWidth="4"
        strokeLinecap="round"
        stroke="var(--color-brand-500)"
        style={{
          strokeDasharray: CIRCUMFERENCE,
          strokeDashoffset: CIRCUMFERENCE * (1 - score / 100),
        }}
      />
      <text
        x="42"
        y="42"
        textAnchor="middle"
        dominantBaseline="central"
        style={{ fontFamily: "var(--font-display)", fontSize: "22px", fill: "var(--fg)" }}
      >
        {score}
      </text>
    </svg>
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
      <div className="flex items-center gap-5">
        {analysis.overall_score !== null && (
          <ScoreRing
            score={analysis.overall_score}
            band={analysis.band ? bandLabel(analysis.band as Band) : "unscored"}
          />
        )}

        <div className="min-w-0">
          {/* A large figure, so the serif — docs/09 §2. */}
          <p
            className="text-3xl leading-none"
            style={{ fontFamily: "var(--font-display)", color: "var(--fg)" }}
          >
            {analysis.band ? bandLabel(analysis.band as Band) : "—"}
          </p>
          <p className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>
            {analysis.overall_score !== null && (
              <span
                data-testid="score"
                className="tabular"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {analysis.overall_score}/100
              </span>
            )}
            <span data-testid="coverage">
              {analysis.overall_score !== null && " · "}
              <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
                {supported.length}/{analysis.requirements.length}
              </span>{" "}
              requirements shown on your profile
            </span>
          </p>
        </div>
      </div>

      {/* Without this the label and the number contradict each other: 56 sits
          in Moderate's range while the band reads Stretch. Naming the
          requirement turns an apparent bug into the most actionable line here. */}
      {analysis.capped_by && (
        <p data-testid="cap-reason" className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
          {/* The band is right above; repeating it here would restate the
              screen. Say the part that is new: which requirement, and why. */}
          Capped by “{analysis.capped_by.text}” — critical to this role, and not shown on your
          profile.
        </p>
      )}

      <Breakdown analysis={analysis} />

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
