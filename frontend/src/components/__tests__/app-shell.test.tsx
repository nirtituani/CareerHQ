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
    // Showing where the product is going is deliberate. If these ever become
    // real links, this test should be updated — not deleted.
    render(
      <AppShell user={USER}>
        <p>content</p>
      </AppShell>,
    );

    expect(screen.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/dashboard");

    for (const label of ["Applications", "Profile", "Resumes"]) {
      const item = screen.getByText(label);
      expect(item).toHaveAttribute("aria-disabled", "true");
      expect(item.tagName).not.toBe("A");
    }
  });
});
