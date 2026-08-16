"use client";

import { useEditMode } from "@/components/profile/edit-mode";
import { RemoveSection } from "@/components/profile/remove";

export function ProfileSection({
  title,
  kind,
  count,
  children,
}: {
  title: string;
  kind: string;
  count: number;
  children: React.ReactNode;
}) {
  const { editing } = useEditMode();

  return (
    <section className="mb-8">
      <div className="mb-2 flex items-baseline justify-between gap-4">
        <h2 className="text-lg" style={{ fontFamily: "var(--font-display)" }}>
          {title}
        </h2>
        {editing && <RemoveSection kind={kind} title={title} count={count} />}
      </div>
      <ul className="space-y-1">{children}</ul>
    </section>
  );
}
