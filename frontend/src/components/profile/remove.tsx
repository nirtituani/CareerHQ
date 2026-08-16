"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Removing something from the profile.
 *
 * Deletion is permanent, so it asks first — but only once, and inline. A modal
 * for removing one skill would cost more attention than the action deserves,
 * while no confirmation at all makes a mis-click destructive on a screen whose
 * rows are one line tall.
 */
export function RemoveItem({ kind, id, label }: { kind: string; id: string; label: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    const response = await fetch(`/api/profile/${kind}/${id}`, { method: "DELETE" });
    setBusy(false);
    if (response.ok) router.refresh();
  }

  if (!confirming) {
    return (
      <button
        aria-label={`Remove ${label}`}
        onClick={() => setConfirming(true)}
        className="text-xs underline underline-offset-2 opacity-0 transition-opacity group-hover:opacity-100 focus:opacity-100"
        style={{ color: "var(--muted)" }}
      >
        Remove
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2 text-xs">
      <span style={{ color: "var(--muted)" }}>Remove?</span>
      <button
        disabled={busy}
        onClick={() => void remove()}
        className="underline underline-offset-2"
        style={{ color: "var(--color-failure)" }}
      >
        {busy ? "Removing…" : "Yes"}
      </button>
      <button
        onClick={() => setConfirming(false)}
        className="underline underline-offset-2"
        style={{ color: "var(--muted)" }}
      >
        Cancel
      </button>
    </span>
  );
}

/**
 * Clearing a whole section.
 *
 * Exists for the case that motivated it — a section parsed badly enough that
 * removing twenty-two entries one at a time is not a realistic repair. It names
 * the count in the confirmation, because "clear this section" and "delete 22
 * things" are the same action described at two different levels of honesty.
 */
export function RemoveSection({
  kind,
  title,
  count,
}: {
  kind: string;
  title: string;
  count: number;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  async function remove() {
    setBusy(true);
    const response = await fetch(`/api/profile/${kind}`, { method: "DELETE" });
    setBusy(false);
    if (response.ok) router.refresh();
  }

  if (!confirming) {
    return (
      <button
        aria-label={`Clear ${title}`}
        onClick={() => setConfirming(true)}
        className="text-xs underline underline-offset-2"
        style={{ color: "var(--faint)" }}
      >
        Clear section
      </button>
    );
  }

  return (
    <span className="flex items-center gap-2 text-xs">
      <span style={{ color: "var(--muted)" }}>
        Remove all {count} from {title}?
      </span>
      <button
        disabled={busy}
        onClick={() => void remove()}
        className="underline underline-offset-2"
        style={{ color: "var(--color-failure)" }}
      >
        {busy ? "Removing…" : "Yes"}
      </button>
      <button
        onClick={() => setConfirming(false)}
        className="underline underline-offset-2"
        style={{ color: "var(--muted)" }}
      >
        Cancel
      </button>
    </span>
  );
}
