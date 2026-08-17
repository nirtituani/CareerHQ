"use client";

import { Tabs } from "radix-ui";

import { NotBuiltYet } from "@/components/not-built-yet";
import type { Application } from "@/lib/api";

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
const TABS = [
  { value: "details", label: "Details", built: true },
  { value: "company", label: "Company", built: false, arrives: "Slice 006" },
  { value: "interview", label: "Interview", built: false, arrives: "Not yet on the roadmap" },
  { value: "versions", label: "Versions", built: false, arrives: "Slice 004" },
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
  versions: {
    title: "Tailored versions",
    arrives:
      "Resumes tailored for this job, with their lineage, arrive with resume tailoring.",
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

  return (
    <ul className="space-y-1.5">
      {lines.map((line, index) => (
        <li key={index} className="flex gap-2.5">
          <span aria-hidden style={{ color: "var(--color-brand-600)" }}>
            •
          </span>
          <span className="min-w-0 flex-1">{line}</span>
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

export function DetailTabs({ application }: { application: Application }) {
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

        <div className="mt-8">
          <h3 className="text-xs font-medium tracking-wide uppercase" style={{ color: "var(--muted)" }}>
            Job description - Requirements
          </h3>

          {application.job_description ? (
            // On --surface-sunken (docs/09 §3, §6.3), and deliberately not a
            // link out: the posting may have expired, and this is what slice
            // 004 tailors against.
            <div
              className="mt-2 rounded-lg p-5 text-sm leading-relaxed"
              style={{ background: "var(--surface-sunken)" }}
            >
              <RequirementList text={application.job_description} />
            </div>
          ) : (
            <p className="mt-2 text-sm" style={{ color: "var(--faint)" }}>
              No requirements saved for this job. Add them to tailor a resume against them.
            </p>
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
