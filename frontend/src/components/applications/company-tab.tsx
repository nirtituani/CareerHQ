"use client";

/**
 * Company research for one application (slice 010).
 *
 * The tab owns the lifecycle — fetch, poll while running, start/refresh — and
 * **dispatches rendering on the response's `shape` field, never by sniffing
 * the payload** (api-research.md): `sections` is the slice 010 view,
 * `tiered` covers both 008-era snapshots and fallback runs, rendered by the
 * verbatim-extracted legacy view so history keeps its evidence affordances
 * (FR-014).
 *
 * **It polls only while a run is in flight**, keyed on the application id and
 * the status, like the Tailor tab and for the same reasons: a run outlives
 * its request, and a stale closure would poll a finished run forever.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ResearchLegacy } from "@/components/applications/research-legacy";
import { ResearchSections } from "@/components/applications/research-sections";
import { type ResearchState, getResearch, startResearch } from "@/lib/api";

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function CompanyTab({ applicationId }: { applicationId: string }) {
  const [research, setResearch] = useState<ResearchState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Guards every `setState` after an await. Without it, switching applications
  // mid-request lands the previous job's research on the new job's tab.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    const next = await getResearch(applicationId);
    if (live.current) setResearch(next);
    return next;
  }, [applicationId]);

  useEffect(() => {
    setLoading(true);
    load()
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : String(cause)))
      .finally(() => {
        if (live.current) setLoading(false);
      });
  }, [load]);

  // Poll only while a run is actually in flight. Keyed on the status as well
  // as the id so the transition itself tears the interval down.
  const status = research?.status;
  useEffect(() => {
    if (status !== "running") return;
    const timer = setInterval(() => {
      getResearch(applicationId)
        .then((next) => {
          if (live.current) setResearch(next);
        })
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [applicationId, status]);

  const run = async () => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const started = await startResearch(applicationId);
      // A reuse is an answer, not a run — say so, or the button reads as
      // broken (review fix). It re-runs by itself when the posting changes.
      if (started.reused && live.current) {
        setNotice(
          "This research is up to date and was reused. It re-runs automatically when the job posting changes, or once it is more than 30 days old.",
        );
      }
      await load();
    } catch (cause: unknown) {
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (live.current) setBusy(false);
    }
  };

  if (loading) {
    return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  }

  if (!research || research.status === "none") {
    return (
      <div className="p-4">
        <p className="text-muted-foreground mb-3 text-sm">
          No research yet for this application. CareerHQ will identify the company from your job
          posting and prepare you for the interview — what they do, what matters for this role, and
          what to ask.
        </p>
        <Button onClick={run} disabled={busy}>
          {busy ? "Starting…" : "Research this company"}
        </Button>
        {error && <p className="text-destructive mt-3 text-sm">{error}</p>}
      </div>
    );
  }

  const payload = research;
  const failed = payload.status === "failed";
  const running = payload.status === "running";

  return (
    <div className="p-4">
      <header className="mb-4">
        <p className="text-muted-foreground text-xs">
          {running ? "Researching…" : `Research from ${formatDate(payload.retrieved_at)}`}
        </p>
      </header>

      {payload.last_failure && (
        // A newer failed refresh riding along the current research: the
        // success stays the body (FR-016), the failure stays visible (US3) —
        // both, or one of them is being hidden (review fix).
        <div className="border-destructive/40 mb-4 rounded border p-3">
          <p className="text-destructive text-sm">
            The latest refresh did not finish ({payload.last_failure.failure_reason ?? "unknown"}
            ) — showing the previous research below. You can try again.
          </p>
        </div>
      )}

      {failed && (
        <div className="border-destructive/40 mb-4 rounded border p-3">
          <p className="text-destructive text-sm">
            This research run did not finish ({payload.failure_reason ?? "unknown"}). Nothing was
            saved from it; any earlier research for this application is still shown when it exists.
            You can try again.
          </p>
        </div>
      )}

      {running && (
        <p className="text-muted-foreground mb-4 text-sm">
          Identifying the company and reading about it. This usually takes under a minute.
        </p>
      )}

      {!running &&
        !failed &&
        (payload.shape === "sections" ? (
          <ResearchSections research={payload} />
        ) : (
          <ResearchLegacy research={payload} />
        ))}

      <div className="mt-6">
        <Button onClick={run} disabled={busy || running} variant="outline">
          {busy ? "Starting…" : "Refresh research"}
        </Button>
        {notice && <p className="text-muted-foreground mt-3 text-sm">{notice}</p>}
        {error && <p className="text-destructive mt-3 text-sm">{error}</p>}
      </div>
    </div>
  );
}
