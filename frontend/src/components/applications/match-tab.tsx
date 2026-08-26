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

import { useEffect, useRef, useState } from "react";

import {
  VERDICT_GLYPH,
  type MatchBand as Band,
  type Verdict,
  bandLabel,
} from "@/components/applications/match-score";
import {
  type MatchAnalysis,
  type MatchRequirement,
  type MatchResult,
  type MatchState,
  fetchMatch,
  runMatch,
} from "@/lib/api";

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

/** The order a person reads them in: strongest evidence first. */
const GROUPS: { verdict: Verdict; label: string }[] = [
  { verdict: "confirmed", label: "Directly on your CV" },
  { verdict: "transferable", label: "Related experience" },
  { verdict: "partial", label: "Partly shown" },
  { verdict: "gap", label: "Below what they ask" },
  { verdict: "unverified", label: "Not on your CV" },
];

/**
 * Where the score came from — and it adds up.
 *
 * v2 showed four dimensions the model rated separately from the requirements,
 * so the summary could disagree with the list beneath it, and on a real job it
 * did: every requirement addressed, score 48. This is the same requirements,
 * grouped, showing what each group earned of what it was worth. The total is
 * the score, so the number is checkable rather than asserted (research.md R11).
 */
/**
 * How the requirements fell out, by verdict.
 *
 * **Counts, not the scoring arithmetic.** Earlier versions showed importance
 * points — "360 of 360", then "77 of 77 points" — which is the formula shown as
 * working, and a question almost nobody is asking. What a person wants here is
 * how many of the requirements they meet.
 *
 * The score is still earned from these requirements weighted by importance
 * (research.md R11); that weighting is visible per row below, on the meter
 * beside each one. It simply is not what this summary is for.
 */
function Breakdown({ analysis }: { analysis: MatchAnalysis }) {
  const total = analysis.requirements.length;
  if (total === 0) return null;

  const rows = GROUPS.map(({ verdict, label }) => ({
    label,
    count: analysis.requirements.filter((r) => r.verdict === verdict).length,
  })).filter((row) => row.count > 0);

  return (
    <dl className="mt-5 space-y-2" data-testid="breakdown">
      {rows.map(({ label, count }) => (
        <div key={label} className="flex items-baseline gap-3 text-sm">
          <dt className="w-52 shrink-0 whitespace-nowrap">{label}</dt>
          <dd className="flex min-w-0 flex-1 items-center gap-3">
            <span
              data-testid="group-count"
              className="tabular w-12 shrink-0 text-xs"
              style={{ fontFamily: "var(--font-mono)", color: "var(--muted)" }}
            >
              {count}/{total}
            </span>
            {/* Every row measured against the same width, so the bars can be
                compared to each other rather than only read individually. */}
            <span
              aria-hidden
              className="h-1.5 w-36 shrink-0 overflow-hidden rounded-full"
              style={{ background: "var(--border)" }}
            >
              <span
                className="block h-full rounded-full"
                style={{
                  width: `${(count / total) * 100}%`,
                  background: "var(--color-brand-500)",
                }}
              />
            </span>
          </dd>
        </div>
      ))}
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
/**
 * The ring before there is a score — a short arc travelling round it.
 *
 * Deliberately the same geometry and position as the finished ring, so the
 * result settles into place rather than replacing a paragraph. A layout that
 * rearranges itself on arrival reads as something having gone wrong.
 */
function PendingRing() {
  return (
    <svg width="84" height="84" viewBox="0 0 84 84" aria-hidden className="shrink-0">
      <circle cx="42" cy="42" r={RADIUS} fill="none" strokeWidth="4" stroke="var(--border)" />
      <circle
        data-testid="pending-arc"
        className="score-pending"
        cx="42"
        cy="42"
        r={RADIUS}
        fill="none"
        strokeWidth="4"
        strokeLinecap="round"
        stroke="var(--color-brand-500)"
        // A quarter turn of arc: enough to read as motion, short enough that a
        // still frame is plainly a placeholder rather than a low score.
        strokeDasharray={`${CIRCUMFERENCE / 4} ${CIRCUMFERENCE}`}
      />
    </svg>
  );
}

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
        style={{ fontFamily: "var(--font-display)", fontSize: "22px", fill: "var(--foreground)" }}
      >
        {score}
      </text>
    </svg>
  );
}

const SUPPORTED: Verdict[] = ["confirmed", "partial", "transferable"];

//: Scoring is the only state that is still moving. Everything else is an
//: answer, and asking again would be asking a question already settled.
const IN_FLIGHT: MatchState = "running";

//: Matches the Tailor tab. Short enough that a 27-second run does not feel
//: stalled, long enough that a tab left open is not a request every second.
const POLL_MS = 2_000;

