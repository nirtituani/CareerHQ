"use client";

import { Edit2, FileText, RotateCcw, Trash2, XCircle } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import { AddApplication } from "@/components/applications/add-application";
import { CompanyLogo } from "@/components/applications/company-logo";
import { MatchCell } from "@/components/applications/match-score";
import { StatusPill } from "@/components/applications/status-pill";
import { type Application, deleteApplication, unrejectApplication, updateApplication } from "@/lib/api";

/**
 * The applications table, and the stat tiles that filter it (docs/09 §6.1, §6.2).
 *
 * **One component, two screens.** The dashboard shows the tiles above the
 * table; Applications shows the table with search. Building those as two
 * renderers is how an affordance goes missing — during slice 003 grouping
 * skills created a second render path and Edit, then Add, then Remove each
 * disappeared from it in turn. So the table is written once and the surrounding
 * chrome is switched by props.
 *
 * The table is a **reading surface, not a form** (docs/09 §4): 44px rows,
 * hairline rules, no zebra striping — alternating fills fight with the status
 * pills, and at 96 rows they read as texture rather than structure.
 */

/** The four tiles from docs/09 §6.1, each a filter over normalized categories. */
const TILES: { key: string; label: string; matches: (a: Application) => boolean }[] = [
  { key: "total", label: "Total", matches: () => true },
  {
    key: "active",
    label: "Active",
    // The source app's own definition, from its dashboard query:
    //
    //   status NOT IN ('Pre-Applied','Rejected','Ghosted','Withdrawn')
    //          AND (rejected IS NOT TRUE)
    //
    // **Pre-Applied is not active.** Nothing has been sent yet, so counting it
    // made the tile claim applications were in flight when none had been
    // submitted. This previously excluded only the closed outcomes, on the
    // reasoning that a new value should count as active by default rather than
    // vanish — right instinct, wrong list, and the wishlist rows paid for it.
    //
    // An unrecognised label still counts as active, which the source does too:
    // its exclusion list cannot name a status it has never seen.
    matches: (a) => !["wishlist", "rejected", "withdrawn", "ghosted"].includes(a.normalized_status),
  },
  { key: "interviews", label: "Interviews", matches: (a) => a.normalized_status === "interviewing" },
  { key: "rejected", label: "Rejected", matches: (a) => a.normalized_status === "rejected" },
];

/** Columns, in the source app's order. Location is deliberately absent — it
 *  belongs on the record you open, not in a row scanned ninety-six at a time. */
const COLUMNS = [
  "Company",
  "Job Title",
  "Status",
  "Date Applied",
  "Match",
  "Applied Via",
  "Job Desc",
  "",
];

/** Outcomes that have ended. Rendered receded rather than red. */
const CLOSED = new Set(["rejected", "withdrawn", "ghosted"]);

const ACTION =
  "rounded-md p-1.5 transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-40";

/**
 * Edit, mark-rejected (or undo), delete — the source app's three row actions.
 *
 * "Mark as rejected" moves the *status* rather than setting a flag beside it,
 * so there is still one source of truth (FR-016). Undo reads the previous
 * status back out of the append-only history and appends the move, so the
 * rejection is not erased — it happened, and the timeline still says so.
 */
