"use client";

/**
 * The tiered research view — 008-era snapshots and slice 010 fallback runs.
 *
 * **Extracted verbatim from `company-tab.tsx`** (slice 010 T012), because a
 * second render path costs an affordance every time it is rewritten instead
 * of moved (testing rule 9). Nothing here was redesigned: the tiers, the
 * always-visible evidence and the failed-source rows are the honesty
 * mechanisms 008 shipped, and both the legacy history and the fallback path
 * still carry them (FR-014, FR-010).
 */

import type { ResearchClaim, ResearchPayload, ResearchSection, TieredResearch } from "@/lib/api";

/** The five fixed sections, in the order a reader wants them (008 FR-020). */
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
  inference: {
    label: "Inference",
    className: "bg-slate-500/10 text-slate-600 dark:text-slate-400",
  },
};

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

export function ResearchLegacy({ research }: { research: ResearchPayload }) {
  const sections = research.research as TieredResearch;
  const urlFor = (sourceId: string) =>
    research.sources.find((s) => s.source_id === sourceId)?.url ?? null;

  return (
    <div>
      {research.freshness === "aging" && (
        <p className="text-muted-foreground mb-4 text-xs">
          <span className="rounded bg-slate-500/10 px-1.5 py-0.5">Ageing research</span>
        </p>
      )}
      {research.freshness === "stale" && (
        <p className="mb-4 text-xs text-amber-700 dark:text-amber-400">
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5">Older research</span> — still
          useful, but check anything that moves quickly, or refresh.
        </p>
      )}
      {SECTIONS.map(({ key, label }) => (
        <Section key={key} label={label} section={sections[key]} urlFor={urlFor} />
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
          {research.produced_by === "builtin" && (
            <p className="text-muted-foreground mt-2 text-xs">
              Produced by CareerHQ&apos;s built-in pipeline (the research provider was
              unavailable). Quotes above were verified against the pages it read.
            </p>
          )}
        </section>
      )}
    </div>
  );
}
