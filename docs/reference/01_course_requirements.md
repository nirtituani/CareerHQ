# Course Project Requirements

> **Source document**, reproduced verbatim. This is the specification CareerHQ is graded against.
> How each requirement is satisfied: `docs/05_Implementation_Plan.md` §6 and
> `docs/07_Capabilities.md` §4.

---

## Projects Overview

The projects can be in teams of up to 4 people. Start thinking of ideas, implementation will start
mid course.

The teams are encouraged to bring their original ideas.

For convenience, some project ideas appear below, you can pick from them.

- There will be a launch mid-course, team formation.
- Mid-project short demo: Projects Pitch and Plan (specs, plan & team roles, architecture
  blueprint).
- Final project presentations. End of course.

---

## Prerequisites

- Develop a project idea with specifications.
- Plan the project. Define milestones.
- Build an agent, having a backend + frontend.
- The agent should manage memory.
- The agent should use Tools/MCPs.
- Pick an agentic workflow that matches the problem: ReAct, RAG, RLM, multi-agent, self-critique,
  etc.
- Design evaluation + benchmark. Metrics + analytics of success.
- Roles within the team: spec writer, evaluator, engineer(s), product owner.
- Deployed using Docker (with Railway, for example, or others)

---

## The listed idea closest to CareerHQ

**6. Job Application Composer**

> **Purpose:** An agent that helps users prepare job applications — it analyzes job descriptions,
> gives CV feedback grounded in best-practice guidelines, tailors cover letters, and tracks the
> application pipeline.
>
> - **Backend + frontend:** Application tracker dashboard + coaching chat.
> - **Memory:** Past applications, cover letters, interview feedback — persisted across sessions.
>   CV is a session input only (not stored).
> - **Tools/MCPs:** Web search MCP for job postings and company research, document editor tool.
> - **Evaluation:** CV feedback alignment with the checklist; cover letter quality rated by
>   LLM-as-judge.
> - **Workflow:** ReAct over a RAG knowledge base of CV best-practice guidelines (analyze job
>   description → retrieve guidelines → give feedback → draft cover letter → refine).

**How CareerHQ differs, deliberately:** the listed idea treats the CV as a session input that is
not stored. CareerHQ stores a structured Professional Profile as the single source of truth, which
is what makes the Career Advisor possible — you cannot count how often a skill appears across
twenty applications if you never kept the skills. Original ideas are explicitly encouraged; this is
a deliberate expansion, not a misreading (ADR-001, ADR-013).

---

## Status against each prerequisite

| Requirement | Where satisfied | State |
|---|---|---|
| Project idea with specifications | `docs/00`–`docs/07`, `specs/` | Done |
| Plan with milestones | `docs/05` | Done |
| Agent with backend + frontend | Slice 004 | Planned |
| Agent manages memory | Profile + application history; slice 007 reasons over it | Planned |
| Tools / MCPs | Slice 004 tools; web search **MCP** in slice 006 | Planned |
| Agentic workflow matched to the problem | Multi-agent + RAG + self-critique (ADR-004, ADR-008) | Planned |
| Evaluation + benchmark + metrics | Slice 005 | Planned |
| Team roles | Solo; SDD keeps spec, evaluation, and engineering separated as artifacts | N/A |
| Deployed using Docker | Slice 002 | Planned |
