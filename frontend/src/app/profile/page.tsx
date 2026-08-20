import Link from "next/link";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ApiUnavailable } from "@/components/api-unavailable";
import { AppShell } from "@/components/app-shell";
import { EditModeProvider } from "@/components/profile/edit-mode";
import { ProfileEntry } from "@/components/profile/entry";
import { ProfileMenu } from "@/components/profile/profile-menu";
import { OriginalCv } from "@/components/profile/original-cv";
import { ProfileSection } from "@/components/profile/section";
import { ProfileTabs } from "@/components/profile/tabs";
import { type Source, provenanceStyle } from "@/components/provenance";
import { educationLine } from "@/lib/imports";
import { Button } from "@/components/ui/button";
import { ApiUnreachableError, type ImportRecord, type User } from "@/lib/api";
import { fetchCurrentUser, fetchFromApi } from "@/lib/session";

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
  contact: (Item & {
    full_name: string | null;
    email: string | null;
    phone: string | null;
    location: string | null;
    links: string[];
  })[];
  titles: (Item & { title: string })[];
  summaries: (Item & { text: string })[];
  work_experience: Role[];
  skills: (Item & { name: string; category: string | null })[];
  education: (Item & {
    institution: string;
    qualification: string | null;
    field_of_study: string | null;
    start_date: string | null;
    end_date: string | null;
    grade: string | null;
  })[];
  certifications: (Item & { name: string; issuer: string | null; year: string | null })[];
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

