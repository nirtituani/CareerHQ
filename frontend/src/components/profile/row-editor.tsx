"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { EDITABLE_FIELDS } from "@/lib/imports";

/**
 * Correct one fact already in the profile.
 *
 * Uses the same field definitions as the import review, so a job title is
 * edited the same way whether it is being reviewed or repaired. Saving marks
 * the item `user_corrected`, which is what stops a later import from
 * overwriting it.
 */
export function RowEditor({
  kind,
  id,
  values,
  onDone,
}: {
  kind: string;
  id: string;
  values: Record<string, unknown>;
  onDone: () => void;
}) {
  const router = useRouter();
  const fields = EDITABLE_FIELDS[kind] ?? [];
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(fields.map((f) => [f.key, String(values[f.key] ?? "")])),
  );
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    const body = Object.fromEntries(
      fields.map((f) => [f.key, draft[f.key]?.trim() ? draft[f.key].trim() : null]),
    );
    const response = await fetch(`/api/profile/${kind}/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    setBusy(false);
    if (response.ok) {
      onDone();
      router.refresh();
    }
  }

  return (
    <div className="mt-2 space-y-2 rounded-md p-3" style={{ background: "var(--surface-sunken)" }}>
      {fields.map((field) => (
        <label key={field.key} className="block">
          <span className="text-xs" style={{ color: "var(--faint)" }}>
            {field.label}
          </span>
          {field.multiline ? (
            <textarea
              rows={3}
              value={draft[field.key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
              className="mt-0.5 w-full rounded-md border px-2 py-1 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}
            />
          ) : (
            <input
              value={draft[field.key] ?? ""}
              onChange={(e) => setDraft((d) => ({ ...d, [field.key]: e.target.value }))}
              className="mt-0.5 w-full rounded-md border px-2 py-1 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}
            />
          )}
        </label>
      ))}

      <div className="flex gap-2 pt-1">
        <Button size="sm" disabled={busy} onClick={() => void save()}>
          {busy ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
