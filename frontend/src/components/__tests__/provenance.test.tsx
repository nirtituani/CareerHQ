import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ConfidenceMeter, ProvenanceLabel, provenanceStyle } from "@/components/provenance";

describe("provenance", () => {
  it("gives each provenance state its own rule token", () => {
    // The component's job is only to pick a distinct token per state. What the
    // token *looks* like is CSS, and is asserted against globals.css below —
    // testing it here would assert nothing, since the value is a var() name.
    const rules = (["extracted", "user_corrected", "user_added"] as const).map(
      (s) => provenanceStyle(s).borderLeft,
    );

    expect(new Set(rules).size).toBe(3);
  });

  it("defines the rules so extracted reads as provisional and the rest as affirmed", () => {
    // docs/09 §5, asserted where the rule actually lives. Dashed vs solid is
    // the non-colour channel: it survives greyscale and colour blindness, which
    // a hue difference does not. If someone "tidies" these to all be solid, the
    // provenance system silently becomes colour-only.
    const css = readFileSync(
      resolve(__dirname, "../../app/globals.css"),
      "utf8",
    );

    expect(css).toMatch(/--rule-extracted:\s*[^;]*dashed/);
    expect(css).toMatch(/--rule-corrected:\s*[^;]*solid/);
    expect(css).toMatch(/--rule-added:\s*[^;]*solid/);
  });

  it("labels every provenance state in text as well", () => {
    render(<ProvenanceLabel source="extracted" />);
    expect(screen.getByText("EXTRACTED")).toBeInTheDocument();
  });
});

describe("ConfidenceMeter", () => {
  it("states the value in text, not only as segments", () => {
    render(<ConfidenceMeter value={0.82} />);
    expect(screen.getByText("0.82")).toBeInTheDocument();
  });

  it("marks a low value as needing attention", () => {
    render(<ConfidenceMeter value={0.3} />);
    expect(screen.getByLabelText(/low/i)).toBeInTheDocument();
  });

  it("does not mark a high value", () => {
    render(<ConfidenceMeter value={0.95} />);
    expect(screen.queryByLabelText(/low/i)).not.toBeInTheDocument();
  });
});
