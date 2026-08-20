"use client";

/**
 * The CV as it was uploaded, rendered by the browser's own PDF viewer.
 *
 * **Not a second source of truth.** ADR-013 keeps the structured profile as the
 * thing the system reasons over; nothing in extraction, scoring or tailoring
 * reads these bytes, and `test_architecture.py` still enforces that. This
 * exists because a person sometimes needs to check what the document actually
 * said — which is exactly how a deployed profile scoring 58 was explained
 * against the same posting scoring 87 locally.
 *
 * No third-party viewer. A hosted one (Google's, say) has to fetch the file
 * itself, which would mean making a CV — home address, phone number,
 * employment history — publicly reachable. An `<iframe>` at our own endpoint
 * gets the same toolbar from the browser and sends nothing anywhere.
 */

import { useState } from "react";

import type { ImportRecord } from "@/lib/api";

function formatBytes(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function OriginalCv({ imports }: { imports: ImportRecord[] }) {
  // Approved uploads only. A failed or discarded one never reached the profile,
  // so offering it would answer a question nobody asked.
  const approved = imports.filter((i) => i.status === "approved");
  const usable = approved.length > 0 ? approved : imports;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const source = usable.find((i) => i.id === selectedId) ?? usable[0];

  if (!source) {
    return (
      <p className="py-10 text-sm" style={{ color: "var(--muted)" }}>
        No CV has been uploaded yet. Import one and the original stays here, exactly as you sent
        it.
      </p>
    );
  }

  const isPdf = source.content_type === "application/pdf";

  return (
    <div className="py-6">
      {/* The profile is a **merge** of every approved import, so there is no
          single "the original" once someone has imported twice. Picking one is
          the honest interface: the alternative silently shows the newest and
          lets a person conclude their profile came from a document that
          contributed part of it. */}
      {usable.length > 1 && (
        <div className="mb-3 flex flex-wrap gap-2">
          {usable.map((record) => (
            <button
              key={record.id}
              type="button"
              onClick={() => setSelectedId(record.id)}
              className="rounded-lg border px-3 py-1.5 text-left text-xs"
              style={{
                borderColor:
                  record.id === source.id ? "var(--color-brand-600)" : "var(--border)",
                color: record.id === source.id ? "var(--foreground)" : "var(--muted)",
              }}
            >
              {record.filename}
              <span className="ml-1.5" style={{ color: "var(--faint)" }}>
                {new Date(record.created_at).toLocaleDateString()}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <p className="text-sm font-medium">{source.filename}</p>
          <p className="mt-0.5 text-xs" style={{ color: "var(--faint)" }}>
            {/* Monospace, because these are reported verbatim (docs/09 §1). */}
            <span style={{ fontFamily: "var(--font-mono)" }}>
              {formatBytes(source.byte_size)}
            </span>{" "}
            · uploaded {new Date(source.created_at).toLocaleDateString()} · this original is never
            modified
          </p>
        </div>
        <a
          href={`/api/imports/${source.id}/file`}
          target="_blank"
          rel="noreferrer noopener"
          className="text-sm underline underline-offset-4"
          style={{ color: "var(--muted)" }}
        >
          Open in a new tab
        </a>
      </div>

      {isPdf ? (
        <iframe
          key={source.id}
          src={`/api/imports/${source.id}/file`}
          title={`${source.filename} — original CV`}
          className="h-[75vh] w-full rounded-lg border"
          style={{ borderColor: "var(--border)" }}
        />
      ) : (
        // Only PDF renders inline. Anything else the endpoint sends as an
        // attachment, because serving arbitrary uploaded content inline from
        // our own origin is an XSS vector.
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          This upload is not a PDF, so it cannot be previewed here. Use the link above to download
          it.
        </p>
      )}
    </div>
  );
}
