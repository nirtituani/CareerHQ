import Link from "next/link";

import { SidebarNav } from "@/components/sidebar-nav";
import { UserMenu } from "@/components/user-menu";
import type { User } from "@/lib/api";

/**
 * The application frame: a fixed left sidebar and a scrolling main column.
 *
 * Structure follows docs/09_Design_Language.md §6.0. The navigation is a client
 * component because it needs the current path to mark the active item; keeping
 * that split means this shell stays a server component and the user is still
 * resolved on the server.
 *
 * The user menu is rendered exactly once. Putting a copy in both the sidebar
 * and a mobile header would duplicate it in the DOM — visually hidden by a
 * breakpoint class, but still there for assistive technology and still a second
 * element with the same accessible name.
 */
export function AppShell({ user, children }: { user: User; children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen">
      <aside
        className="hidden w-60 shrink-0 flex-col border-r p-3 sm:flex"
        style={{ borderColor: "var(--border)" }}
      >
        <Link
          href="/dashboard"
          className="mb-4 px-3 py-2 text-lg tracking-tight text-brand-700"
          style={{ fontFamily: "var(--font-display)" }}
        >
          CareerHQ
        </Link>

        <SidebarNav />
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header
          className="flex h-14 shrink-0 items-center justify-between border-b px-4 sm:justify-end sm:px-6"
          style={{ borderColor: "var(--border)" }}
        >
          {/* The wordmark lives here only while the sidebar is hidden. */}
          <Link
            href="/dashboard"
            className="text-brand-700 sm:hidden"
            style={{ fontFamily: "var(--font-display)" }}
          >
            CareerHQ
          </Link>

          <UserMenu user={user} />
        </header>

        <main className="min-w-0 flex-1 px-4 py-8 sm:px-6">{children}</main>
      </div>
    </div>
  );
}
