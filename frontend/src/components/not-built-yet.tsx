/**
 * "Not built yet" — one of the three empty states in docs/09 §5.
 *
 * It must never be mistaken for *failed* or for *empty data*. Conflating those
 * is the recurring failure in tools like this: a panel that is simply not
 * finished should not alarm anyone, and a CV that could not be read must not
 * quietly look like a CV containing nothing.
 */
export function NotBuiltYet({ title, arrives }: { title: string; arrives: string }) {
  return (
    <div
      className="rounded-lg border border-dashed p-6 text-sm"
      style={{ borderColor: "var(--border-strong)", color: "var(--muted)" }}
    >
      <p className="font-medium" style={{ color: "var(--foreground)" }}>
        {title}
      </p>
      <p className="mt-1">{arrives}</p>
    </div>
  );
}