function RowActions({ application }: { application: Application }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const rejected = application.normalized_status === "rejected";

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex justify-end gap-0.5">
      {/* The same modal as Add Application, opened on the form step with the
          record's own values — one form to maintain rather than two that drift.
          Saving PATCHes, so a status change still writes its history row. */}
      <AddApplication open={editing} onOpenChange={setEditing} editing={application} />
      <button
        type="button"
        className={ACTION}
        title="Edit"
        style={{ color: "var(--muted)" }}
        onClick={() => setEditing(true)}
      >
        <Edit2 className="size-3.5" />
      </button>

      <button
        type="button"
        disabled={busy}
        className={ACTION}
        style={{ color: rejected ? "var(--color-attention)" : "var(--muted)" }}
        title={rejected ? "Undo rejection" : "Mark as rejected"}
        onClick={() =>
          void run(() =>
            rejected
              ? unrejectApplication(application.id)
              : updateApplication(application.id, { status: "Rejected" }),
          )
        }
      >
        {rejected ? <RotateCcw className="size-3.5" /> : <XCircle className="size-3.5" />}
      </button>

      <button
        type="button"
        disabled={busy}
        className={ACTION}
        style={{ color: "var(--muted)" }}
        title="Delete"
        onClick={() => {
          // Deleting takes the history with it, so it is worth one question.
          if (confirm(`Delete the ${application.job_title} application at ${application.company.name}?`))
            void run(() => deleteApplication(application.id));
        }}
      >
        <Trash2 className="size-3.5" />
      </button>
    </div>
  );
}

/** `09/08/2026`, mono and tabular so the column aligns down the page. */
function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return [
    String(date.getDate()).padStart(2, "0"),
    String(date.getMonth() + 1).padStart(2, "0"),
    date.getFullYear(),
  ].join("/");
}

