"use client";

/**
 * The sections-first research view (slice 010, decision 3B).
 *
 * **This reads as interview preparation, not as an audit log.** The
 * fact/interpretation/inference taxonomy was internal validation vocabulary
 * that leaked into the product; here it is gone from the surface entirely
 * (SC-008 asserts its absence) and provenance travels two quieter ways
 * instead: every section stands over a visible sources list, and a source
 * whose passage was verified verbatim shows that quote — provider sources
 * carry none and render as plain attribution, because a verification nobody
 * performed must not be implied (FR-010).
 *
 * **The entity identification leads** (FR-007). The POC's failure mode was
 * research about three same-named companies with nothing admitting it, so
 * which company this is — and how it was told apart — is the first thing a
 * reader sees, and their tripwire if it is ever wrong.
 */

import type { ResearchPayload, SectionsResearch } from "@/lib/api";

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

function Prose({ label, text }: { label: string; text: string }) {
  return (
    <section className="mb-5">
      <h3 className="text-foreground mb-1 text-sm font-semibold">{label}</h3>
      <p className="text-foreground/90 text-sm whitespace-pre-line">{text}</p>
    </section>
  );
}

function Items({ label, items }: { label: string; items: string[] }) {
  return (
    <section className="mb-5">
      <h3 className="text-foreground mb-1 text-sm font-semibold">{label}</h3>
      <ul className="list-disc space-y-1 pl-5">
        {items.map((item, index) => (
          <li key={index} className="text-foreground/90 text-sm">
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ResearchSections({ research }: { research: ResearchPayload }) {
  const data = research.research as SectionsResearch;
  const identification = data.company_identification;

  return (
    <div>
      {/* Which company this is, and how we know — the wrong-entity tripwire. */}
      <section className="border-border/60 bg-muted/30 mb-5 rounded border p-3">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="text-foreground text-sm font-semibold">
            {identification.official_name}
          </span>
          <a
            href={identification.website}
            target="_blank"
            rel="noreferrer noopener"
            className="text-muted-foreground text-xs underline underline-offset-2"
          >
            {identification.website}
          </a>
          {identification.headquarters && (
            <span className="text-muted-foreground text-xs">{identification.headquarters}</span>
          )}
        </div>
        <p className="text-muted-foreground mt-1 text-xs">
          Identified by: {identification.how_identified}
        </p>
      </section>

      {research.freshness === "aging" && (
        <p className="text-muted-foreground mb-4 text-xs">
          <span className="rounded bg-slate-500/10 px-1.5 py-0.5">Ageing research</span> — gathered{" "}
          {formatDate(research.retrieved_at)}.
        </p>
      )}
      {research.freshness === "stale" && (
        <p className="mb-4 text-xs text-amber-700 dark:text-amber-400">
          <span className="rounded bg-amber-500/10 px-1.5 py-0.5">Older research</span> — gathered{" "}
          {formatDate(research.retrieved_at)}. Consider a refresh before the interview; anything
          that moves quickly may have moved.
        </p>
      )}

      <Prose label="Company overview" text={data.company_overview} />
      <Prose label="Products & services" text={data.products_and_services} />
      <Prose label="Business & market" text={data.business_and_market} />
      {/* When no posting existed, this section explains itself — the provider
          is required to say so rather than invent a role (FR-011), and the
          view must not dress that up. */}
      <Prose label="Relevant to your role" text={data.relevant_to_your_role} />
      <Items label="What to know before the interview" items={data.what_to_know_before_the_interview} />
      <Items label="Questions worth asking" items={data.questions_worth_asking} />

      <section className="border-border/60 mt-6 border-t pt-4">
        <h3 className="text-foreground mb-2 text-sm font-semibold">Sources</h3>
        <ul className="space-y-2">
          {research.sources.map((source) => (
            <li key={source.source_id} className="text-muted-foreground text-xs">
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
                <span>
                  {source.url} — could not be read ({source.fetch_status})
                </span>
              )}
              {/* A quote appears ONLY where the producing path verified one
                  verbatim against a page it fetched (FR-010). Provider sources
                  have none, and none is implied. */}
              {source.excerpt && (
                <blockquote className="border-border/70 mt-1 border-l-2 pl-2 italic">
                  &ldquo;{source.excerpt}&rdquo;
                </blockquote>
              )}
            </li>
          ))}
        </ul>
        <p className="text-muted-foreground mt-2 text-xs">
          {research.produced_by === "builtin"
            ? "Produced by CareerHQ's built-in pipeline (the research provider was unavailable)."
            : "Compiled by the research provider from the sources above."}
        </p>
      </section>
    </div>
  );
}
