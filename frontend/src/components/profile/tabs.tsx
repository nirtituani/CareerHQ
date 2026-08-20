"use client";

/**
 * Two views of the same career: what the system holds, and what you sent.
 *
 * The structured profile is first and is the default, because it is what
 * everything downstream reads — tailoring, scoring, the advisor. The original
 * sits beside it as a reference, not as an alternative source of truth
 * (ADR-013).
 */

import { Tabs } from "radix-ui";

export function ProfileTabs({
  profile,
  original,
}: {
  profile: React.ReactNode;
  original: React.ReactNode;
}) {
  return (
    <Tabs.Root defaultValue="profile">
      <Tabs.List
        className="mb-2 flex gap-1 border-b"
        style={{ borderColor: "var(--border)" }}
        aria-label="Profile views"
      >
        {[
          { value: "profile", label: "Profile" },
          { value: "original", label: "Original CV" },
        ].map(({ value, label }) => (
          <Tabs.Trigger
            key={value}
            value={value}
            className="border-b-2 border-transparent px-3 py-2.5 text-sm whitespace-nowrap transition-colors data-[state=active]:border-[var(--color-brand-600)] data-[state=active]:font-medium"
            style={{ color: "var(--muted)" }}
          >
            {label}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      <Tabs.Content value="profile" className="outline-none">
        {profile}
      </Tabs.Content>
      <Tabs.Content value="original" className="outline-none">
        {original}
      </Tabs.Content>
    </Tabs.Root>
  );
}