function StatTiles({
  applications,
  active,
  onSelect,
}: {
  applications: Application[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
      {TILES.map(({ key, label, matches }) => {
        const selected = active === key;
        return (
          // A button, not a card with a click handler: the tiles are filters,
          // carried over from JobTracker where they already were buttons.
          <button
            key={key}
            type="button"
            aria-pressed={selected}
            onClick={() => onSelect(key)}
            className="rounded-xl border p-4 text-left transition-colors"
            style={{
              borderColor: selected ? "var(--color-brand-600)" : "var(--border)",
              background: selected ? "var(--surface)" : "transparent",
            }}
          >
            <p className="text-xs font-medium tracking-wide uppercase" style={{ color: "var(--muted)" }}>
              {label}
            </p>
            <p
              className="mt-1 text-4xl tabular-nums"
              style={{ fontFamily: "var(--font-display)" }}
            >
              {applications.filter(matches).length}
            </p>
          </button>
        );
      })}
    </div>
  );
}

export function ApplicationsView({
  applications,
  showTiles = false,
  showSearch = false,
}: {
  applications: Application[];
  showTiles?: boolean;
  showSearch?: boolean;
}) {
  const [tile, setTile] = useState("total");
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const matchesTile = TILES.find((t) => t.key === tile)?.matches ?? (() => true);
    const needle = query.trim().toLowerCase();

    return applications.filter((application) => {
      if (!matchesTile(application)) return false;
      if (!needle) return true;
      return [
        application.company.name,
        application.job_title,
        application.location ?? "",
        application.status,
      ].some((field) => field.toLowerCase().includes(needle));
    });
  }, [applications, tile, query]);

  return (
    <>
      {showTiles && (
        <StatTiles
          applications={applications}
          active={tile}
          onSelect={(key) => setTile(key === tile ? "total" : key)}
        />
      )}

      {showSearch && (
        <div className="mb-4 flex flex-wrap items-center gap-3">
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search company, role, location…"
            aria-label="Search applications"
            className="h-9 min-w-64 flex-1 rounded-md border px-3 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--background)" }}
          />
          <div className="flex flex-wrap gap-1.5">
            {TILES.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                aria-pressed={tile === key}
                onClick={() => setTile(key === tile ? "total" : key)}
                className="rounded-md px-2.5 py-1.5 text-xs font-medium transition-colors"
                style={
                  tile === key
                    ? { background: "var(--surface)", color: "var(--foreground)" }
                    : { color: "var(--muted)" }
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}

      {applications.length === 0 ? (
        // "Empty but available" — plain muted text in a normal container
        // (docs/09 §5). Deliberately not the dashed *not built yet* treatment
        // and deliberately not an error: nothing is broken and nothing is
        // missing, there is simply no job recorded yet.
        <p className="py-8 text-sm" style={{ color: "var(--muted)" }}>
          No applications yet. Record a job to start tracking it.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-xl border" style={{ borderColor: "var(--border)" }}>
          <table className="w-full border-collapse text-sm">
            <thead className="sticky top-0" style={{ background: "var(--surface)" }}>
              <tr style={{ color: "var(--muted)" }}>
                {COLUMNS.map((heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="border-b px-4 py-2.5 text-left text-xs font-medium tracking-wide uppercase"
                    style={{ borderColor: "var(--border)" }}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>

            <tbody>
              {visible.map((application) => (
                <tr
                  key={application.id}
                  className="border-b transition-colors last:border-0"
                  style={{
                    borderColor: "var(--border)",
                    height: "var(--spacing-row)",
                    // Closed outcomes recede rather than shout — the source app
                    // muted them too, and rejection is the commonest ending of
                    // a job search, not an error.
                    opacity: CLOSED.has(application.normalized_status) ? 0.6 : 1,
                  }}
                >
                  <td className="px-4">
                    <div className="flex items-center gap-2">
                      <CompanyLogo
                        company={application.company.name}
                        domain={application.company.domain}
                      />
                      <Link
                        href={`/applications/${application.id}`}
                        className="font-medium hover:underline"
                      >
                        {application.company.name}
                      </Link>
                    </div>
                  </td>

                  <td className="px-4" style={{ color: "var(--muted)" }}>
                    {application.job_title}
                  </td>

                  <td className="px-4">
                    <StatusPill
                      status={application.status}
                      normalized={application.normalized_status}
                    />
                  </td>

                  <td
                    className="px-4 font-mono text-xs tabular-nums"
                    style={{ color: "var(--muted)" }}
                  >
                    {/* The applied date once it exists, the added date before
                        that. Two stored fields, one column: a Pre-Applied row
                        still shows when it was recorded, which is what makes a
                        job that has been sitting for weeks visible. */}
                    {formatDate(application.date_applied ?? application.date_added)}
                  </td>

                  <td
                    className="px-4 font-mono text-xs tabular-nums"
                    style={{ color: "var(--muted)" }}
                  >
                    {/* Two facts, never merged. The computed band is what the
                        system thinks; `imported_match_rating` is what the
                        person thought, carried from JobTracker and never
                        overwritten (FR-013). One field for both would drift,
                        exactly as the source app's `rejected` flag drifted
                        from its status. */}
                    <MatchCell
                      match={
                        application.match ?? {
                          state: "nothing_to_score",
                          band: null,
                          overall_score: null,
                        }
                      }
                    />
                    {application.imported_match_rating > 0 && (
                      <span
                        className="ml-2"
                        style={{ color: "var(--muted)" }}
                        title="Your own rating, imported from JobTracker"
                      >
                        {application.imported_match_rating * 20}%
                      </span>
                    )}
                  </td>

                  <td className="px-4 text-xs" style={{ color: "var(--muted)" }}>
                    {application.source ?? "—"}
                  </td>

                  <td className="px-4">
                    {/* Kept from the source app at the user's request. docs/09
                        §6.2 had dropped this column in favour of "does a
                        tailored resume exist" — that can share the space when
                        slice 004 builds versions. */}
                    {application.job_description_url || application.job_url ? (
                      <a
                        href={application.job_description_url ?? application.job_url ?? "#"}
                        target="_blank"
                        rel="noreferrer noopener"
                        title="Open the original posting"
                        style={{ color: "var(--color-brand-600)" }}
                      >
                        <FileText className="size-4" />
                      </a>
                    ) : (
                      <FileText className="size-4" style={{ color: "var(--faint)" }} aria-hidden />
                    )}
                  </td>

                  <td className="px-2">
                    <RowActions application={application} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {visible.length === 0 && (
            <p className="px-4 py-6 text-sm" style={{ color: "var(--muted)" }}>
              No applications match this filter.
            </p>
          )}
        </div>
      )}
    </>
  );
}
