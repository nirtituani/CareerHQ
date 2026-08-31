"use client";

/**
 * The Career Advisor page's client half (US1/US2/US4).
 *
 * Owns the lifecycle: load the memory state, start a run, poll it while
 * pending (keyed on the run id and status, so the transition tears the
 * interval down), reload the page state when the run lands, dismiss a
 * memory. A failed run keeps serving the previous memories — the failure is
 * announced beside them, never instead of them.
 *
 * Honesty states are first-class: the empty state names what the advisor
 * needs, and the coverage line renders the insufficient-data answer for
 * skill-level patterns from the server's own denominators (FR-011).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { MemoryCard } from "@/components/advisor/memory-card";
import {
  type AdvisorRun,
  type AdvisorState,
  dismissMemory,
  getAdvisor,
  getAdvisorRun,
  startAdvisorRun,
} from "@/lib/api";

export function AdvisorView() {
  const [state, setState] = useState<AdvisorState | null>(null);
  const [loading, setLoading] = useState(true);
  const [run, setRun] = useState<AdvisorRun | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    const next = await getAdvisor();
    if (live.current) {
      setState(next);
      setRun(next.latest_run);
    }
    return next;
  }, []);

  useEffect(() => {
    load()
      .catch((cause: unknown) => {
        if (live.current) {
          setError(cause instanceof Error ? cause.message : String(cause));
        }
      })
      .finally(() => {
        if (live.current) setLoading(false);
      });
  }, [load]);

  // Poll only while a run is in flight; the status key tears this down the
  // moment it lands, and landing reloads the whole page state.
  const runId = run?.id ?? null;
  const runStatus = run?.status ?? null;
  useEffect(() => {
    if (runId === null || runStatus !== "pending") return;
    const timer = setInterval(() => {
      getAdvisorRun(runId)
        .then((next) => {
          if (!live.current) return;
          setRun(next);
          if (next.status !== "pending") void load().catch(() => undefined);
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [runId, runStatus, load]);

  const analyze = async () => {
    setBusy(true);
    setError(null);
    try {
      const started = await startAdvisorRun();
      if (live.current) setRun(started.run);
    } catch (cause) {
      if (live.current) {
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      if (live.current) setBusy(false);
    }
  };

  const onDismiss = async (memoryId: string) => {
    await dismissMemory(memoryId);
    await load().catch(() => undefined);
  };

  if (loading) return <p className="text-sm">Loading…</p>;

  if (state === null) {
    return (
      <p className="text-sm" role="alert">
        The advisor could not be loaded{error ? `: ${error}` : "."}
      </p>
    );
  }

  const { memories, coverage, history_counts } = state;
  const running = run?.status === "pending";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Career Advisor</h1>
          <p className="text-xs" style={{ color: "var(--muted)" }} data-testid="coverage">
            {coverage.analysed} of {coverage.applications} applications have a match analysis.{" "}
            {coverage.message}
          </p>
        </div>
        <Button onClick={analyze} disabled={busy || running} data-testid="analyze">
          {running ? "Analyzing…" : "Analyze my history"}
        </Button>
      </div>

      {run?.status === "failed" ? (
        <p className="text-sm" role="alert" data-testid="run-failed">
          The last analysis failed: {run.error ?? "unknown kind of failure"}. Your previous
          memories are unchanged below.
        </p>
      ) : null}

      {run?.status === "ready" && run.ops ? (
        <p className="text-xs" style={{ color: "var(--muted)" }} data-testid="run-summary">
          Last analysis: {run.ops.applied} kept, {run.ops.discarded} discarded of{" "}
          {run.ops.proposed} proposed
          {run.cost ? ` · $${run.cost}` : ""}
        </p>
      ) : null}

      {memories.length === 0 && !running ? (
        <div className="rounded-lg border p-6 text-sm" style={{ borderColor: "var(--border)" }} data-testid="empty-state">
          {coverage.applications === 0 ? (
            <>
              <p className="font-medium">Nothing to analyse yet.</p>
              <p className="mt-1" style={{ color: "var(--muted)" }}>
                The advisor reasons over your application history. Add applications — or import
                your JobTracker history — and come back.
              </p>
            </>
          ) : (
            <>
              <p className="font-medium">No memories yet.</p>
              <p className="mt-1" style={{ color: "var(--muted)" }}>
                Run an analysis and the advisor will record what your {coverage.applications}{" "}
                applications support — with the evidence beside every claim.
              </p>
            </>
          )}
        </div>
      ) : null}

      <div className="space-y-3">
        {memories.map((memory) => (
          <MemoryCard
            key={memory.id}
            memory={memory}
            latestRunId={run?.status === "ready" ? run.id : null}
            onDismiss={onDismiss}
          />
        ))}
      </div>

      {history_counts.superseded + history_counts.retired > 0 ? (
        <p className="text-xs" style={{ color: "var(--faint)" }} data-testid="history-counts">
          History: {history_counts.superseded} superseded · {history_counts.retired} retired —
          open a memory's history to read how understanding evolved.
        </p>
      ) : null}
    </div>
  );
}
