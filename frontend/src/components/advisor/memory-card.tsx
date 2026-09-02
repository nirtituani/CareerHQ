"use client";

/**
 * The expanded detail behind a topic chip (Advisor V2).
 *
 * V1 rendered the LLM's claim, then the raw fact sentences, then the priority
 * reason — the same statistic three times, in three voices. V2 states the
 * numbers **once** (in the chip's headline, above this) and uses the space for
 * what the user could not see before:
 *
 *   What the roles ask   the verbatim requirement rows, with verdict and cause
 *   Your evidence        the profile lines the match analysis quoted
 *   Assessment           one deterministic, number-free sentence
 *   Recommended action   one typed next step (rendered by the chip)
 *
 * Nothing was removed for brevity's sake: the claim still exists on the
 * memory and is what the lineage view compares, and the grouping is shown as
 * a fallback wherever the rows themselves cannot be resolved.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { type CareerMemory, type MemoryDetail, getMemory } from "@/lib/api";

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

const ACTION_LABEL: Record<string, string> = {
  created: "New",
  confirmed: "Confirmed",
  superseded: "Superseded",
  retired: "Retired",
  left_open: "Left open",
};

/** How each verdict reads at a glance — met and unmet asks must be
 *  distinguishable without reading the words. */
const VERDICT_MARK: Record<string, { mark: string; tone: string; label: string }> = {
  confirmed: { mark: "✓", tone: "var(--color-outcome-offer)", label: "met" },
  partial: { mark: "◐", tone: "var(--color-attention)", label: "partly met" },
  transferable: { mark: "◐", tone: "var(--color-attention)", label: "adjacent" },
  gap: { mark: "✕", tone: "var(--color-failure)", label: "gap" },
  unverified: { mark: "?", tone: "var(--faint)", label: "profile silent" },
};

