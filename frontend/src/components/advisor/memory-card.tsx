"use client";

/**
 * One career memory: the claim, its priority (with the stated reason —
 * FR-022 requires the reasoning shown, not just a number), the frozen
 * evidence with denominators, lifecycle badges, and the dismiss action.
 *
 * The dismiss button lives on the card itself, not behind a second render
 * path — a second render path costs an affordance every time (testing
 * philosophy §9).
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

  return (
    <article
      data-testid={`memory-${memory.id}`}
      className="rounded-lg border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium leading-snug">{memory.claim}</p>
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

      <p className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
        {memory.kind.replaceAll("_", " ")}
        {memory.scope.value ? ` · ${memory.scope.kind}: ${memory.scope.value}` : ""}
        {" · as of "}
        {formatDate(memory.evidence.as_of)}
        {" · last confirmed "}
        {formatDate(memory.last_confirmed_at)}
      </p>

      {memory.priority !== null ? (
        <p className="mt-2 text-xs" data-testid="priority">
          <span className="font-medium">Priority {memory.priority}</span>
          {memory.priority_reason ? (
            <span style={{ color: "var(--muted)" }}> — {memory.priority_reason}</span>
          ) : null}
        </p>
      ) : null}

      <ul className="mt-2 space-y-1" data-testid="evidence">
        {memory.evidence.facts.map((fact) => (
          <li key={fact.fact_id} className="text-xs" style={{ color: "var(--muted)" }}>
            {fact.value}{" "}
            <span style={{ color: "var(--faint)" }}>
              ({fact.numerator}/{fact.denominator})
            </span>
          </li>
        ))}
      </ul>

      {memory.evidence.groupings.length > 0 ? (
        <p className="mt-1 text-xs" style={{ color: "var(--faint)" }} data-testid="groupings">
          {memory.evidence.groupings
            .map((g) => `read as ${g.label}: ${g.member_ids.length} requirement${g.member_ids.length === 1 ? "" : "s"}`)
            .join(" · ")}
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
        <ol className="mt-3 space-y-2 border-l pl-3" style={{ borderColor: "var(--border)" }} data-testid="lineage">
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
