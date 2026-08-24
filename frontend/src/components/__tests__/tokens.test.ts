import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * Every `var(--token)` a component names must actually exist.
 *
 * A misspelled custom property does not throw, does not warn, and does not fail
 * a build. The declaration is simply invalid at computed-value time, so the
 * property falls back — and what it falls back *to* decides whether anyone
 * notices.
 *
 * `var(--fg)` was written for `--foreground` in four places. Three were
 * `color:`, which inherits, so they rendered correctly by accident and nothing
 * suggested a problem. The fourth was `fill:` on SVG text, which has no
 * inherited value to land on and fell to its initial: **black text on a dark
 * ground**, in the middle of the score ring.
 *
 * So three of the four were invisible, and the visible one only surfaced
 * because a person looked at it. Hence a test rather than a convention.
 */
function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return walk(path);
    return /\.(tsx?|css)$/.test(entry) ? [path] : [];
  });
}

describe("design tokens", () => {
  it("are all defined before they are used", () => {
    const src = resolve(__dirname, "../..");
    const css = readFileSync(join(src, "app", "globals.css"), "utf8");

    const defined = new Set(Array.from(css.matchAll(/^\s*(--[\w-]+)\s*:/gm), (m) => m[1]));

    const used = new Map<string, string[]>();
    for (const file of walk(src)) {
      // Tests name tokens in prose; only real components are scanned.
      if (file.endsWith("globals.css") || file.includes("__tests__")) continue;
      const contents = readFileSync(file, "utf8");
      for (const [, token] of contents.matchAll(/var\((--[\w-]+)/g)) {
        // Tailwind supplies its own `--tw-*` and `--spacing`-style internals.
        if (token.startsWith("--tw-")) continue;
        used.set(token, [...(used.get(token) ?? []), file.replace(src, "")]);
      }
    }

    const missing = [...used.entries()]
      .filter(([token]) => !defined.has(token))
      .map(([token, files]) => `${token} — used in ${[...new Set(files)].join(", ")}`);

    expect(missing).toEqual([]);

    // T071. The walk is the whole test, and a walk that silently stopped
    // finding files would report zero missing tokens and pass — the same
    // vacuous-gate failure the route enumeration in `test_auth.py` shipped for
    // two slices. Naming the newest components is what makes this scan provably
    // about them rather than about whatever it happened to reach.
    const scanned = [...used.values()].flat();
    for (const component of ["tailor-tab.tsx", "tailor-diff-item.tsx"]) {
      expect(
        scanned.some((file) => file.endsWith(component)),
        `${component} names no design token; either it was not scanned or it is styling itself off-system`,
      ).toBe(true);
    }
  });
});

/**
 * Every Tailwind theme colour a component names must exist in `@theme`.
 *
 * The same failure as above, one layer out, and it had been shipping for three
 * slices. `src/components/ui/` is shadcn, written against a fixed vocabulary —
 * `bg-primary`, `bg-accent`, `border-input`, `ring-ring`. None of those names
 * were declared here, and **Tailwind does not warn about a colour it has never
 * heard of**: it simply generates no rule. `bg-primary` computed to
 * `rgba(0, 0, 0, 0)`, so all twenty default `<Button>`s in the application
 * rendered as bare text with no fill.
 *
 * It survived a passing build, a passing type check, a passing lint, 130
 * passing tests and the `var(--token)` scan above — because none of them look
 * at whether a class name resolves. It was found by opening the Tailor tab in a
 * browser and noticing the primary action did not look like a button, which is
 * how every display defect in this project has been found.
 *
 * The `outline` and `ghost` variants are why nobody caught it sooner: both are
 * *meant* to be transparent, so two of the three variants looked perfect and
 * the third read as a text link rather than as anything broken.
 */
describe("Tailwind theme colours", () => {
  it("are all declared before they are used", () => {
    const src = resolve(__dirname, "../..");
    const css = readFileSync(join(src, "app", "globals.css"), "utf8");

    // Both blocks: `@theme` for fixed palettes, `@theme inline` for names that
    // resolve through a var() which changes under the dark-mode media query.
    const declared = new Set(
      Array.from(css.matchAll(/^\s*--color-([\w-]+)\s*:/gm), (match) => match[1]),
    );

    // Only the semantic names. The brand ramp and outcome colours are declared
    // in the same place and would be caught by the same rule, but spelling out
    // the utility prefixes keeps this from matching arbitrary class names that
    // merely look like colours (`text-sm`, `border-b`).
    const utility =
      /\b(?:bg|text|border|ring|fill|stroke|divide|outline|shadow|from|via|to|caret|accent|decoration|placeholder)-((?:primary|secondary|accent|destructive|popover|card|muted|background|foreground|input|ring)(?:-foreground)?)\b/g;

    const used = new Map<string, string[]>();
    for (const file of walk(src)) {
      if (file.endsWith("globals.css") || file.includes("__tests__")) continue;
      for (const [, name] of readFileSync(file, "utf8").matchAll(utility)) {
        used.set(name, [...(used.get(name) ?? []), file.replace(src, "")]);
      }
    }

    // `ring` and `border` alone are width utilities, not colours; the regex
    // above only matches them when a semantic colour name follows.
    const missing = [...used.entries()]
      .filter(([name]) => !declared.has(name))
      .map(([name, files]) => `--color-${name} — used in ${[...new Set(files)].join(", ")}`);

    expect(missing).toEqual([]);
    // A guard with nothing to examine passes forever, which is exactly what the
    // scan above did for three slices. `ui/` alone names half a dozen.
    expect(used.size).toBeGreaterThan(8);
  });
});
