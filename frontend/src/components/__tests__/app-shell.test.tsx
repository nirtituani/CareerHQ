import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/app-shell";
import type { User } from "@/lib/api";

const USER: User = {
  id: "0198f2c1-0000-0000-0000-000000000000",
  email: "nir@example.com",
  display_name: "Nir Tituani",
  avatar_url: null,
  created_at: "2026-08-06T09:00:00Z",
};

describe("AppShell", () => {
  it("shows the signed-in identity", () => {
    render(
      <AppShell user={USER}>
        <p>content</p>
      </AppShell>,
    );

    expect(screen.getByText("Nir Tituani")).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("falls back to the email when no display name is set", () => {
    render(
      <AppShell user={{ ...USER, display_name: null }}>
        <p>content</p>
      </AppShell>,
    );

    expect(screen.getByText("nir@example.com")).toBeInTheDocument();
  });

  it("marks sections that are not built yet as disabled rather than hiding them", () => {
    // Showing where the product is going is deliberate. The original version of
    // this test said "if these ever become real links, update it — do not
    // delete it", and slice 003 is when that happened: Applications and Profile
    // are now built, and Resumes was replaced by the destinations in
    // docs/09 §6.0.
    render(
      <AppShell user={USER}>
        <p>content</p>
      </AppShell>,
    );

    for (const [label, href] of [
      ["Dashboard", "/dashboard"],
      ["Applications", "/applications"],
      ["Profile", "/profile"],
      // Live since slice 009 — the Soon marker came off in the same slice
      // that built the page behind it (the stale-marker rule).
      ["Career Advisor", "/advisor"],
    ] as const) {
      expect(screen.getByRole("link", { name: label })).toHaveAttribute("href", href);
    }

    for (const label of ["CV Builder", "Settings"]) {
      const item = screen.getByText(label).closest("[aria-disabled]");
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(item?.tagName).not.toBe("A");
    }
  });

  it("renders the user menu exactly once", () => {
    // A sidebar copy plus a mobile-header copy would be hidden by a breakpoint
    // class and still present for assistive technology — two elements with the
    // same accessible name. This caught that during slice 003.
    render(
      <AppShell user={USER}>
        <p>content</p>
      </AppShell>,
    );

    expect(screen.getAllByText("Nir Tituani")).toHaveLength(1);
  });
});