export function MatchTab({
  state: initialState,
  analysis: initialAnalysis,
  stale: initialStale,
  applicationId,
  canScore = false,
}: {
  state: MatchState;
  analysis: MatchAnalysis | null;
  stale: boolean;
  applicationId?: string;
  /** The job has requirements, so an analysis would have something to work
   *  from — true of a record repaired by fetching its posting, which otherwise
   *  reads "nothing to score against" forever because scoring fires on create. */
  canScore?: boolean;
}) {
  /**
   * The page renders this once, server-side, and scoring outlives that request.
   *
   * A real run sat reading "Scoring" for over twenty minutes while the analysis
   * had been `ready` for nineteen of them: `/match` was fetched in the same
   * second the completion started and never again. So the props are a starting
   * point, not the truth, and this component keeps its own.
   */
  const [live, setLive] = useState<MatchResult>({
    state: initialState,
    analysis: initialAnalysis,
    stale: initialStale,
  });
  // The render below reads these names, unchanged.
  const { state, analysis, stale } = live;
  const [running, setRunning] = useState(false);

  // Guards every `setState` after an await, so a tab closed mid-poll does not
  // set state on an unmounted component.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // **Keyed on the state, so the transition itself tears the interval down.**
  // A check inside the callback would depend on a value the closure captured
  // when it was created, and would keep polling a finished analysis forever.
  useEffect(() => {
    if (!applicationId || state !== IN_FLIGHT) return;
    const timer = setInterval(() => {
      fetchMatch(applicationId)
        .then((next) => {
          if (mounted.current) setLive(next);
        })
        // A dropped request must not strand the screen; the next tick asks
        // again, and the run is unaffected either way.
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [applicationId, state]);

  async function score() {
    if (!applicationId) return;
    setRunning(true);
    await runMatch(applicationId).catch(() => undefined);
    // Moved locally rather than from the response: `POST /match` answers
    // `{state, analysis}` and carries no `stale`, so adopting it wholesale
    // would quietly drop a flag the interface renders. The poll this starts
    // fetches the whole truth a moment later — and it runs even when the POST
    // was refused with a 409, which means a run was already going and is
    // exactly the case that most needs watching.
    if (mounted.current) setLive((current) => ({ ...current, state: IN_FLIGHT }));
    setRunning(false);
  }

  // Checked before the null guard below: a run in flight has a pending row,
  // but a null analysis with `running` state must still read as running
  // rather than falling through to "nothing to score against", which would
  // tell a person the opposite of what is happening.
  if (state === "running") {
    return (
      <div role="status" aria-busy="true" className="flex items-center gap-5 py-6">
        <PendingRing />
        <div>
          <p className="text-3xl leading-none" style={{ fontFamily: "var(--font-display)", color: "var(--muted)" }}>
            Scoring
          </p>
          <p className="mt-1.5 text-sm" style={{ color: "var(--muted)" }}>
            Scoring this job against your profile — this takes a few seconds.
          </p>
        </div>
      </div>
    );
  }

  if (state === "nothing_to_score" || analysis === null) {
    return (
      <div className="py-8">
        {/* **Two different situations, and they need different sentences.**
            A job with content that has simply not been scored yet offers the
            action. A job with no posting content cannot be scored at all, and
            offering the action there spends a completion on an empty posting —
            which is what produced a `0/100 · low_probability` that read as a
            judgement about the person rather than a missing field. */}
        <p
          data-testid={canScore ? undefined : "needs-posting"}
          className="max-w-prose text-sm"
          style={{ color: "var(--muted)" }}
        >
          {canScore
            ? "This job has requirements but has not been scored yet."
            : "Add the posting to score this job. Paste the job description or its requirements into this application, and it will be scored against your profile."}
        </p>
        {canScore && applicationId && (
          <button
            type="button"
            disabled={running}
            onClick={score}
            className="mt-2 text-sm underline underline-offset-4 disabled:opacity-50"
          >
            {running ? "Scoring…" : "Score this job"}
          </button>
        )}
      </div>
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


  const supported = analysis.requirements.filter((r) => SUPPORTED.includes(r.verdict));
  //: What the posting asks for and the profile plainly shows. Kept apart from
  //: `supported` because the difference between "you have this" and "this
  //: transfers" is the whole point of the taxonomy, and flattening it in the
  //: summary undoes every per-row distinction below.
  const direct = analysis.requirements.filter((r) => r.verdict === "confirmed");
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
            style={{ fontFamily: "var(--font-display)", color: "var(--foreground)" }}
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
            {/* Only `confirmed` counts here.
                Adding `partial` and `transferable` in reported "8/8 shown on
                your profile" for a profile with two direct matches — which
                reads as a perfect fit and then contradicts itself with a low
                score. It is also the error FR-011b names: presenting
                transferable experience as direct experience, in the one line
                most likely to be read. */}
            <span data-testid="coverage">
              {analysis.overall_score !== null && " · "}
              <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
                {direct.length} of {analysis.requirements.length}
              </span>{" "}
              requirements directly on your CV
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
              onClick={score}
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
