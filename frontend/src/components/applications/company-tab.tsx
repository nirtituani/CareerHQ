"use client";

/**
 * Company research: what this employer does, and what backs every sentence.
 *
 * **Every claim is shown with its evidence, and that is the feature rather than
 * a flourish.** The research is assembled from pages a model read; a brief the
 * reader cannot check is worth less than none, because it reads exactly like one
 * they could. So each factual claim carries the quoted passage and a link to the
 * page it came from, and the three tiers are visually distinct.
 *
 * **The tiers are the honesty mechanism** (FR-028). `fact` means a source states
 * it and the quotation was verified verbatim against the page CareerHQ fetched
 * itself. `interpretation` means we read it out of stated facts. `inference`
 * means the model reasoned beyond every source, and it is labelled so nobody
 * mistakes it for something a page said. Rendering all three identically would
 * throw away the distinction the whole pipeline exists to preserve.
 *
 * **It fetches its own state and polls only while a run is in flight**, like the
 * Tailor tab and for the same reason: a research run outlives the request that
 * started it, so there is nothing a server render could hand over that would
 * still be true when it was read.
 *
 * **Staleness is a label, never a hiding place** (OQ-E). Research past the
 * display window is marked visibly rather than withheld — three-month-old
 * research is still useful, but it must be visibly three months old rather than
 * silently wrong.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  type CompanyResearch,
  type ResearchClaim,
  type ResearchSection,
  getResearch,
  startResearch,
} from "@/lib/api";

/** The five fixed sections, in the order a reader wants them (FR-020). */
const SECTIONS: { key: string; label: string }[] = [
  { key: "what_the_company_does", label: "What the company does" },
  { key: "products_and_services", label: "Products and services" },
  { key: "market_and_customers", label: "Market and customers" },
  { key: "practical_facts", label: "Practical facts" },
  { key: "interview_preparation", label: "Interview preparation" },
];

