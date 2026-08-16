/**
 * Provenance and confidence, per docs/09_Design_Language.md §5.
 *
 * The rules these encode are not decoration:
 *
 * - **Colour is never the only channel.** Provenance is carried by the *line
 *   style* of a left rule — dashed for extracted, solid for affirmed — which
 *   survives greyscale, colour blindness and a bad monitor. The label repeats
 *   it in text.
 * - **Confidence informs, it never decides.** It may change what is suggested,
 *   emphasised or ordered; it never changes what happens. Principle II admits no
 *   threshold, so nothing here returns "should auto-accept".
 */

export type Source = "extracted" | "user_corrected" | "user_added";

const PROVENANCE: Record<Source, { label: string; rule: string; hint: string }> = {
  extracted: {
    label: "EXTRACTED",
    rule: "var(--rule-extracted)",
    hint: "Read from your CV. Not confirmed by you yet.",
  },
  user_corrected: {
    label: "CORRECTED",
    rule: "var(--rule-corrected)",
    hint: "You changed this.",
  },
  user_added: {
    label: "ADDED",
    rule: "var(--rule-added)",
    hint: "You added this.",
  },
};

/** The left rule. Dashed reads as provisional, solid as affirmed. */
export function provenanceStyle(source: Source): React.CSSProperties {
  return { borderLeft: PROVENANCE[source].rule, paddingLeft: "0.75rem" };
}

export function ProvenanceLabel({ source }: { source: Source }) {
  // `extracted` is the default and says nothing worth reading: straight after an
  // import every row carries it, and sixty repetitions of one word is noise
  // competing with the content. The signal is the *exception* — a fact a person
  // corrected or added — so only that is labelled.
  //
  // FR-004 still holds. The distinction survives in the left rule, which is the
  // primary channel by design (docs/09 §5) precisely because it works without
  // reading anything.
  if (source === "extracted") return null;

  const { label, hint } = PROVENANCE[source];
  return (
    <span
      title={hint}
      className="text-[10px] tracking-wider"
      style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
    >
      {label}
    </span>
  );
}

/** Below this, an item is flagged for attention. It is never auto-anything. */
export const LOW_CONFIDENCE = 0.6;

/**
 * A three-segment meter and the value in monospace.
 *
 * Two channels, neither of them colour alone: the number is readable whatever
 * the segments look like.
 */
export function ConfidenceMeter({ value }: { value: number }) {
  const filled = value >= 0.8 ? 3 : value >= LOW_CONFIDENCE ? 2 : 1;
  const low = value < LOW_CONFIDENCE;

  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={low ? "Low confidence — worth checking" : "Confidence"}
      aria-label={`Confidence ${value.toFixed(2)}${low ? ", low" : ""}`}
    >
      <span aria-hidden className="inline-flex gap-0.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="block h-3 w-1 rounded-[1px]"
            style={{
              background:
                i < filled
                  ? low
                    ? "var(--color-attention)"
                    : "var(--color-brand-500)"
                  : "var(--border)",
            }}
          />
        ))}
      </span>
      <span
        className="tabular text-xs"
        style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
      >
        {value.toFixed(2)}
      </span>
    </span>
  );
}
