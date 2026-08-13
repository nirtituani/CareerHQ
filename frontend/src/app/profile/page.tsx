import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { ProvenanceLabel, type Source, provenanceStyle } from "@/components/provenance";
import { Button } from "@/components/ui/button";
import { ApiUnreachableError, type User } from "@/lib/api";
import { fetchCurrentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type Item = { id: string; source: Source };
type Role = Item & {
  company: string;
  title: string | null;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  bullets: (Item & { text: string })[];
};

type Content = {
  contact: (Item & { full_name: string | null; email: string | null; location: string | null })[];
  titles: (Item & { title: string })[];
  summaries: (Item & { text: string })[];
  work_experience: Role[];
  skills: (Item & { name: string })[];
  education: (Item & { institution: string; qualification: string | null })[];
  certifications: (Item & { name: string; issuer: string | null })[];
  languages: (Item & { name: string; proficiency: string | null })[];
  military_service: (Item & {
    branch: string;
    role: string | null;
    start_date: string | null;
    end_date: string | null;
  })[];
  volunteering: (Item & {
    organisation: string;
    role: string | null;
    start_date: string | null;
    end_date: string | null;
  })[];
  master_resume: { id: string; name: string } | null;
};

async function fetchContent(): Promise<Content> {
  const cookieStore = await cookies();
  const backend = process.env.BACKEND_URL ?? "http://localhost:8000";
  const response = await fetch(`${backend}/api/profile/content`, {
    headers: { cookie: cookieStore.toString() },
    cache: "no-store",
  }).catch((cause) => {
    throw new ApiUnreachableError(cause);
  });
  if (!response.ok) throw new Error(`Unexpected ${response.status} from /api/profile/content`);
  return (await response.json()) as Content;
}

/** Provenance survives into the profile — FR-004 requires it *after* approval. */
function Entry({ source, children }: { source: Source; children: React.ReactNode }) {
  return (
    <li className="py-1.5" style={provenanceStyle(source)}>
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0 text-sm">{children}</div>
        <ProvenanceLabel source={source} />
      </div>
    </li>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-2 text-lg" style={{ fontFamily: "var(--font-display)" }}>
        {title}
      </h2>
      <ul className="space-y-1">{children}</ul>
    </section>
  );
}

export default async function ProfilePage() {
  let user: User | null;
  let content: Content;
  try {
    user = await fetchCurrentUser();
    if (!user) redirect("/login?next=/profile");
    content = await fetchContent();
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }

  const empty =
    content.work_experience.length === 0 &&
    content.skills.length === 0 &&
    content.titles.length === 0;

  return (
    <AppShell user={user}>
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl tracking-tight" style={{ fontFamily: "var(--font-display)" }}>
            Profile
          </h1>
          <p className="mt-1 text-sm" style={{ color: "var(--muted)" }}>
            {content.master_resume
              ? "Everything your tailored resumes are built from."
              : "Your professional knowledge lives here."}
          </p>
        </div>
        {!empty && (
          <Button asChild variant="outline">
            <Link href="/import">Import another CV</Link>
          </Button>
        )}
      </div>

      {empty ? (
        // An empty profile is really an onboarding state: saying "nothing here"
        // and stopping would leave the user to find the import themselves.
        <div
          className="rounded-xl border border-dashed p-10 text-center"
          style={{ borderColor: "var(--border-strong)" }}
        >
          <h2 className="text-base font-medium">Start with the CV you already have</h2>
          <p className="mx-auto mt-2 max-w-md text-sm" style={{ color: "var(--muted)" }}>
            Upload it and review what we read. Nothing is saved to your profile until you say
            so.
          </p>
          <Button className="mt-6" asChild>
            <Link href="/import">Import my CV</Link>
          </Button>
        </div>
      ) : (
        <>
          {content.contact.length > 0 && (
            <Section title="Contact">
              {content.contact.map((c) => (
                <Entry key={c.id} source={c.source}>
                  {[c.full_name, c.email, c.location].filter(Boolean).join(" · ")}
                </Entry>
              ))}
            </Section>
          )}

          {content.titles.length > 0 && (
            <Section title="Titles">
              {content.titles.map((t) => (
                <Entry key={t.id} source={t.source}>
                  {t.title}
                </Entry>
              ))}
            </Section>
          )}

          {content.summaries.length > 0 && (
            <Section title="Summary">
              {content.summaries.map((s) => (
                <Entry key={s.id} source={s.source}>
                  {s.text}
                </Entry>
              ))}
            </Section>
          )}

          {content.work_experience.length > 0 && (
            <Section title="Work experience">
              {content.work_experience.map((role) => (
                <Entry key={role.id} source={role.source}>
                  <p className="font-medium">
                    {[role.title, role.company].filter(Boolean).join(" — ")}
                  </p>
                  <p
                    className="tabular text-xs"
                    style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
                  >
                    {[role.start_date, role.is_current ? "Present" : role.end_date]
                      .filter(Boolean)
                      .join(" – ")}
                  </p>
                  <ul className="mt-1 space-y-1">
                    {role.bullets.map((b) => (
                      <li key={b.id} style={provenanceStyle(b.source)}>
                        {b.text}
                      </li>
                    ))}
                  </ul>
                </Entry>
              ))}
            </Section>
          )}

          {content.skills.length > 0 && (
            <Section title="Skills">
              {content.skills.map((s) => (
                <Entry key={s.id} source={s.source}>
                  {s.name}
                </Entry>
              ))}
            </Section>
          )}

          {content.education.length > 0 && (
            <Section title="Education">
              {content.education.map((e) => (
                <Entry key={e.id} source={e.source}>
                  {[e.qualification, e.institution].filter(Boolean).join(", ")}
                </Entry>
              ))}
            </Section>
          )}

          {content.certifications.length > 0 && (
            <Section title="Certifications">
              {content.certifications.map((c) => (
                <Entry key={c.id} source={c.source}>
                  {[c.name, c.issuer].filter(Boolean).join(" — ")}
                </Entry>
              ))}
            </Section>
          )}

          {content.volunteering.length > 0 && (
            <Section title="Volunteering">
              {content.volunteering.map((v) => (
                <Entry key={v.id} source={v.source}>
                  {[v.role, v.organisation].filter(Boolean).join(" — ")}
                </Entry>
              ))}
            </Section>
          )}

          {content.military_service.length > 0 && (
            <Section title="Military service">
              {content.military_service.map((m) => (
                <Entry key={m.id} source={m.source}>
                  {[m.role, m.branch].filter(Boolean).join(" — ")}
                </Entry>
              ))}
            </Section>
          )}

          {content.languages.length > 0 && (
            <Section title="Languages">
              {content.languages.map((l) => (
                <Entry key={l.id} source={l.source}>
                  {[l.name, l.proficiency].filter(Boolean).join(" — ")}
                </Entry>
              ))}
            </Section>
          )}
        </>
      )}
    </AppShell>
  );
}
