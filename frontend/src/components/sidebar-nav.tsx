"use client";

import {
  BarChart3,
  FileText,
  LayoutDashboard,
  Settings,
  Sparkles,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The six destinations from docs/09_Design_Language.md §6.0.
 *
 * `ready: false` items are shown rather than hidden, and marked rather than
 * broken. That is §5's three-empty-states rule applied to navigation: a
 * capability that is *not built yet* must never read as *failed*, and hiding it
 * entirely would leave the user unable to see where the product is going.
 *
 * Profile is deliberately separate from CV Builder. They share a data model and
 * nothing else — Profile holds career data populated by import and corrected by
 * hand, while CV Builder is the guided from-scratch composer ADR-013 defers.
 */
const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, ready: true },
  { href: "/applications", label: "Applications", icon: FileText, ready: true },
  { href: "/profile", label: "Profile", icon: UserRound, ready: true },
  { href: "/advisor", label: "Career Advisor", icon: BarChart3, ready: false },
  { href: "/builder", label: "CV Builder", icon: Sparkles, ready: false },
  { href: "/settings", label: "Settings", icon: Settings, ready: false },
] as const;

export function SidebarNav() {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      <p
        className="px-3 pb-2 pt-1 text-xs font-medium tracking-wider uppercase"
        style={{ color: "var(--faint)" }}
      >
        Navigation
      </p>

      {NAV.map(({ href, label, icon: Icon, ready }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);

        if (!ready) {
          return (
            <span
              key={href}
              aria-disabled="true"
              className="flex cursor-default items-center gap-2.5 rounded-md px-3 py-2 text-sm"
              style={{ color: "var(--faint)" }}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="flex-1">{label}</span>
              {/* Marked here rather than discovered on arrival. Reaching a page
                  to learn it does not exist is the experience this avoids. */}
              <span className="text-[10px] tracking-wide uppercase">Soon</span>
            </span>
          );
        }

        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className="flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors"
            style={
              active
                ? { background: "var(--surface)", color: "var(--foreground)", fontWeight: 500 }
                : { color: "var(--muted)" }
            }
          >
            <Icon className="size-4 shrink-0" aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
