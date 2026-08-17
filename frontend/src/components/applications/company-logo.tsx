"use client";

import { useState } from "react";

/**
 * The company mark in the applications table.
 *
 * Logic carried from the source app's `CompanyLogo` (`ApplicationTable.jsx`):
 * logo.dev keyed by domain, the domain guessed from the company name when none
 * was entered, and the mark links to a LinkedIn company search. Two changes:
 *
 * **The token comes from the environment.** The source hardcodes it at
 * `ApplicationTable.jsx:4` in a public repository, where anyone can lift it and
 * spend the quota. It is a *publishable* token — it necessarily travels in the
 * image URL, so the browser sees it and that is fine — but published in the URL
 * and committed to public source are not the same thing.
 *
 * **A failed load falls back to initials, not to nothing.** The source hides
 * the image `onError`, which leaves the column ragged: some rows indented by a
 * logo, others not. An initial keeps the row rhythm and still identifies the
 * company.
 */
const TOKEN = process.env.NEXT_PUBLIC_LOGO_DEV_TOKEN;

/** Strip scheme and `www.`, exactly as the source app does. */
function extractDomain(value: string): string {
  const trimmed = value.trim();
  try {
    return new URL(trimmed.includes("//") ? trimmed : `https://${trimmed}`).hostname.replace(
      /^www\./,
      "",
    );
  } catch {
    return trimmed
      .replace(/^https?:\/\//, "")
      .replace(/^www\./, "")
      .split("/")[0];
  }
}

function Initial({ company }: { company: string }) {
  return (
    <span
      aria-hidden
      className="flex size-5 shrink-0 items-center justify-center rounded-sm text-[10px] font-semibold"
      style={{ background: "var(--surface-sunken)", color: "var(--muted)" }}
    >
      {company.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}

export function CompanyLogo({
  company,
  domain,
}: {
  company: string;
  domain: string | null;
}) {
  const [failed, setFailed] = useState(false);

  // Guessing `acme.com` from "Acme" is wrong often enough that the guess must
  // fail gracefully — which is what the initials fallback is for.
  const resolved = domain ? extractDomain(domain) : `${company.toLowerCase().replace(/\s+/g, "")}.com`;

  const mark =
    TOKEN && !failed ? (
      // eslint-disable-next-line @next/next/no-img-element -- a third-party
      // logo endpoint, not an asset Next can optimise; next/image would need a
      // remotePatterns entry per provider for no benefit here.
      <img
        src={`https://img.logo.dev/${resolved}?token=${TOKEN}&size=40`}
        alt=""
        width={20}
        height={20}
        loading="lazy"
        className="size-5 shrink-0 rounded-sm object-contain"
        onError={() => setFailed(true)}
      />
    ) : (
      <Initial company={company} />
    );

  return (
    <a
      href={`https://www.linkedin.com/search/results/companies/?keywords=${encodeURIComponent(company)}`}
      target="_blank"
      rel="noreferrer noopener"
      title={`${company} on LinkedIn`}
      className="shrink-0 transition-opacity hover:opacity-70"
    >
      {mark}
    </a>
  );
}
