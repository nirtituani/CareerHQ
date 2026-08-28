## Purpose and Scope

This report catalogs authoritative sources of guidelines for building a "perfect" hi-tech CV, with special emphasis on the Israeli market, intended as a curated corpus for a Retrieval-Augmented Generation (RAG) system that helps users tailor CVs to specific job requirements. Sources are grouped by theme: general tech resume structure, ATS/formatting compliance, keyword-tailoring methodology, achievement-writing frameworks (STAR/PAR), LinkedIn optimization, and Israel-specific hi-tech CV guides.

## General Tech/Software Engineer Resume Structure

Multiple career platforms converge on a consistent core structure for a hi-tech resume: header with name, phone, email, city, and links to GitHub/LinkedIn/portfolio; a 2-4 sentence professional summary tailored to the target role; a skills section grouped by category (languages, frameworks, tools); reverse-chronological work experience with 3-6 quantified bullets per role; and education/certifications placed last for experienced candidates (or first for students/new grads).

Consensus formatting rules across these sources include: one page for under 5-10 years of experience (two pages max for senior candidates), single-column layout, standard fonts (Arial, Calibri, Georgia, Times New Roman) at 10-12pt, and PDF as the preferred export format for human readability (though plain text/.docx is safer for older ATS parsers). Sources emphasize the "three C's" — consistent, clean, correct — and stress that a technical resume should foreground hard skills (coding ability, systems, tools) more heavily than a generic resume.

| Source | Focus | Key Contribution |
|---|---|---|
| Indeed Technical Resume Tips | General structure | 6-section framework: personal info, summary, experience, education, skills, certifications |
| Rockstar Developer University | Software engineer specifics | Bullet formula, ATS parsing, one-page rule under 5 yrs |
| BridgeviewIT 2026 Guide | Proof-driven bullets | Action + Tech + Impact + Scope bullet pattern |
| DataCamp Guide | SE resume with examples | STAR/PAR structuring, project section detail |
| CareerFoundry Guide | Tech resume tips/examples | 8 key sections, dos/don'ts list |
| Tech Interview Handbook (FAANG) | FAANG-ready format | ATS-friendly template, heading naming table |
| NickSingh.com 36 Rules | Principles-based | "15-second test" for resume clarity |

Sources: indeed.com/career-advice/resumes-cover-letters/technical-resume-tips, rockstardeveloperuniversity.com/software-engineer-resume, bridgeviewit.com/blog/technical-resume-writing-tips, datacamp.com/blog/software-engineer-resume, careerfoundry.com/en/blog/career-change/best-tech-resume-guide-tips-examples, techinterviewhandbook.org/resume, nicksingh.com/posts/36-resume-rules-for-software-engineers

## ATS (Applicant Tracking System) Compliance

A large cluster of sources focuses specifically on ATS-parseability, which is critical for the "job requirement fitting" logic in a RAG tailoring tool. Universal ATS rules include: single-column layout (no tables, text boxes, columns, or graphics); standard section headings such as "Work Experience," "Education," "Skills," "Certifications"; contact information placed in the document body rather than headers/footers; consistent Month-Year date formatting; and avoidance of images, icons, logos, or unusual fonts.

There is some disagreement on file format: several university career centers (ONU, UIC, PCC) recommend .doc/.txt/.rtf over PDF/.docx because older ATS engines historically failed to parse PDFs correctly, while more recent 2025-2026 sources state modern ATS platforms parse text-based PDFs reliably, making PDF the practical default unless the employer specifies otherwise. This is an important nuance for a RAG system to flag as time/context-dependent rather than an absolute rule. Additional actionable ATS guidance includes running a "copy-paste test" (select all text and paste into a blank document — if it pastes cleanly, the ATS can read it), and never using keyword-stuffing tricks such as white-text keyword hiding, which is explicitly called out as both ineffective and unethical.

Sources: my.onu.edu (ATS resume guide PDF), pcc.edu (ATS formatting guidelines PDF), careerservices.uic.edu (ATS optimization PDF), indeed.com/career-advice/resumes-cover-letters/applicant-tracking-system-resume, resumly.ai/resume-format/ats, careerservices.cns.utexas.edu/resources/resumes/applicant-tracking-systems, atsresumeschecker.com

## Keyword-Tailoring Methodology for Job-Specific Matching

