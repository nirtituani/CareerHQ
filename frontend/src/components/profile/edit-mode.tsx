"use client";

import { createContext, useContext, useState } from "react";

/**
 * Whether the profile is being edited.
 *
 * A mode rather than permanently visible controls. The profile is read far more
 * often than it is changed, and a Remove button on every one of sixty rows
 * makes the common case noisier to serve the rare one — and puts a destructive
 * action one stray click away from someone who only came to look.
 */
const EditModeContext = createContext<{ editing: boolean; toggle: () => void }>({
  editing: false,
  toggle: () => {},
});

export function useEditMode() {
  return useContext(EditModeContext);
}

export function EditModeProvider({ children }: { children: React.ReactNode }) {
  const [editing, setEditing] = useState(false);
  return (
    <EditModeContext.Provider value={{ editing, toggle: () => setEditing((e) => !e) }}>
      {children}
    </EditModeContext.Provider>
  );
}

export function EditModeToggle() {
  const { editing, toggle } = useEditMode();
  return (
    <button
      onClick={toggle}
      aria-pressed={editing}
      className="text-sm underline underline-offset-4"
      style={{ color: editing ? "var(--color-brand-600)" : "var(--muted)" }}
    >
      {editing ? "Done editing" : "Edit profile"}
    </button>
  );
}
