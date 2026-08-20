/**
 * The match band, and the four states it can be in.
 *
 * **Shows a band, never a bare percentage** (FR-001a). An "84%" claims a
 * precision this method does not have; the score is retained for sorting and
 * for the calibration docs/07 §3.2 evaluates this capability on, but it is not
 * what a person should read.
 *
 * The four states must not be conflated (FR-022, docs/09 §5). *Nothing to score
 * against* is the one most likely to appear — every application recorded before
 * slice 004 is in it — and it is ordinary, not an error.
 */

export type MatchState = "running" | "ready" | "failed" | "nothing_to_score";
export type MatchBand = "strong" | "moderate" | "stretch" | "low_probability";
export type Verdict = "confirmed" | "partial" | "transferable" | "gap" | "unverified";

export type MatchSummary = {
  state: MatchState;
  band: MatchBand | null;
  overall_score: number | null;
};

/**
 * One glyph per verdict, because the glyph is what survives greyscale and
 * colour blindness (docs/09 §7). Colour alone would make `unverified` and `gap`
 * — the distinction the whole taxonomy exists for — indistinguishable to the
 * person who has to act on it.
 */
export const VERDICT_GLYPH: Record<Verdict, string> = {
  confirmed: "✓",
  partial: "≈",
  transferable: "↗",
  gap: "✕",
  unverified: "?",
};

export const VERDICT_LABEL: Record<Verdict, string> = {
  confirmed: "Confirmed",
  partial: "Partial",
  transferable: "Transferable",
  gap: "Gap",
  unverified: "Not stated",
};

const BAND_LABEL: Record<MatchBand, string> = {
  strong: "Strong",
  moderate: "Moderate",
  stretch: "Stretch",
  low_probability: "Long shot",
};

export function bandLabel(band: MatchBand): string {
  return BAND_LABEL[band];
}

/** Weight, not hue: a strong match reads as present, a long shot as receded. */
const BAND_STYLE: Record<MatchBand, { color: string; fontWeight: number }> = {
  strong: { color: "var(--foreground)", fontWeight: 600 },
  moderate: { color: "var(--foreground)", fontWeight: 500 },
  stretch: { color: "var(--muted)", fontWeight: 500 },
  low_probability: { color: "var(--muted)", fontWeight: 400 },
};

export function MatchCell({ match }: { match: MatchSummary }) {
  if (match.state === "running") {
    return (
      <span className="text-xs" style={{ color: "var(--muted)" }} aria-label="Scoring">
        Scoring…
      </span>
    );
  }

  if (match.state === "failed") {
    // The only state that gets the failure treatment. docs/09 §3 reserves it
    // for things that actually broke.
    return (
      <span
        role="alert"
        className="text-xs"
        style={{ color: "var(--color-failure)" }}
        title="The analysis could not be completed."
      >
        Not scored
      </span>
    );
  }

  if (match.state === "nothing_to_score" || match.band === null) {
    // Muted and ordinary — deliberately not an error, and deliberately not a
    // zero. A job with no posting has nothing to score against, which is a
    // different fact from scoring badly.
    return (
      <span
        className="text-xs"
        style={{ color: "var(--muted)" }}
        title="No job posting saved for this job yet."
      >
        —
      </span>
    );
  }

  return (
    <span className="text-xs" style={BAND_STYLE[match.band]}>
      {bandLabel(match.band)}
    </span>
  );
}
