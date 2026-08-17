import type { NormalizedStatus } from "@/lib/api";

/**
 * The status pill — docs/09 §6.2.
 *
 * **It shows the user's own label**, never the normalized category. The label
 * is what they call it; the category is what the system counts, and replacing
 * one with the other would throw away the words the person chose.
 *
 * Outcome colours are deliberately low-drama (docs/09 §3): they appear ~96
 * times on one screen, and the closed end — rejected, ghosted, withdrawn — is
 * **neutral grey, not red**. A rejected application is among the commonest
 * outcomes of a job search, not an error. Red is reserved for things that
 * actually broke.
 */
const OUTCOME: Record<NormalizedStatus, string> = {
  wishlist: "var(--color-outcome-wishlist)",
  applied: "var(--color-outcome-applied)",
  interviewing: "var(--color-outcome-interviewing)",
  offer: "var(--color-outcome-offer)",
  rejected: "var(--color-outcome-closed)",
  withdrawn: "var(--color-outcome-closed)",
  ghosted: "var(--color-outcome-closed)",
  other: "var(--color-outcome-other)",
};

/**
 * The category is **not** printed beside the label.
 *
 * It was, briefly, on the reasoning that the normalized value must not be
 * carried by colour alone (docs/09 §7). In practice every Pre-Applied row read
 * "Pre-Applied WISHLIST" — the same word twice, on every row, saying nothing
 * the label had not already said. A marker that appears everywhere is
 * decoration, which is the failure §5 warns about for the provenance labels and
 * is just as true here.
 *
 * docs/09 §6.2 does describe a marker, but for a narrower case: where the
 * category genuinely **disagrees** with the label — an imported row whose
 * `rejected` flag was true while its status still said "Interview Round 2".
 * That cannot happen yet: manual entry derives the category *from* the label,
 * so the two agree by construction. It becomes possible with the JobTracker
 * import (User Story 3), and when it does the marker should be driven by a flag
 * the backend sets when it overrode the derivation — not by the frontend
 * re-deriving the vocabulary, which would be a second copy of it to drift.
 *
 * The accessible name carries the category meanwhile, so it is available to a
 * screen reader without occupying the row.
 */
export function StatusPill({
  status,
  normalized,
}: {
  status: string;
  normalized: NormalizedStatus;
}) {
  const colour = OUTCOME[normalized] ?? OUTCOME.other;

  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap"
      style={{ color: colour, background: "color-mix(in oklch, currentColor 10%, transparent)" }}
      title={`Counted as ${normalized}`}
    >
      <span aria-hidden className="size-1.5 shrink-0 rounded-full" style={{ background: colour }} />
      {status}
    </span>
  );
}
