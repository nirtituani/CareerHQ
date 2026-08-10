import Link from "next/link";

import { UserMenu } from "@/components/user-menu";
import type { User } from "@/lib/api";

/** Sections that will exist. Disabled ones show where the product is going. */
const NAV = [
  { href: "/dashboard", label: "Dashboard", ready: true },
  { href: "/applications", label: "Applications", ready: false },
  { href: "/profile", label: "Profile", ready: false },
  { href: "/resumes", label: "Resumes", ready: false },
];

export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b" style={{ borderColor: "var(--border)" }}>
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-4">
          <Link href="/dashboard" className="font-semibold tracking-tight text-brand-700">
            CareerHQ
          </Link>

          <nav className="hidden flex-1 items-center gap-1 sm:flex">
            {NAV.map((item) =>
              item.ready ? (
                <Link
                  key={item.href}
                  href={item.href}
                  className="rounded-md px-3 py-1.5 text-sm hover:bg-brand-50"
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  key={item.href}
                  aria-disabled="true"
                  title="Coming in a later release"
                  className="cursor-not-allowed rounded-md px-3 py-1.5 text-sm opacity-40"
                >
                  {item.label}
                </span>
              ),
            )}
          </nav>

          <div className="ml-auto">
            <UserMenu user={user} />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10">{children}</main>
    </div>
  );
}
