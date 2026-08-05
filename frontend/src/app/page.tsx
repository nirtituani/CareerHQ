export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold tracking-tight text-brand-700">
        CareerHQ
      </h1>
      <p className="text-sm" style={{ color: "var(--muted)" }}>
        Your AI-powered headquarters for every job application.
      </p>
    </main>
  );
}
