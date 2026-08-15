"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { EDITABLE_FIELDS, type ExtractionItem } from "@/lib/imports";

/**
 * Correct one extracted item.
 *
 * Saving marks it `user_corrected`, which is the only way that provenance state
 * is ever reached — and therefore the only way the profile can distinguish a
 * fact a person checked from one the model produced and nobody read.
 *
 * The original value is not shown alongside the field on purpose: the field
 * *is* the original until it is changed, and a diff view here would add noise
 * to a screen already dense with dozens of items.
 */
export function ItemEditor({
  item,
  onSave,
  onCancel,
}: {
  item: ExtractionItem;
  onSave: (payload: Record<string, unknown>) => Promise<void>;
  onCancel: () => void;
}) {
  const fields = EDITABLE_FIELDS[item.kind] ?? [];
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      fields.map((field) => [field.key, String(item.payload[field.key] ?? "")]),
    ),
  );
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    // Everything the item already carried is preserved — links, is_current and
    // confidence are not editable here, and dropping them would lose data the
    // extraction got right.
    const payload: Record<string, unknown> = { ...item.payload };
    for (const field of fields) {
      const value = values[field.key]?.trim();
      payload[field.key] = value ? value : null;
    }
    await onSave(payload);
    setSaving(false);
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
              value={values[field.key] ?? ""}
              onChange={(event) =>
                setValues((v) => ({ ...v, [field.key]: event.target.value }))
              }
              className="mt-0.5 w-full rounded-md border px-2 py-1 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}
            />
          ) : (
            <input
              value={values[field.key] ?? ""}
              onChange={(event) =>
                setValues((v) => ({ ...v, [field.key]: event.target.value }))
              }
              className="mt-0.5 w-full rounded-md border px-2 py-1 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--surface)" }}
            />
          )}
        </label>
      ))}

      <div className="flex gap-2 pt-1">
        <Button size="sm" disabled={saving} onClick={() => void save()}>
          {saving ? "Saving…" : "Save correction"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
