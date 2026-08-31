"use client";

import { AlertCircle, CheckCircle2, FileUp, Info, Loader2, SkipForward } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  ApiError,
  MAX_IMPORT_BYTES,
  type JobtrackerImportReport,
  importJobtracker,
} from "@/lib/api";

/**
 * The JobTracker import screen (T083), over the endpoint T084 exercised in
 * production.
 *
 * **The report has four outcomes and two of them are easy to render as a lie.**
 * `skipped` is a success — re-running an import is safe by design, and the
 * honest answer to a second upload is that nothing new arrived. `notices` are
 * rows that **did** import; showing them beside rejections would send someone
 * looking for history that is already in the database. Each gets its own block,
 * its own icon and its own colour, and a block with nothing in it is not drawn
 * at all — "0 rejected" invites a hunt for a problem that does not exist.
 *
 * **The working state can only be indeterminate.** The endpoint is synchronous
 * and reports no progress, so there is nothing honest to fill a bar with. It
 * still has to look different from idle: a 96-row import is a long POST, and a
 * screen that looks idle invites a second upload of the same file.
 */

type State =
  | { name: "idle" }
  | { name: "importing"; filename: string }
  | { name: "done"; report: JobtrackerImportReport }
  | { name: "failed"; message: string };

/** Plural that reads as English rather than as `1 row(s)`. */
function rows(n: number): string {
  return `${n} ${n === 1 ? "row" : "rows"}`;
}

export function JobtrackerImport() {
  const [state, setState] = useState<State>({ name: "idle" });
  const input = useRef<HTMLInputElement>(null);

  async function onPick(file: File | undefined) {
    if (!file) return;

    // The server guards this too; failing here only spares a long upload.
    if (file.size > MAX_IMPORT_BYTES) {
      setState({ name: "failed", message: "That file is larger than 10 MB." });
      return;
    }

    setState({ name: "importing", filename: file.name });

    try {
      const report = await importJobtracker(file);
      setState({ name: "done", report });
    } catch (error) {
      setState({
        name: "failed",
        // An ApiError's message is the server's own sentence and is meant for
        // a person — the missing columns, the concurrent import, the size.
        // Anything else is an operator's detail and must not reach the browser.
        message:
          error instanceof ApiError
            ? error.message
            : "That import could not be completed. Please try again.",
      });
    } finally {
      // Clearing lets the same file be chosen twice — the retry path, and the
      // one a person reaches for when they are unsure the first upload worked.
      if (input.current) input.current.value = "";
    }
  }

  const busy = state.name === "importing";

  return (
    <div className="max-w-2xl">
      <div
        className="mt-6 rounded-lg border p-6"
        style={{ borderColor: "var(--border)", background: "var(--surface)" }}
      >
        <label htmlFor="jobtracker-file" className="text-sm font-medium">
          Upload your JobTracker CSV export.
        </label>

        <input
          ref={input}
          id="jobtracker-file"
          type="file"
          accept=".csv,text/csv"
          disabled={busy}
          className="mt-2 block w-full text-sm"
          onChange={(event) => void onPick(event.target.files?.[0])}
        />

        <p className="mt-2 text-xs" style={{ color: "var(--faint)" }}>
          Up to 10 MB. Importing the same file twice is safe — rows already
          imported are skipped, not duplicated.
        </p>

        {busy && (
          <p
            data-testid="importing"
            className="mt-4 flex items-center gap-2 text-sm"
            style={{ color: "var(--muted)" }}
          >
            {/* Indeterminate by necessity: the endpoint reports no progress.
                A spinning arc rather than a full ring, so a paused animation
                never reads as a finished run. */}
            <Loader2 className="size-4 animate-spin" aria-hidden />
            <span>Importing {state.filename}…</span>
          </p>
        )}
      </div>

      {state.name === "failed" && (
        <p
          role="alert"
          className="mt-4 flex items-start gap-2 rounded-lg border p-4 text-sm"
          style={{ borderColor: "var(--color-failure)", color: "var(--color-failure)" }}
        >
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>{state.message}</span>
        </p>
      )}

      {state.name === "done" && <Report report={state.report} />}
    </div>
  );
}

/** The four outcomes, each visually its own thing. */
function Report({ report }: { report: JobtrackerImportReport }) {
  const { imported, skipped, rejected, notices } = report;
  const nothingHappened = imported === 0 && skipped === 0 && rejected.length === 0;

  return (
    <div className="mt-6 space-y-4">
      {/* Imported — the plain success. */}
      {imported > 0 && (
        <Outcome
          testId="outcome-imported"
          tone="var(--color-outcome-offer)"
          icon={<CheckCircle2 className="mt-0.5 size-4 shrink-0" aria-hidden />}
          title={`Imported ${rows(imported)}`}
          body="Added to your applications."
        />
      )}

      {/* Skipped — also a success, and the one most likely to be misread.
          The wording says "already", never "failed". */}
      {skipped > 0 && (
        <Outcome
          testId="outcome-skipped"
          tone="var(--muted)"
          icon={<SkipForward className="mt-0.5 size-4 shrink-0" aria-hidden />}
          title={`Skipped ${rows(skipped)}`}
          body="Already imported previously, so nothing was duplicated."
        />
      )}

      {/* Notices — imported, and saying so first, because the row IS there. */}
      {notices.length > 0 && (
        <Outcome
          testId="outcome-notices"
          tone="var(--color-attention)"
          icon={<Info className="mt-0.5 size-4 shrink-0" aria-hidden />}
          title={`${rows(notices.length)} imported with something to check`}
          body="These are in your applications. Something about them needs your eye."
        >
          <ul className="mt-2 space-y-1">
            {notices.map((notice) => (
              <li key={notice.source_id} className="text-xs">
                <span style={{ fontFamily: "var(--font-mono)" }}>{notice.source_id}</span>
                {" — "}
                {notice.message}
              </li>
            ))}
          </ul>
        </Outcome>
      )}

      {/* Rejected — the only block describing rows that are NOT there. */}
      {rejected.length > 0 && (
        <Outcome
          testId="outcome-rejected"
          tone="var(--color-failure)"
          icon={<AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />}
          title={`${rows(rejected.length)} could not be imported`}
          body="These are not in your applications. Fix them in the file and import again."
        >
          <ul className="mt-2 space-y-1">
            {rejected.map((rejection) => (
              <li key={rejection.source_id} className="text-xs">
                <span style={{ fontFamily: "var(--font-mono)" }}>{rejection.source_id}</span>
                {" — "}
                {rejection.reason}
              </li>
            ))}
          </ul>
        </Outcome>
      )}

      {nothingHappened && (
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          That file held no rows to import.
        </p>
      )}

      <Button asChild variant="outline">
        <a href="/applications">
          <FileUp aria-hidden />
          Back to applications
        </a>
      </Button>
    </div>
  );
}

function Outcome({
  testId,
  tone,
  icon,
  title,
  body,
  children,
}: {
  testId: string;
  tone: string;
  icon: React.ReactNode;
  title: string;
  body: string;
  children?: React.ReactNode;
}) {
  return (
    <div
      data-testid={testId}
      className="flex items-start gap-3 rounded-lg border p-4"
      style={{ borderColor: "var(--border)", background: "var(--surface)" }}
    >
      <span style={{ color: tone }}>{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium" style={{ color: tone }}>
          {title}
        </p>
        <p className="mt-0.5 text-xs" style={{ color: "var(--muted)" }}>
          {body}
        </p>
        {children}
      </div>
    </div>
  );
}