This is the most directly relevant cluster for the RAG project's core use case — matching a CV to a specific job requirement. The dominant methodology across sources (Indeed, LinkedIn, ManyOffer, ATS Resume Checker, Resume Optimizer Pro) follows a repeatable process:

- Extract repeated keywords from the job description (skills, tools, methodologies, outcome verbs), prioritizing terms appearing 2+ times.
- Build/maintain a "master resume" containing all experience, then select and reorder content per application rather than writing from scratch each time.
- Mirror exact phrasing from the job posting (e.g., "data pipeline" not "data workflow") rather than paraphrasing, since ATS and human matching rely on literal term overlap.
- Insert matched keywords naturally into three high-weight zones: the summary, the skills section, and inside experience bullet points (not just as a list) — since context-embedded keywords score higher than isolated lists.
- Include both acronym and spelled-out forms of terms (e.g., "Search Engine Optimization (SEO)") to cover both keyword variants.
- Target roughly 70-80% coverage of "required" keywords and 50%+ of "preferred" keywords, while avoiding fabricating skills the candidate lacks.

A useful time-boxed version of this process appears in ManyOffer's "5-Minute ATS Tailoring" framework, which breaks tailoring into five one-minute steps: highlight repeated terms, pick 3 must-match requirements, rewrite summary/skills, swap 4-6 bullets, and run a final keyword check. This maps well onto a RAG pipeline: retrieval of job-description keywords → retrieval of matching resume bullets from the user's master resume → generation of tailored rewrites.

Sources: manyoffer.com/blog/tailor-resume-to-job-description, indeed.com/career-advice/resumes-cover-letters/match-resume-with-job-description, linkedin.com/top-content/career/resume-tips/resume-keywords-for-ats-and-recruiters, linkedin.com/top-content/career/resume-tips/tips-for-ats-keyword-optimization, resumeoptimizerpro.com/blog/how-to-tailor-resumes-for-jobs, atsresumeschecker.com/how-to-tailor-resume-to-job-description

## Achievement-Writing Frameworks (STAR / PAR)

For converting raw experience into compelling bullet points, sources converge on the STAR (Situation, Task, Action, Result) or the shorter PAR (Problem, Action, Result) frameworks, often condensed into "Action Verb + Task + Context + Quantified Result" for resume use rather than full interview-style STAR answers. Because full STAR paragraphs are too long for a resume, most sources recommend a "reverse STAR" — leading with the result — e.g., "Cut monthly server costs by $4,000 by auditing and decommissioning unused AWS accounts."

Best practices for quantification include using percentages, dollar amounts, time saved, user/scale numbers, or defensible estimates when hard numbers are unavailable, and keeping each bullet to roughly 15-25 words. These frameworks are directly reusable as generation templates in a RAG system: given a raw accomplishment and a target job's priority keywords, the system can restructure it into Action + Tech/Context + Quantified Result form.

Sources: resuopt.com/blog/star-method-resume-bullets-examples, monster.com/career-advice/resume/star-method-resume, resumly.ai/blog/write-bullet-points-using-the-star-framework-effectively, resumegenius.com/blog/resume-help/star-method-resume, resume-get.com/blog/how-to-write-star-method-bullet-points-that-get-interviews, sweresume.app/articles/star-method-resume, resumeworded.com/star-method-resume-key-advice

## LinkedIn Profile Optimization (Complementary Asset)

Since Israeli and global tech recruiting heavily uses LinkedIn alongside the CV itself, several sources cover profile optimization as a companion artifact: a keyword-rich headline (role + 2-3 key skills, not just job title), an About section opening with a one-line hook, quantified project/experience bullets mirroring resume language, a Skills section with 15-20+ ranked relevant terms, and GitHub/portfolio links in the contact/featured section. This is a useful secondary corpus segment since a complete "CV help" RAG tool for hi-tech job seekers is often expected to also give LinkedIn alignment advice.

Sources: mitsedge.com/guides/linkedin-optimization-tips-for-tech-job-seekers, jobwizard.ai/blog/guide-to-optimizing-your-linkedin-profile-for-2026-tech-hiring, agenticjobboard.com/guides/linkedin-profile-optimization-for-tech-candidates, scaletwice.com/blog-post/linkedin-profile-optimization-tech-job-seekers, oho.us/blog/how-to-optimise-your-linkedin-profile-for-a-tech-role, pursuenetworking.com/blog/tech-industry-linkedin-profile-guide