const TIER_STYLE: Record<ResearchClaim["tier"], { label: string; className: string }> = {
  fact: { label: "Fact", className: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" },
  interpretation: {
    label: "Interpretation",
    className: "bg-amber-500/10 text-amber-700 dark:text-amber-400",
  },
  inference: { label: "Inference", className: "bg-slate-500/10 text-slate-600 dark:text-slate-400" },
};

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

function Claim({ claim, urlFor }: { claim: ResearchClaim; urlFor: (id: string) => string | null }) {
  const tier = TIER_STYLE[claim.tier];
  return (
    <li className="border-border/60 border-b py-3 last:border-b-0">
      <div className="flex items-start gap-3">
        <span
          className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-xs font-medium ${tier.className}`}
        >
          {tier.label}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-foreground text-sm">{claim.text}</p>

          {/* The evidence, always visible rather than behind a disclosure. A
              citation nobody opens is a citation nobody checks, and checking is
              the point. */}
          {claim.evidence.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {claim.evidence.map((evidence, index) => {
                const href = urlFor(evidence.source_id);
                return (
                  <li
                    key={`${evidence.source_id}-${index}`}
                    className="border-border/70 text-muted-foreground border-l-2 pl-3 text-xs"
                  >
                    <span className="italic">&ldquo;{evidence.excerpt}&rdquo;</span>{" "}
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="underline underline-offset-2"
                      >
                        [{evidence.source_id}]
                      </a>
                    ) : (
                      <span>[{evidence.source_id}]</span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {/* An interpretation names the facts it rests on. Showing the ids is
              what lets a reader follow the reasoning back to something quoted. */}
          {claim.rests_on.length > 0 && (
            <p className="text-muted-foreground mt-1.5 text-xs">
              Rests on {claim.rests_on.join(", ")}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

function Section({
  label,
  section,
  urlFor,
}: {
  label: string;
  section: ResearchSection | undefined;
  urlFor: (id: string) => string | null;
}) {
  const claims = section?.claims ?? [];
  return (
    <section className="mb-6">
      <h3 className="text-foreground mb-1 text-sm font-semibold">{label}</h3>
      {claims.length > 0 ? (
        <ul>
          {claims.map((claim) => (
            <Claim key={claim.id} claim={claim} urlFor={urlFor} />
          ))}
        </ul>
      ) : (
        // An empty section states why. Silence and absence are different
        // things, and a section that simply vanished would read as "not
        // applicable" when it may mean "we looked and found nothing".
        <p className="text-muted-foreground text-sm">
          {section?.empty_reason ?? "Nothing found for this section."}
        </p>
      )}
    </section>
  );
}

export function CompanyTab({ applicationId }: { applicationId: string }) {
  const [research, setResearch] = useState<CompanyResearch | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Guards every `setState` after an await. Without it, switching applications
  // mid-request lands the previous employer's research on the new job's tab.
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

  // Poll only while a run is actually in flight. Keyed on the status as well as
  // the id so the transition itself tears the interval down — a stale closure
  // would poll a finished run forever.
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
    try {
      await startResearch(applicationId);
      await load();
    } catch (cause: unknown) {
      if (live.current) setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      if (live.current) setBusy(false);
    }
  };

  const urlFor = useCallback(
    (sourceId: string) => research?.sources.find((s) => s.source_id === sourceId)?.url ?? null,
    [research],
  );

  if (loading) {
    return <p className="text-muted-foreground p-4 text-sm">Loading…</p>;
  }

  if (!research) {
    return (
      <div className="p-4">
        <p className="text-muted-foreground mb-3 text-sm">
          No research yet for this company. CareerHQ will search the web, read the pages itself, and
          quote what it finds — every claim carries the passage it came from.
        </p>
        <Button onClick={run} disabled={busy}>
          {busy ? "Starting…" : "Research this company"}
        </Button>
        {error && <p className="text-destructive mt-3 text-sm">{error}</p>}
      </div>
    );
  }

  const failed = research.status === "failed";
  const running = research.status === "running";

  return (
    <div className="p-4">
      <header className="mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-foreground text-base font-semibold">{research.company}</h2>
          {research.freshness === "stale" && (
            <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-xs text-amber-700 dark:text-amber-400">
              Older research
            </span>
          )}
        </div>
        <p className="text-muted-foreground mt-1 text-xs">
          {running ? "Researching…" : `Retrieved ${formatDate(research.retrieved_at)}`}
          {research.freshness === "stale" && !running && " — still useful, but check anything that moves quickly."}
        </p>
      </header>

      {failed && (
        <div className="border-destructive/40 mb-4 rounded border p-3">
          <p className="text-destructive text-sm">
            This research run did not finish. Nothing was saved from it, and any earlier research for
            this company is still shown above.
          </p>
        </div>
      )}

      {running && (
        // A partial arc rather than a full ring: a complete ring resting still
        // reads as a finished run.
        <p className="text-muted-foreground mb-4 text-sm">
          Searching the web and reading pages. This usually takes a minute or two.
        </p>
      )}

      {!running &&
        SECTIONS.map(({ key, label }) => (
          <Section key={key} label={label} section={research.sections[key]} urlFor={urlFor} />
        ))}

      {research.sources.length > 0 && (
        <section className="border-border/60 mt-6 border-t pt-4">
          <h3 className="text-foreground mb-2 text-sm font-semibold">Sources</h3>
          <ul className="space-y-1">
            {research.sources.map((source) => (
              <li key={source.source_id} className="text-muted-foreground text-xs">
                <span className="font-mono">[{source.source_id}]</span>{" "}
                {source.fetch_status === "retrieved" ? (
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="underline underline-offset-2"
                  >
                    {source.title ?? source.url}
                  </a>
                ) : (
                  // A source that could not be read is still listed (FR-009).
                  // How much of the web was consulted is part of what the brief
                  // claims, and hiding the failures overstates it.
                  <span>
                    {source.url} — could not be read ({source.fetch_status})
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="mt-6">
        <Button onClick={run} disabled={busy || running} variant="outline">
          {busy ? "Starting…" : "Refresh research"}
        </Button>
        {error && <p className="text-destructive mt-3 text-sm">{error}</p>}
      </div>
    </div>
  );
}
