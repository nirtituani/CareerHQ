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
  bulletsOf,
  describe,
  groupByCategory,
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
            const inSection = items.filter(
              (i) =>
                i.kind === s.kind ||
                (s.kind === "work_experience" && i.kind === "bullet"),
            );
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
          {/* Skills keep the grouping the CV used. Twenty-two in a flat list is
              a wall; six labelled groups is the structure the author wrote. */}
          {section === "skill" &&
            groupByCategory(visible).map(([category, group]) => (
              <li key={category} className="pt-2 first:pt-0">
                <p
                  className="mb-1 text-xs tracking-wider uppercase"
                  style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
                >
                  {category}
                </p>
                <ul className="space-y-1">
                  {group.map((item) => (
                    <li
                      key={item.id}
                      className="flex items-center justify-between gap-3 py-1 text-sm"
                      style={{
                        ...provenanceStyle(item.source),
                        opacity: item.decision === "discarded" ? 0.45 : 1,
                        textDecoration:
                          item.decision === "discarded" ? "line-through" : undefined,
                      }}
                    >
                      <span className="min-w-0">{describe(item).primary}</span>
                      <span className="flex shrink-0 items-center gap-2">
                        <ConfidenceMeter value={item.confidence} />
                        <button
                          className="text-xs underline underline-offset-2"
                          style={{ color: "var(--muted)" }}
                          onClick={() =>
                            void decide(
                              item,
                              item.decision === "discarded" ? "accepted" : "discarded",
                            )
                          }
                        >
                          {item.decision === "discarded" ? "Keep" : "Discard"}
                        </button>
                      </span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}

          {section !== "skill" &&
            visible.map((item, index) => {
            const settled = item.decision !== "pending";
            const described = describe(item);
            const bullets = item.kind === "work_experience" ? bulletsOf(items, item.id) : [];
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
                  <div className="min-w-0">
                    <p
                      className="text-sm"
                      style={
                        item.decision === "discarded"
                          ? { textDecoration: "line-through" }
                          : undefined
                      }
                    >
                      {described.primary}
                    </p>
                    {/* Every captured field is shown. Hiding one would mean
                        asking the user to verify something they cannot see. */}
                    {!settled &&
                      described.details.map((detail) => (
                        <p
                          key={detail}
                          className="text-xs"
                          style={{ color: "var(--faint)" }}
                        >
                          {detail}
                        </p>
                      ))}

                    {/* Bullets sit under their role. Reviewing one in isolation
                        cannot answer the only question that matters about it —
                        whether it belongs to this job. */}
                    {bullets.length > 0 && (
                      <ul className="mt-2 space-y-1">
                        {bullets.map((bullet) => (
                          <li
                            key={bullet.id}
                            className="py-0.5 text-sm"
                            style={{
                              ...provenanceStyle(bullet.source),
                              opacity: bullet.decision === "discarded" ? 0.45 : 1,
                              textDecoration:
                                bullet.decision === "discarded" ? "line-through" : undefined,
                            }}
                          >
                            <span className="flex items-start justify-between gap-3">
                              <span className="min-w-0">{describe(bullet).primary}</span>
                              <span className="flex shrink-0 items-center gap-2">
                                <ConfidenceMeter value={bullet.confidence} />
                                <button
                                  className="text-xs underline underline-offset-2"
                                  style={{ color: "var(--muted)" }}
                                  onClick={() =>
                                    void decide(
                                      bullet,
                                      bullet.decision === "discarded" ? "accepted" : "discarded",
                                    )
                                  }
                                >
                                  {bullet.decision === "discarded" ? "Keep" : "Discard"}
                                </button>
                              </span>
                            </span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

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
