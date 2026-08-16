"use client";

import { useState } from "react";

import { useEditMode } from "@/components/profile/edit-mode";
import { RemoveItem } from "@/components/profile/remove";
import { RowEditor } from "@/components/profile/row-editor";
import { ProvenanceLabel, type Source, provenanceStyle } from "@/components/provenance";

/**
 * One fact in the profile, with its provenance and — in edit mode — the
 * controls to correct or remove it.
 *
 * Provenance stays visible in both modes: FR-004 requires the distinction
 * between a verified fact and unverified extraction to persist after approval,
 * and hiding it outside edit mode would make it a feature of editing rather
 * than a property of the data.
 */
export function ProfileEntry({
  source,
  kind,
  id,
  label,
  values,
  children,
}: {
  source: Source;
  kind: string;
  id: string;
  label: string;
  values: Record<string, unknown>;
  children: React.ReactNode;
}) {
  const { editing } = useEditMode();
  const [open, setOpen] = useState(false);

  return (
    <li className="py-1.5" style={provenanceStyle(source)}>
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0 text-sm">{children}</div>
        <div className="flex shrink-0 items-center gap-3">
          <ProvenanceLabel source={source} />
          {editing && (
            <>
              <button
                aria-label={`Edit ${label}`}
                onClick={() => setOpen((o) => !o)}
                className="text-xs underline underline-offset-2"
                style={{ color: "var(--muted)" }}
              >
                Edit
              </button>
              <RemoveItem kind={kind} id={id} label={label} />
            </>
          )}
        </div>
      </div>

      {editing && open && (
        <RowEditor kind={kind} id={id} values={values} onDone={() => setOpen(false)} />
      )}
    </li>
  );
}
