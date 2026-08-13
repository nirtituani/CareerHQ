import type { Metadata } from "next";
import { Fraunces, IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import "./globals.css";

/*
 * Three faces, three jobs — see docs/09_Design_Language.md §2.
 *
 * Each exposes a CSS variable that globals.css maps to a role. The variables
 * carry inline fallbacks there, so a font that fails to load degrades to a
 * system face rather than dropping font-family entirely.
 */

/** Display. Page titles, the wordmark, stat figures — used sparingly, because
 *  it supplies the warmth in a tool that is otherwise about records. */
const fraunces = Fraunces({
  subsets: ["latin"],
  variable: "--font-fraunces",
  display: "swap",
});

/** The workhorse. Drawn for technical work and legible at the small sizes a
 *  96-row table needs. */
const plexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

/** Data quoted verbatim: dates, ids, confidence values, provenance labels.
 *  The typeface is doing semantic work, not decoration. */
const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CareerHQ",
  description: "Your AI-powered headquarters for every job application.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${fraunces.variable} ${plexSans.variable} ${plexMono.variable}`}
    >
      <body>{children}</body>
    </html>
  );
}