## Israel-Specific Hi-Tech CV Sources (Original Round)

Several Hebrew-language, Israel-focused sources provide guidance closely mirroring the international consensus but with local nuances (e.g., military service section, Hebrew vs. English CV choice, and recruiter agency perspectives common in the Israeli market):

- **Techmonster** — a detailed Hebrew step-by-step 2025 guide specifying a strict one-page format with sections in the order: personal details, work experience (most important, top of document), side projects, skills, education, and an optional military service section; it also stresses using a target job title in the header even without formal experience in that title.
- **GotFriends** (Israeli tech recruiting agency) — comprehensive Hebrew CV writing guide including a suggested CV format and emphasis on total years of experience plus relevant education upfront.
- **Jolt** — "10 tips for improving your hi-tech CV," recommending an opening paragraph at the top of the page summarizing the candidate, and advising 3-4 industry contacts review a CV before submission.
- **Log-On** (Israeli staffing agency) — two guides covering classic CV structure (personal details, 3-4 line professional summary/"elevator pitch," experience, education, technical skills) and keyword-matching against job postings (copy the job ad, mark recurring keywords like Python, React, REST API, Agile, Docker, and weave them naturally into experience descriptions).
- **HaJunior** — a guide targeted at students/new graduates entering programming roles (CS/EE grads), including specific advice on when and how to include a code/GitHub link.
- **Jobseeker.he** — 2026 Israeli-market hi-tech CV example emphasizing quantified achievements and clean, professional design as critical first impressions.
- **Jerusalem Mynet career article** — three key tips for Israeli hi-tech job seekers: choose a template matching the specific company/role, include only role-relevant content, and use recruiter-searchable keywords (e.g., "מפתח," "מהנדס," "יזם," "מומחה").
- **Technion Career Development Center (Dean of Students)** — official Israeli academic institution service offering professional CV rewriting support, framing the CV as typically the candidate's first contact point with an employer.
- **AllJobs** — Israel's major job board's official CV Center guide and Help Center FAQ on writing effective CVs.

Sources: techmonster.co.il/hightech-cv-guide, gotfriends.co.il (CV guide page), jolt.co.il/careers/hightech-cv, b.log-on.com (two CV guide articles), hajunior.com, jobseeker.com/he/cv/examples/developer, jerusalem.mynet.co.il (good_to_know article), dean.technion.ac.il/career-development-center, alljobs.co.il/Campaigns/CVCenter/CVCenterGuide.htm, alljobs.co.il/helpcenter/jobseekers/cv

## Additional Israeli-Market Sources (Expansion Round)

To increase the Israeli-source-to-global ratio in the corpus, a second round of research targeted Israeli job boards, staffing platforms, dev-specific job sites, and company career blogs directly.

**Drushim.co.il (major Israeli job board)** — Its official CV-writing guide is one of the most detailed Hebrew sources found: it states recruiters spend only 20-30 seconds on first CV screening, recommends omitting age and home address to avoid automatic disqualification for location-restricted roles, advises 1-2 pages maximum, and explicitly instructs candidates to tailor the document per job posting rather than sending one generic version. Drushim also maintains a dedicated hi-tech jobs hub aggregating role-specific listings (Unix/Windows sysadmin, DBA, ERP/CRM developer, Web developer, InfoSec specialist, etc.), useful for building a taxonomy of Israeli hi-tech role titles for the RAG system's keyword-matching layer.

**TechJob.co.il** — An Israeli hi-tech-focused advice page reinforcing per-job tailoring, and specifically flagging military service as a resume element Israeli employers expect to see when relevant, alongside software/language proficiency.

**JobMob (Jacob Share)** — A long-running, detailed English-language guide specifically aimed at building CVs for the Israeli job market audience, covering agency vs. direct-employer submission etiquette, formatting rules (avoiding excessive bold/color, consistent heading structure), language-proficiency framing (e.g., stating fluency levels explicitly rather than just listing languages), and the reminder that a CV is not a LinkedIn profile dump.

