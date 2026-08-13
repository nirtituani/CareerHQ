"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ConfidenceMeter,
  LOW_CONFIDENCE,
  ProvenanceLabel,
  provenanceStyle,
} from "@/components/provenance";
import { Button } from "@/components/ui/button";
import {
  type Decision,
  type ExtractionItem,
  type ImportedResume,
  SECTIONS,
  summarise,
} from "@/lib/imports";

/**
 * The review interface — docs/09 §6.5, and the hardest screen in the slice.
 *
 * The problem is volume: dozens of items across many sections, each needing a
 * decision, with the user needing to move fast and not lose their place. Three
 * things address that, and they are the design rather than embellishment:
 *
 * - **Keyboard first.** A/E/D and J/K. This is the difference between reviewing
 *   sixty items and abandoning the import, not a nicety.
 * - **Reviewed items collapse**, so the list visibly shortens as work is done.
 *   Progress you can see beats a progress bar you have to interpret.
 * - **Nothing is decided for you.** Confidence orders and flags; it never
 *   accepts. Principle II admits no threshold.
 */
export function ImportReview({
  record,
  onPatch,
  onApprove,
}: {
  record: ImportedResume;
  onPatch: (itemId: string, body: Record<string, unknown>) => Promise<void>;
  onApprove: () => Promise<void>;
}) {
  const [items, setItems] = useState(record.items);
  const [cursor, setCursor] = useState(0);
  const [busy, setBusy] = useState(false);

  const sections = useMemo(
    () => SECTIONS.filter((s) => items.some((i) => i.kind === s.kind)),
    [items],
  );
  const [section, setSection] = useState(sections[0]?.kind ?? "");

  const visible = useMemo(
    () => items.filter((i) => i.kind === section),
    [items, section],
  );

  const decide = useCallback(
    async (item: ExtractionItem, decision: Decision) => {
      setItems((prev) =>
        prev.map((i) => (i.id === item.id ? { ...i, decision } : i)),
      );
      setCursor((c) => Math.min(c + 1, visible.length - 1));
      await onPatch(item.id, { decision });
    },
    [onPatch, visible.length],
  );

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      // Never hijack typing in a field: an editor open on an item is exactly
      // when these letters are wanted as letters.
      if (target && ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName)) return;

      const item = visible[cursor];
      if (!item) return;

      if (event.key === "j" || event.key === "ArrowDown") {
        event.preventDefault();
        setCursor((c) => Math.min(c + 1, visible.length - 1));
      } else if (event.key === "k" || event.key === "ArrowUp") {
        event.preventDefault();
        setCursor((c) => Math.max(c - 1, 0));
      } else if (event.key === "a") {
        void decide(item, "accepted");
      } else if (event.key === "d") {
        void decide(item, "discarded");
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, decide, visible]);

  const reviewed = items.filter((i) => i.decision !== "pending").length;
  const attention = items.filter(
    (i) => i.decision === "pending" && i.confidence < LOW_CONFIDENCE,
  ).length;
  const anyAccepted = items.some((i) => i.decision !== "discarded");

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {record.is_fixture && (
        // Persistent for the whole review. The one unacceptable outcome of
        // having a fixture mode is someone approving invented content into
        // their own profile.
        <div
          role="alert"
          className="mb-4 rounded-md px-4 py-2 text-sm"
          style={{
            border: "1px solid var(--color-fixture)",
            color: "var(--color-fixture)",
          }}
        >
          <strong>Demo data — this is not your CV.</strong> Nothing here was read from your
          upload.
        </div>
      )}

      <div className="flex min-h-0 flex-1 gap-8">
        <nav aria-label="Sections" className="w-52 shrink-0 space-y-0.5">
          {sections.map((s) => {
            const inSection = items.filter((i) => i.kind === s.kind);
            const done = inSection.filter((i) => i.decision !== "pending").length;
            return (
              <button
                key={s.kind}
                onClick={() => {
                  setSection(s.kind);
                  setCursor(0);
                }}
                aria-current={section === s.kind ? "true" : undefined}
                className="flex w-full items-center justify-between rounded-md px-3 py-2 text-sm"
                style={
                  section === s.kind
                    ? { background: "var(--surface)", color: "var(--foreground)" }
                    : { color: "var(--muted)" }
                }
              >
                <span>{s.label}</span>
                <span className="tabular text-xs" style={{ fontFamily: "var(--font-mono)" }}>
                  {done}/{inSection.length}
                </span>
              </button>
            );
          })}
        </nav>

        <ul className="min-w-0 flex-1 space-y-2">
          {visible.map((item, index) => {
            const settled = item.decision !== "pending";
            return (
              <li
                key={item.id}
                aria-current={index === cursor ? "true" : undefined}
                className="rounded-md py-2 pr-3"
                style={{
                  ...provenanceStyle(item.source),
                  background: index === cursor ? "var(--surface)" : undefined,
                  opacity: item.decision === "discarded" ? 0.45 : 1,
                }}
              >
                <div className="flex items-start justify-between gap-4">
                  <p
                    className={settled ? "truncate text-sm" : "text-sm"}
                    style={
                      item.decision === "discarded"
                        ? { textDecoration: "line-through" }
                        : undefined
                    }
                  >
                    {summarise(item)}
                  </p>

                  <div className="flex shrink-0 items-center gap-3">
                    <ConfidenceMeter value={item.confidence} />
                    <ProvenanceLabel source={item.source} />
                    <Button
                      size="sm"
                      variant={item.decision === "accepted" ? "default" : "outline"}
                      onClick={() => void decide(item, "accepted")}
                    >
                      Keep
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void decide(item, "discarded")}
                    >
                      Discard
                    </Button>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <div
        className="mt-6 flex items-center justify-between border-t pt-4"
        style={{ borderColor: "var(--border)" }}
      >
        <p className="text-sm" style={{ color: "var(--muted)" }}>
          <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
            {reviewed} of {items.length}
          </span>{" "}
          reviewed
          {attention > 0 && (
            <>
              {" · "}
              <span style={{ color: "var(--color-attention)" }}>
                {attention} need attention
              </span>
            </>
          )}
          <span className="ml-3 text-xs" style={{ color: "var(--faint)" }}>
            A keep · D discard · J/K move
          </span>
        </p>

        <Button
          disabled={!anyAccepted || busy}
          onClick={() => {
            setBusy(true);
            void onApprove().finally(() => setBusy(false));
          }}
        >
          {busy ? "Adding to profile…" : "Add to my profile"}
        </Button>
      </div>
    </div>
  );
}
