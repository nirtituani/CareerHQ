"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ItemActions } from "@/components/import-review/item-actions";
import { ItemEditor } from "@/components/import-review/item-editor";
import { ConfidenceMeter, LOW_CONFIDENCE, provenanceStyle } from "@/components/provenance";
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
  const [editing, setEditing] = useState<string | null>(null);

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

  const correct = useCallback(
    async (item: ExtractionItem, payload: Record<string, unknown>) => {
      // Optimistic, and it flips provenance locally too: the label changing
      // from EXTRACTED to CORRECTED is the feedback that the edit took.
      setItems((prev) =>
        prev.map((i) =>
          i.id === item.id ? { ...i, payload, source: "user_corrected" as const } : i,
        ),
      );
      setEditing(null);
      await onPatch(item.id, { payload });
    },
    [onPatch],
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
      } else if (event.key === "e") {
        event.preventDefault();
        setEditing(item.id);
      }
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, decide, visible]);

  const alreadyPresent = items.filter((i) => i.already_present).length;
  const isRepeat = alreadyPresent > 0;
  const newItems = items.filter((i) => !i.already_present);
  //: Explicitly added items narrow approval to those; otherwise everything not
  //: discarded is added. The button names whichever applies, so the mode is
  //: read rather than inferred.
  const selected = items.filter((i) => i.decision === "accepted").length;
  const willAdd = selected > 0 ? selected : items.filter((i) => i.decision !== "discarded").length;

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
                  {isRepeat
                    ? `${inSection.filter((i) => !i.already_present).length} new`
                    : `${done}/${inSection.length}`}
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
              <li key={category ?? "uncategorised"} className="pt-2 first:pt-0">
                {category && (
                  <p
                    className="mb-1 text-xs tracking-wider uppercase"
                    style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
                  >
                    {category}
                  </p>
                )}
                <ul className="space-y-1">
                  {group.map((item) => (
                    <li
                      key={item.id}
                      className="py-1 text-sm"
                      style={{
                        ...provenanceStyle(item.source),
                        opacity: item.decision === "discarded" ? 0.45 : 1,
                      }}
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span
                          className="min-w-0"
                          style={{
                            textDecoration:
                              item.decision === "discarded" ? "line-through" : undefined,
                          }}
                        >
                          {describe(item).primary}
                        </span>
                        <ItemActions
                          item={item}
                          isRepeat={isRepeat}
                          onDecide={(decision) => void decide(item, decision)}
                          onEdit={() => setEditing(editing === item.id ? null : item.id)}
                        />
                      </span>
                      {editing === item.id && (
                        <ItemEditor
                          item={item}
                          onSave={(payload) => correct(item, payload)}
                          onCancel={() => setEditing(null)}
                        />
                      )}
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
                  opacity:
                    item.decision === "discarded" ? 0.45 : item.already_present ? 0.55 : 1,
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
                    {editing === item.id && (
                      <ItemEditor
                        item={item}
                        onSave={(payload) => correct(item, payload)}
                        onCancel={() => setEditing(null)}
                      />
                    )}

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
                                    setEditing(editing === bullet.id ? null : bullet.id)
                                  }
                                >
                                  Edit
                                </button>
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
                            {editing === bullet.id && (
                              <ItemEditor
                                item={bullet}
                                onSave={(payload) => correct(bullet, payload)}
                                onCancel={() => setEditing(null)}
                              />
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <ItemActions
                    item={item}
                    isRepeat={isRepeat}
                    onDecide={(decision) => void decide(item, decision)}
                    onEdit={() => setEditing(editing === item.id ? null : item.id)}
                  />
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
          {isRepeat ? (
            <>
              <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
                {alreadyPresent}
              </span>{" "}
              already in your profile ·{" "}
              <span
                className="tabular"
                style={{ fontFamily: "var(--font-mono)", color: "var(--foreground)" }}
              >
                {newItems.length}
              </span>{" "}
              new
            </>
          ) : (
            <>
              <span className="tabular" style={{ fontFamily: "var(--font-mono)" }}>
                {reviewed} of {items.length}
              </span>{" "}
              reviewed
            </>
          )}
          {attention > 0 && (
            <>
              {" · "}
              <span style={{ color: "var(--color-attention)" }}>
                {attention} need attention
              </span>
            </>
          )}
          <span className="ml-3 text-xs" style={{ color: "var(--faint)" }}>
            A keep · E edit · D discard · J/K move
          </span>
        </p>

        <Button
          disabled={!anyAccepted || busy}
          onClick={() => {
            setBusy(true);
            void onApprove().finally(() => setBusy(false));
          }}
        >
          {busy
            ? "Adding to profile…"
            : selected > 0
              ? `Add ${willAdd} selected to my profile`
              : `Add ${willAdd} to my profile`}
        </Button>
      </div>
    </div>
  );
}
