"use client";

import { Tabs } from "radix-ui";

import { MatchTab } from "@/components/applications/match-tab";
import { TailorTab } from "@/components/applications/tailor-tab";
import { NotBuiltYet } from "@/components/not-built-yet";
import type { Application, MatchResult } from "@/lib/api";

/**
 * The tabbed application detail — docs/09 §6.3.
 *
 * The screen every later slice lands on, so its job is to hold five
 * capabilities without any of them crowding the one the user came for.
 *
 * **Tabs rather than a right rail**, because the job description is long and
 * wants the full column. A rail would permanently squeeze the one piece of
 * content that is always present in order to show four panels that mostly are
 * not.
 *
 * The Requirements tab that used to sit here is gone: what it was going to
 * hold — the requirements pulled out of a posting — is now what the Details tab
 * stores, so an unbuilt tab for it would mark as missing something already on
 * screen.
 *
 * **Unbuilt capabilities are marked in the tab itself** (T072). Without that,
 * the user clicks Company to discover it is not built, then clicks Interview to
 * discover the same. Marking at the navigation level means never clicking into
 * disappointment — §5's *not built yet* state applied one level up. It must
 * never read as **failed** and never as **empty data**; those are three
 * distinct states, and the first must never look like the third.
 */
// The order is the work, in the order it happens: what the job is, whether it
// is worth applying to, and what you sent. Company research and interview
// preparation belong to later stages and follow. A tab order that does not
// follow the work makes a person hunt for the next step.
//
// `arrives` used to sit here too and was never read — `UNBUILT` below supplies
// it. One of its values had also gone stale, still calling tailored versions
// "Slice 004" after match analysis took that number.
const TABS = [
  { value: "details", label: "Details", built: true },
  // Read before any resume work: "is this worth applying to, and where am I
  // weak" is the question that decides whether the rest of the page matters.
  { value: "match", label: "Match", built: true },
  // After Match, because tailoring refuses to run without a completed
  // analysis — the tab order is the order the work actually happens in.
  { value: "tailor", label: "Tailor", built: true },
  { value: "company", label: "Company", built: false },
  { value: "interview", label: "Interview", built: false },
] as const;

/** What each unbuilt panel will hold, in the user's terms rather than ours. */
const UNBUILT: Record<string, { title: string; arrives: string }> = {
  company: {
    title: "Company research",
    arrives: "A research snapshot for this company arrives with the research agent.",
  },
  interview: {
    title: "Interview preparation",
    arrives: "Interview preparation is a future release, not a planned slice.",
  },
};

/**
 * Requirements as a list, one per line — the shape they are stored in.
 *
 * A single block of pre-wrapped text made a scannable list read as a paragraph.
 * Any bullet character the posting already carried is stripped first, so a
 * source that wrote "- 5+ years" does not end up double-bulleted.
 *
 * Falls back to a paragraph for a single line, and for anything with blank
 * lines between blocks — that is prose, and bulleting each of its lines would
 * be worse than leaving it alone. Records saved before requirements extraction
 * existed hold exactly that.
 */
function RequirementList({ text }: { text: string }) {
  const lines = text
    .split("\n")
    .map((line) => line.replace(/^\s*[-•*·—]\s*/, "").trim())
    .filter(Boolean);

  const isProse = lines.length < 2 || /\n\s*\n/.test(text.trim());

  if (isProse) {
    return <p className="whitespace-pre-wrap">{text}</p>;
  }

  return <BulletList items={lines} />;
}

/** One marker, used by both the stored list and the legacy split-by-line path,
 *  so a row recorded before slice 004 and one recorded after look identical. */
function BulletList({ items }: { items: string[] }) {
  return (
    <ul className="space-y-1.5">
      {items.map((item, index) => (
        <li key={index} className="flex gap-2.5">
          <span aria-hidden style={{ color: "var(--color-brand-600)" }}>
            •
          </span>
          <span className="min-w-0 flex-1">{item}</span>
        </li>
      ))}
    </ul>
  );
}

function Field({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide uppercase" style={{ color: "var(--muted)" }}>
        {label}
      </dt>
      {/* "Empty but available" — plain muted text, never the dashed treatment
          and never an error. Nothing is broken; the field is simply unset. */}
      <dd className="mt-1 text-sm" style={value ? undefined : { color: "var(--faint)" }}>
        {value || "Not set"}
      </dd>
    </div>
  );
}

function formatDate(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  return date.toLocaleDateString(undefined, { day: "2-digit", month: "2-digit", year: "numeric" });
}