export default async function ProfilePage() {
  let user: User | null;
  let content: Content;
  let imports: ImportRecord[] = [];
  try {
    user = await fetchCurrentUser();
    if (!user) redirect("/login?next=/profile");
    content = await fetchContent();
    // Defaulted rather than fatal: a person whose uploads cannot be listed
    // still has a profile to read, and the tab says so for itself.
    imports =
      (await fetchFromApi<{ imports: ImportRecord[] }>("/api/imports"))?.imports ?? [];
  } catch (error) {
    if (error instanceof ApiUnreachableError) return <ApiUnavailable />;
    throw error;
  }

  // Named so the confirmation can state it. "Remove everything" and "remove 61
  // things" are the same action described at two different levels of honesty.
  const totalItems =
    content.contact.length +
    content.titles.length +
    content.summaries.length +
    content.work_experience.length +
    content.work_experience.reduce((n, role) => n + role.bullets.length, 0) +
    content.skills.length +
    content.education.length +
    content.certifications.length +
    content.languages.length +
    content.volunteering.length +
    content.military_service.length;

  const empty =
    content.work_experience.length === 0 &&
    content.skills.length === 0 &&
    content.titles.length === 0;

  return (
    <AppShell user={user}>
      <EditModeProvider>
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
          {/* The dashed rule needs saying once. Repeating it on every row was
              the version that had to be explained anyway. */}
          <p className="mt-1 text-xs" style={{ color: "var(--faint)" }}>
            A dashed line means the fact came from your CV and you have not
            checked it yet.
          </p>
        </div>
        {!empty && (
          <ProfileMenu total={totalItems} />
        )}
      </div>

      {/* Two views of the same career: what the system holds, and what was
          sent. The structured profile is the default because it is what
          tailoring, scoring and the advisor all read; the original is a
          reference beside it, never a second source of truth (ADR-013). */}
      <ProfileTabs
        profile={
          <>
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
              <ProfileSection title="Contact" kind="contact" count={content.contact.length}>
                {content.contact.map((c) => (
                  <ProfileEntry key={c.id} source={c.source} kind="contact" id={c.id} label="contact details" values={c}>
                    {/* Every stored field. Showing three of five here was the same
                        bug as the review screen had — the profile would claim a
                        phone number was never captured when it was. */}
                    <p>{c.full_name}</p>
                    <p style={{ color: "var(--muted)" }}>
                      {[c.email, c.phone, c.location].filter(Boolean).join(" · ")}
                    </p>
                    {c.links.map((link) => (
                      <p key={link} className="text-xs" style={{ color: "var(--faint)" }}>
                        {link}
                      </p>
                    ))}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.titles.length > 0 && (
              <ProfileSection title="Titles" kind="title" count={content.titles.length}>
                {content.titles.map((t) => (
                  <ProfileEntry key={t.id} source={t.source} kind="title" id={t.id} label={t.title} values={t}>
                    {t.title}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.summaries.length > 0 && (
              <ProfileSection title="Summary" kind="summary" count={content.summaries.length}>
                {content.summaries.map((s) => (
                  <ProfileEntry key={s.id} source={s.source} kind="summary" id={s.id} label="summary" values={s}>
                    {s.text}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.work_experience.length > 0 && (
              <ProfileSection title="Work experience" kind="work_experience" count={content.work_experience.length}>
                {content.work_experience.map((role) => (
                  <ProfileEntry key={role.id} source={role.source} kind="work_experience" id={role.id} label={role.company} values={role}>
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
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.skills.length > 0 && (
              <ProfileSection title="Skills" kind="skill" count={content.skills.length}>
                {[
                  ...content.skills
                    .reduce((groups, skill) => {
                      const category = skill.category?.trim() || null;
                      groups.set(category, [...(groups.get(category) ?? []), skill]);
                      return groups;
                    }, new Map<string | null, Content["skills"]>())
                    .entries(),
                ].map(([category, group]) => (
                  // The same grouping the review screen uses, and the same one the
                  // CV was written in. A flat list of 22 discards structure that is
                  // already in the data.
                  <li key={category ?? "uncategorised"} className="pt-3 first:pt-0">
                    {category && (
                      <p
                        className="mb-1 text-xs tracking-wider uppercase"
                        style={{ fontFamily: "var(--font-mono)", color: "var(--faint)" }}
                      >
                        {category}
                      </p>
                    )}
                    <ul className="space-y-1">
                      {group.map((skill) => (
                        <ProfileEntry
                          key={skill.id}
                          source={skill.source}
                          kind="skill"
                          id={skill.id}
                          label={skill.name}
                          values={skill}
                        >
                          {skill.name}
                        </ProfileEntry>
                      ))}
                    </ul>
                  </li>
                ))}
              </ProfileSection>
            )}

            {content.education.length > 0 && (
              <ProfileSection title="Education" kind="education" count={content.education.length}>
                {content.education.map((e) => (
                  <ProfileEntry key={e.id} source={e.source} kind="education" id={e.id} label={e.institution} values={e}>
                    <p>{educationLine(e.qualification, e.field_of_study, e.institution)}</p>
                    {[e.start_date, e.end_date, e.grade].some(Boolean) && (
                      <p className="text-xs" style={{ color: "var(--faint)" }}>
                        {[
                          [e.start_date, e.end_date].filter(Boolean).join(" – "),
                          e.grade,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </p>
                    )}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.certifications.length > 0 && (
              <ProfileSection title="Certifications" kind="certification" count={content.certifications.length}>
                {content.certifications.map((c) => (
                  <ProfileEntry key={c.id} source={c.source} kind="certification" id={c.id} label={c.name} values={c}>
                    {[c.name, c.issuer, c.year].filter(Boolean).join(" — ")}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.volunteering.length > 0 && (
              <ProfileSection title="Volunteering" kind="volunteer" count={content.volunteering.length}>
                {content.volunteering.map((v) => (
                  <ProfileEntry key={v.id} source={v.source} kind="volunteer" id={v.id} label={v.organisation} values={v}>
                    {[v.role, v.organisation].filter(Boolean).join(" — ")}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.military_service.length > 0 && (
              <ProfileSection title="Military service" kind="military_service" count={content.military_service.length}>
                {content.military_service.map((m) => (
                  <ProfileEntry key={m.id} source={m.source} kind="military_service" id={m.id} label={m.branch} values={m}>
                    {[m.role, m.branch].filter(Boolean).join(" — ")}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}

            {content.languages.length > 0 && (
              <ProfileSection title="Languages" kind="language" count={content.languages.length}>
                {content.languages.map((l) => (
                  <ProfileEntry key={l.id} source={l.source} kind="language" id={l.id} label={l.name} values={l}>
                    {[l.name, l.proficiency].filter(Boolean).join(" — ")}
                  </ProfileEntry>
                ))}
              </ProfileSection>
            )}
          </>
        )}
          </>
        }
        original={<OriginalCv imports={imports} />}
      />

      </EditModeProvider>
    </AppShell>
  );
}
