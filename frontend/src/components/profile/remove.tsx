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

/**
 * Emptying the whole profile.
 *
 * Confirmed harder than the others on purpose. Removing one skill is a small
 * correction; this discards everything the user reviewed and approved, and the
 * only way back is to import again and re-review. So it states the total, and
 * asks for a typed confirmation rather than a second click — a click can be
 * muscle memory, typing a word cannot.
 */
export function ClearProfile({ total }: { total: number }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);

  const CONFIRM = "clear";

  async function clear() {
    setBusy(true);
    const response = await fetch("/api/profile/content", { method: "DELETE" });
    setBusy(false);
    if (response.ok) {
      setOpen(false);
      setTyped("");
      router.refresh();
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-xs underline underline-offset-2"
        style={{ color: "var(--muted)" }}
      >
        Clear my profile
      </button>
    );
  }

  return (
    <div
      role="alertdialog"
      aria-label="Clear profile"
      className="rounded-md py-3 pr-4 text-sm"
      style={{ borderLeft: "2px solid var(--color-failure)", paddingLeft: "0.75rem" }}
    >
      <p className="font-medium">Remove all {total} items from your profile?</p>
      <p className="mt-1" style={{ color: "var(--muted)" }}>
        Your account stays. Your imports stay, so you can see what you uploaded — but everything
        you approved into your profile goes, including any corrections you made. The only way
        back is to import again and review it again.
      </p>

      <label className="mt-3 block">
        <span className="text-xs" style={{ color: "var(--faint)" }}>
          Type <strong>{CONFIRM}</strong> to confirm
        </span>
        <input
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          className="mt-1 w-40 rounded-md border px-2 py-1 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--surface)" }}
        />
      </label>

      <div className="mt-3 flex gap-3 text-xs">
        <button
          disabled={typed.trim().toLowerCase() !== CONFIRM || busy}
          onClick={() => void clear()}
          className="underline underline-offset-2 disabled:opacity-40"
          style={{ color: "var(--color-failure)" }}
        >
          {busy ? "Clearing…" : "Clear my profile"}
        </button>
        <button
          onClick={() => {
            setOpen(false);
            setTyped("");
          }}
          className="underline underline-offset-2"
          style={{ color: "var(--muted)" }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
