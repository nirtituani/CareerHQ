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
  });
});