export function MemoryCard({
  memory,
  latestRunId,
  onDismiss,
}: {
  memory: CareerMemory;
  latestRunId: string | null;
  onDismiss: (memoryId: string) => Promise<void>;
}) {
  const [detail, setDetail] = useState<MemoryDetail | null>(null);
  const [lineageOpen, setLineageOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const sinceLastRun =
    memory.last_disposition && memory.last_disposition.run_id === latestRunId
      ? ACTION_LABEL[memory.last_disposition.action]
      : null;

  const toggleLineage = async () => {
    if (!lineageOpen && detail === null) {
      setDetail(await getMemory(memory.id));
    }
    setLineageOpen((open) => !open);
  };

  const specifics = memory.specifics ?? [];
  const quotes = memory.profile_quotes ?? [];
  const groupings = memory.evidence?.groupings ?? [];

  return (
    <article
      data-testid={`memory-${memory.id}`}
      className="rounded-lg border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs" style={{ color: "var(--muted)" }}>
          {memory.kind.replaceAll("_", " ")}
          {memory.scope.value ? ` · ${memory.scope.kind}: ${memory.scope.value}` : ""}
          {" · as of "}
          {formatDate(memory.evidence.as_of)}
        </p>
        <div className="flex shrink-0 items-center gap-1.5">
          {sinceLastRun ? (
            <span
              data-testid="since-last-run"
              className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
              style={{ background: "var(--surface-sunken)", color: "var(--muted)" }}
            >
              {sinceLastRun}
            </span>
          ) : null}
          {memory.status === "tentative" ? (
            <span
              data-testid="tentative-badge"
              className="rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide"
              style={{ background: "var(--surface-sunken)", color: "var(--color-attention)" }}
              title="Based on a small sample — it firms up as evidence accumulates"
            >
              Tentative
            </span>
          ) : null}
        </div>
      </div>

      {specifics.length > 0 ? (
        <section className="mt-3" data-testid="what-roles-ask">
          <h3
            className="text-[10px] font-medium uppercase tracking-wide"
            style={{ color: "var(--muted)" }}
          >
            What the roles ask
          </h3>
          <ul className="mt-1.5 space-y-1">
            {specifics.map((item) => {
              const verdict = VERDICT_MARK[item.verdict] ?? VERDICT_MARK.unverified;
              return (
                <li key={item.requirement_id} className="flex gap-2 text-xs">
                  <span aria-hidden style={{ color: verdict.tone }}>
                    {verdict.mark}
                  </span>
                  <span className="flex-1">
                    <span>{item.text}</span>{" "}
                    <span style={{ color: "var(--faint)" }}>
                      ({verdict.label}
                      {item.shortfall ? ` · ${item.shortfall}` : ""})
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}

      {memory.specifics_unresolved > 0 ? (
        <p className="mt-2 text-xs" style={{ color: "var(--faint)" }} data-testid="unresolved">
          {memory.specifics_unresolved} of the requirements behind this claim are no longer
          available to read.
        </p>
      ) : null}

      {/* Grouping stays visible only where the rows themselves cannot be
          shown — otherwise the rows above are the better audit trail. */}
      {specifics.length === 0 && groupings.length > 0 ? (
        <p className="mt-2 text-xs" style={{ color: "var(--faint)" }} data-testid="groupings">
          {groupings
            .map(
              (g) =>
                `read as ${g.label}: ${g.member_ids.length} requirement${
                  g.member_ids.length === 1 ? "" : "s"
                }`,
            )
            .join(" · ")}
        </p>
      ) : null}

      {quotes.length > 0 ? (
        <section className="mt-3" data-testid="your-evidence">
          <h3
            className="text-[10px] font-medium uppercase tracking-wide"
            style={{ color: "var(--muted)" }}
          >
            Your evidence
          </h3>
          <ul className="mt-1.5 space-y-1">
            {quotes.map((quote) => (
              <li key={quote} className="text-xs" style={{ color: "var(--muted)" }}>
                &ldquo;{quote}&rdquo;
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {memory.assessment ? (
        <section className="mt-3" data-testid="assessment">
          <h3
            className="text-[10px] font-medium uppercase tracking-wide"
            style={{ color: "var(--muted)" }}
          >
            Assessment
          </h3>
          <p className="mt-1 text-xs">{memory.assessment}</p>
        </section>
      ) : null}
      {/* **Its own block, not nested inside the assessment.** `assess()` returns
          null for every portfolio and data-note memory, so nesting it here hid
          FR-022's reasoning entirely for that whole class — an expanded portfolio
          card showed a kind/scope line and a Dismiss button and nothing else. The
          reason the advisor gave for a priority is required wherever there is
          one, whether or not the rows also support an assessment. */}
      {memory.priority_reason ? (
        <p className="mt-3 text-xs" style={{ color: "var(--muted)" }} data-testid="priority">
          {memory.priority_reason}
        </p>
      ) : null}

      {memory.recreates_dismissed_id ? (
        <p className="mt-2 text-xs" style={{ color: "var(--muted)" }} data-testid="recreated-note">
          You dismissed an earlier version of this claim; the evidence has since changed.
        </p>
      ) : null}

      <div className="mt-3 flex items-center gap-2">
        {memory.supersedes_id ? (
          <Button variant="ghost" size="sm" onClick={toggleLineage}>
            {lineageOpen ? "Hide history" : "How this evolved"}
          </Button>
        ) : null}
        <Button
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await onDismiss(memory.id);
            } finally {
              setBusy(false);
            }
          }}
        >
          Dismiss
        </Button>
      </div>

      {lineageOpen && detail ? (
        <ol
          className="mt-3 space-y-2 border-l pl-3"
          style={{ borderColor: "var(--border)" }}
          data-testid="lineage"
        >
          {detail.lineage.map((predecessor) => (
            <li key={predecessor.id} className="text-xs" style={{ color: "var(--muted)" }}>
              <span className="font-medium">{formatDate(predecessor.created_at)}:</span>{" "}
              {predecessor.claim}
              {predecessor.retired_reason ? ` (${predecessor.retired_reason})` : ""}
            </li>
          ))}
        </ol>
      ) : null}
    </article>
  );
}