export function DetailTabs({
  application,
  match,
}: {
  application: Application;
  /** Fetched by the page alongside the record, so the tab has no loading state
   *  of its own — the four states already say everything about readiness. */
  match: MatchResult;
}) {
  return (
    <Tabs.Root defaultValue="details">
      <Tabs.List
        className="flex gap-1 overflow-x-auto border-b"
        style={{ borderColor: "var(--border)" }}
        aria-label="Application detail"
      >
        {TABS.map(({ value, label, built }) => (
          <Tabs.Trigger
            key={value}
            value={value}
            className="flex items-center gap-1.5 border-b-2 border-transparent px-3 py-2.5 text-sm whitespace-nowrap transition-colors data-[state=active]:border-[var(--color-brand-600)] data-[state=active]:font-medium"
            style={{ color: built ? "var(--muted)" : "var(--faint)" }}
          >
            {label}
            {!built && (
              // The marker from docs/09 §6.3. Muted and quiet: it says "later",
              // not "broken".
              <span aria-label="not built yet" title="Not built yet">
                ◦
              </span>
            )}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      {/* **Both tabs are keyed on the job.** They hold their own polled state,
          and React would otherwise keep it across a navigation — same
          component, same position, different record — so the previous job's
          score would greet you on the next one. Keying makes the identity of
          the record the identity of the component, which is what it is. */}
      <Tabs.Content value="tailor" className="outline-none">
        {/* Fetches its own version and polls while a run is in flight, rather
            than being handed data by the page. A tailoring run outlives the
            request that started it, so there is nothing for a server render to
            hand over that would still be true by the time it is read. */}
        <TailorTab key={application.id} applicationId={application.id} />
      </Tabs.Content>

      <Tabs.Content value="match" className="outline-none">
        {/* Scoring outlives its request too — the page fetched `/match` in the
            same second a run began and never again, and the screen read
            "Scoring" for twenty minutes. These props are the starting point;
            the tab polls for the rest. */}
        <MatchTab
          key={application.id}
          state={match.state}
          analysis={match.analysis}
          stale={match.stale}
          applicationId={application.id}
          canScore={Boolean(application.requirements?.length)}
        />
      </Tabs.Content>

      <Tabs.Content value="details" className="pt-6 outline-none">
        <dl className="grid gap-5 sm:grid-cols-3">
          <Field label="Company" value={application.company.name} />
          <Field label="Role" value={application.job_title} />
          <Field label="Location" value={application.location} />
          <Field label="Applied" value={formatDate(application.date_applied)} />
          <Field label="Added" value={formatDate(application.date_added)} />
          <Field label="Applied via" value={application.source} />
          <Field label="Salary" value={application.salary_text} />
          <Field label="Contact" value={application.contact_name} />
          <Field label="Contact email" value={application.contact_email} />
        </dl>

        {application.job_url && (
          <p className="mt-5 text-sm">
            <a
              href={application.job_url}
              target="_blank"
              rel="noreferrer noopener"
              className="text-brand-700 underline underline-offset-4"
            >
              Original posting
            </a>
          </p>
        )}

        {application.notes && (
          <div className="mt-6">
            <h3 className="text-xs font-medium tracking-wide uppercase" style={{ color: "var(--muted)" }}>
              Notes
            </h3>
            <p className="mt-2 text-sm whitespace-pre-wrap">{application.notes}</p>
          </div>
        )}

        {/* Two fields, two jobs. `requirements` is what a person reads; the
            posting is what match analysis scores and is kept behind a
            disclosure so it does not drown the list.

            Before slice 004 there was one field doing both, and after R1 gave
            `job_description` back its plain meaning this panel showed several
            hundred words of company blurb under a heading reading
            "Requirements" (T057). */}
        <div className="mt-8">
          <h3 className="text-xs font-medium tracking-wide uppercase" style={{ color: "var(--muted)" }}>
            Requirements
          </h3>

          {/* `null` means no posting was ever captured — a row recorded before
              slice 004, whose `job_description` holds a joined requirements
              list rather than an advert. There is nothing to recover, so it
              says so plainly and offers the fix. Ordinary, not an error: it is
              the state of every older record (T058, research.md R1). */}
          {application.requirements === null ? (
            <>
              {application.job_description ? (
                <div
                  className="mt-2 rounded-lg p-5 text-sm leading-relaxed"
                  style={{ background: "var(--surface-sunken)" }}
                >
                  <RequirementList text={application.job_description} />
                </div>
              ) : (
                <p className="mt-2 text-sm" style={{ color: "var(--faint)" }}>
                  No requirements saved for this job.
                </p>
              )}
              <p className="mt-2 text-sm" style={{ color: "var(--muted)" }}>
                No job posting was saved for this job, so it cannot be scored against your
                profile. Add it again from its URL or paste the posting to fix that.
              </p>
            </>
          ) : application.requirements.length > 0 ? (
            <div
              className="mt-2 rounded-lg p-5 text-sm leading-relaxed"
              style={{ background: "var(--surface-sunken)" }}
            >
              <BulletList items={application.requirements} />
            </div>
          ) : (
            <p className="mt-2 text-sm" style={{ color: "var(--faint)" }}>
              No requirements were found in this posting.
            </p>
          )}

          {/* Deliberately not a link out: the posting may have expired, and
              this stored text is what gets scored. */}
          {application.requirements !== null && application.job_description && (
            <details className="mt-3">
              <summary className="cursor-pointer text-sm" style={{ color: "var(--muted)" }}>
                Read the full posting
              </summary>
              <div
                className="mt-2 rounded-lg p-5 text-sm leading-relaxed whitespace-pre-wrap"
                style={{ background: "var(--surface-sunken)" }}
              >
                {application.job_description}
              </div>
            </details>
          )}
        </div>

        {application.status_history.length > 0 && (
          <div className="mt-8">
            <h3 className="text-xs font-medium tracking-wide uppercase" style={{ color: "var(--muted)" }}>
              History
            </h3>
            {/* Append-only (FR-012). The timeline is the record; the status at
                the top of the page is a projection of it. */}
            <ol className="mt-2 space-y-1.5 text-sm">
              {application.status_history.map((change, index) => (
                <li key={index} className="flex flex-wrap gap-2" style={{ color: "var(--muted)" }}>
                  <span className="font-mono text-xs tabular-nums" style={{ color: "var(--faint)" }}>
                    {formatDate(change.changed_at)}
                  </span>
                  <span>
                    {change.from_status ? `${change.from_status} → ` : "Recorded as "}
                    <span style={{ color: "var(--foreground)" }}>{change.to_status}</span>
                  </span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Tabs.Content>

      {TABS.filter((tab) => !tab.built).map(({ value }) => (
        <Tabs.Content key={value} value={value} className="pt-6 outline-none">
          <NotBuiltYet title={UNBUILT[value].title} arrives={UNBUILT[value].arrives} />
        </Tabs.Content>
      ))}
    </Tabs.Root>
  );
}
