"use client";

/**
 * A compact, topic-first chip for the first view: a colour dot, the topic, a
 * one-line evidence summary, and the tier label. Clicking it expands to the
 * full existing detail — the deterministic action scaffold (where the tier
 * warrants one) followed by the unchanged `MemoryCard`, so no evidence,
 * lineage, or dismiss affordance is lost. Progressive disclosure, not hiding.
 *
 * Colours map to CareerHQ's declared tokens; no new theme values.
 */

import { useState } from "react";

import { MemoryCard } from "@/components/advisor/memory-card";
import type { CareerMemory } from "@/lib/api";

const TIER_DOT: Record<CareerMemory["tier"], string> = {
  recommendation: "var(--color-failure)",
  strength: "var(--color-outcome-offer)",
  pattern: "var(--color-attention)",
  emerging: "var(--color-attention)",
  observation: "var(--color-attention)",
  portfolio: "var(--faint)",
  data_note: "var(--faint)",
};

const TIER_LABEL: Record<CareerMemory["tier"], string> = {
  recommendation: "High priority",
  strength: "Consistent strength",
  pattern: "Recurring pattern",
  emerging: "Emerging pattern",
  observation: "Early signal",
  portfolio: "",
  data_note: "",
};

/** Prevalence first, then the gap — each figure stated once.
 *  "Required in 4 of 7 · Gap in 2". The gap half is omitted where there is
 *  none, so a strength reads as pure prevalence and its tier label carries
 *  the rest. */
function evidenceLine(memory: CareerMemory): string {
  const c = memory.counts;
  if (c && c.coverage != null && c.occurrences != null) {
    const required = `Required in ${c.occurrences} of ${c.coverage}`;
    return c.gaps ? `${required} · Gap in ${c.gaps}` : required;
  }
  return memory.claim;
}

export function TopicChip({
  memory,
  latestRunId,
  onDismiss,
}: {
  memory: CareerMemory;
  latestRunId: string | null;
  onDismiss: (memoryId: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const label = TIER_LABEL[memory.tier];

  return (
    <div
      data-testid={`chip-${memory.id}`}
      data-tier={memory.tier}
      className="rounded-lg border"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
    >
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
      >
        <span
          aria-hidden
          className="size-2.5 shrink-0 rounded-full"
          style={{ background: TIER_DOT[memory.tier] }}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium">{memory.topic}</span>
          <span className="block truncate text-xs" style={{ color: "var(--muted)" }}>
            {evidenceLine(memory)}
          </span>
          {/* Grounded specifics: shortened **verbatim** requirement text, so
              the card can be specific without inventing a technology name the
              evidence never contained. */}
          {memory.specific_labels && memory.specific_labels.length > 0 ? (
            <span
              className="mt-0.5 block truncate text-xs"
              style={{ color: "var(--faint)" }}
              data-testid="specific-labels"
            >
              {memory.specific_labels.join(" · ")}
            </span>
          ) : null}
        </span>
        {label ? (
          <span className="shrink-0 text-[10px] uppercase tracking-wide" style={{ color: "var(--faint)" }}>
            {label}
          </span>
        ) : null}
        <span aria-hidden className="shrink-0 text-xs" style={{ color: "var(--faint)" }}>
          {open ? "▲" : "▼"}
        </span>
      </button>

      {open ? (
        <div className="border-t px-4 py-3" style={{ borderColor: "var(--border)" }}>
          {memory.action ? (
            <div className="mb-3" data-testid="action" data-category={memory.action.category}>
              <p
                className="text-xs font-medium uppercase tracking-wide"
                style={{ color: "var(--muted)" }}
              >
                Recommended action
              </p>
              <p className="mt-1 text-sm">{memory.action.text}</p>
            </div>
          ) : null}
          <MemoryCard memory={memory} latestRunId={latestRunId} onDismiss={onDismiss} />
        </div>
      ) : null}
    </div>
  );
}