**ResumeFlex Israel Job Market Guide** — Provides Israel-specific cultural framing: notes Israeli recruiters average roughly 6 seconds on a first resume scan, recommends a "Challenge → Action → Result" bullet structure, and states that IDF unit experience (e.g., Unit 8200 cyber intelligence) functions as a strong credibility signal on Israeli hi-tech resumes, especially for cybersecurity roles. It also stresses cultural fit signals like directness and initiative ("chutzpah") over corporate-mission-statement language.

**DevJobs.co.il** — An Israel-specific developer job board (also used by companies like Wiz for R&D hiring in Tel Aviv/Herzliya) that anonymizes resume submissions, indicating a norm in parts of the Israeli dev market for bias-reduced/blind initial screening.

**Israeli hi-tech job-search Facebook groups** — A meta-directory identifies roughly 35 active Facebook groups specifically dedicated to Israeli hi-tech job search and recruiting, which function as informal peer-review and networking channels where candidates often crowd-source CV feedback. While not a single authoritative style guide, this signals that community peer-review is a recognized/expected step in the Israeli CV-refinement process.

**Company-level hiring pages (Wix, Wiz, Check Point)** — Wix's official careers blog states explicitly "we hire people, not resumes" and prioritizes demonstrated learning ability over formal credentials in its Israeli/global hiring philosophy, plus a companion guide on proactive/referral-based job search tactics. Check Point's hiring-process breakdown (via a third-party prep guide) confirms Israeli cybersecurity-employer expectations of an ATS-clean, role-tailored résumé plus two rehearsed STAR stories per candidate before behavioral panels. Wiz's Tel Aviv-headquartered engineering interview guide confirms a 4-7 week loop starting with a recruiter screen focused on résumé-driven "why this role" framing.

Sources: drushim.co.il/article/13, drushim.co.il/דרושים-הייטק, techjob.co.il/blog/tips-writing-resumes, jobmob.co.il/blog/english-resume-writing-tips, resumeflex.com/how-to-write-a-professional-resume-for-israel-job-market, devjobs.co.il, startuping.co.il/facebook-groups-for-entrepreneurs, careers.wix.com/how-we-hire, careers.wix.com/post/job-search-tips-how-to-stand-out-with-a-proactive-approach, techinterview.org/companies/wiz-interview-guide, claveprep.com/blog/check-point-hiring-process-guide-2026

## Updated Corpus Coverage Summary

| Category | Israeli Sources Now Included |
|---|---|
| Job-board official guides | Drushim.co.il, AllJobs |
| Staffing/recruiting agencies | GotFriends, Log-On (x2) |
| Hi-tech-specific advice blogs | Techmonster, Jolt, TechJob.co.il, HaJunior |
| Cross-market/English-for-Israel guides | JobMob/Jacob Share, ResumeFlex Israel Guide |
| Academic career services | Technion Career Development Center |
| Dev-specific job boards | DevJobs.co.il |
| Company hiring philosophy/process | Wix Careers, Wiz, Check Point (via prep guide) |
| Community/peer-review channels | Israeli hi-tech Facebook groups directory |

## Corpus Organization Recommendations for the RAG System

For building the retrieval corpus, the sources naturally cluster into six retrievable categories that a RAG system should tag and index separately: (1) structural/section-order guidelines, (2) ATS formatting rules, (3) job-description keyword-extraction and tailoring procedures, (4) bullet-point rewriting frameworks (STAR/PAR/quantification), (5) LinkedIn companion optimization, and (6) Israel-market-specific conventions (Hebrew/English CV choice, military service, agency norms, company-specific hiring philosophy, community peer-review norms). Given that ATS file-format guidance is contested and evolving (older sources recommend .docx/.txt, 2025-2026 sources say PDF is now generally safe), the RAG system should timestamp and version-tag ATS-related chunks so it can surface the most current consensus rather than conflicting absolute rules.

Because the end goal is tailoring a CV to a specific job requirement, the highest-value chunks for the RAG's generation step are the keyword-extraction/matching methodologies and the STAR/reverse-STAR bullet rewriting templates, as these provide the actual transformation logic (job description → keyword list → rewritten bullet) rather than static formatting rules. The Israeli-specific chunks should further be sub-tagged by query type: "recruiter scanning behavior" (Drushim, ResumeFlex), "company-specific expectations" (Wix, Wiz, Check Point), and "peer-review/community norms" (Facebook groups, Jolt), since these answer meaningfully different user questions within the tailoring tool.
