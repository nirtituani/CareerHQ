# CareerHQ

### Your AI-powered headquarters for every job application.

---

# Architecture Decision Records (ADR)

**Version:** 1.0  
**Status:** Draft  
**Author:** Nir Tituani  
**Last Updated:** August 2026

---

# Purpose

This document records the major architectural decisions made during the design of CareerHQ.

Each Architecture Decision Record (ADR) documents the context, alternatives considered, the chosen solution, and its consequences.

The goal is to preserve architectural reasoning, improve maintainability, and provide clear documentation for future development.

---

# ADR-001

## Professional Profile as the System of Record

### Status

Accepted

### Context

Traditional resume builders treat resumes as independent documents. This leads to duplicated information, inconsistent updates, and difficulty maintaining multiple resume variants.

CareerHQ requires a model capable of supporting multiple career paths while maintaining one authoritative source of professional information.

### Decision

CareerHQ will maintain a single **Professional Profile** for every user.

The Professional Profile will serve as the system's single source of truth.

Every Resume Profile, Resume Version, AI workflow, and career insight will derive information from this profile.

### Alternatives Considered

**Multiple Independent Resumes**

Pros

- Simple implementation.
- Familiar user experience.

Cons

- Heavy duplication.
- Difficult maintenance.
- Poor support for AI reasoning.

### Consequences

Advantages

- Eliminates duplicated information.
- Enables structured AI reasoning.
- Simplifies profile maintenance.
- Supports multiple Resume Profiles.

Trade-offs

- Requires a richer domain model.
- Resume generation becomes composition instead of document editing.

---

# ADR-002

## Professional Knowledge over Document-Centric Design

### Status

Accepted

### Context

Traditional resume systems manage static documents.

CareerHQ is designed around structured professional knowledge rather than editable resume files.

### Decision

CareerHQ will model professional information as structured knowledge.

Resumes become generated artifacts instead of primary data.

### Alternatives Considered

Document-centric architecture.

### Consequences

Advantages

- Better AI reasoning.
- Easier future expansion.
- Reduced duplication.
- Improved maintainability.

Trade-offs

- More complex domain model.

---

# ADR-003

## Resume Profiles Instead of Multiple Master Resumes

### Status

Accepted

### Context

Users often maintain several resumes for different career paths.

Maintaining separate master resumes causes unnecessary duplication.

### Decision

CareerHQ introduces Resume Profiles.

Resume Profiles define presentation preferences while referencing a shared Professional Profile.

### Consequences

Advantages

- Shared professional knowledge.
- Cleaner maintenance.
- Easier profile evolution.

Trade-offs

- Additional abstraction.

---

# ADR-004

## Multi-Agent Architecture

### Status

Accepted

### Context

CareerHQ contains several independent AI capabilities including resume tailoring, company research, career advising, and future interview preparation.

A single monolithic AI workflow would become increasingly difficult to maintain.

### Decision

CareerHQ will adopt a Multi-Agent architecture.

Each business capability will be implemented as an independent AI Agent coordinated through a central orchestration layer.

### Alternatives Considered

Single AI Agent

Advantages

- Simpler implementation.

Disadvantages

- Poor scalability.
- Tight coupling.
- Difficult testing.

### Consequences

Advantages

- Modular architecture.
- Independent evolution.
- Easier testing.
- Better maintainability.

Trade-offs

- Higher orchestration complexity.

---

# ADR-005

## LangGraph as the Agent Orchestrator

### Status

Proposed

### Context

CareerHQ requires stateful workflows, conditional execution, long-running tasks, and human approval steps.

Several orchestration frameworks were evaluated.

### Alternatives Considered

- LangGraph
- CrewAI
- Semantic Kernel
- Custom orchestration

### Decision

LangGraph is the preferred orchestration framework.

### Rationale

- Native graph execution.
- Excellent Human-in-the-Loop support.
- Strong state management.
- Growing ecosystem.

### Trade-offs

- Additional learning curve.
- Tighter dependency on LangGraph.

---

# ADR-006

## Human-in-the-Loop Approval

### Status

Accepted

### Context

CareerHQ generates recommendations that directly affect professional documents.

Users must retain complete ownership of every modification.

### Decision

Every AI-generated resume modification requires explicit user approval before becoming part of a Resume Version.

### Consequences

Advantages

- User trust.
- Prevents unintended changes.
- Supports explainability.

Trade-offs

- Additional interaction.

---

# ADR-007

## Immutable Submitted Resumes

### Status

Accepted

### Context

Applications should always reference the exact resume submitted.

Historical resumes must remain reproducible.

### Decision

Submitted resumes become immutable snapshots.

### Consequences

Advantages

- Complete audit history.
- Accurate application tracking.
- Reproducibility.

Trade-offs

- Increased storage.

---

# ADR-008

## Retrieval-Augmented Generation over Structured Knowledge

### Status

Proposed

### Context

AI agents require access to professional knowledge and historical application data.

### Decision

CareerHQ will use Retrieval-Augmented Generation (RAG) to retrieve relevant structured knowledge before invoking an LLM.

### Consequences

Advantages

- Better factual accuracy.
- Reduced hallucinations.
- Better personalization.

Trade-offs

- Additional infrastructure.
- Vector indexing required.

---

# ADR-009

## PostgreSQL as the Primary Database

### Status

Proposed

### Context

CareerHQ requires structured relational data while supporting semantic search.

### Decision

Use PostgreSQL as the primary database with pgvector for vector search.

### Alternatives

- MongoDB
- Pinecone
- Neo4j

### Consequences

Advantages

- Mature ecosystem.
- ACID compliance.
- Structured + vector support.

Trade-offs

- Less flexible than document databases.

---

# ADR-010

## FastAPI as the Backend Framework

### Status

Proposed

### Context

CareerHQ requires high-performance APIs and native Python support for AI services.

### Decision

Use FastAPI as the primary backend framework.

### Consequences

Advantages

- Async support.
- Excellent developer experience.
- Native Python ecosystem.

Trade-offs

- Smaller ecosystem compared to Django.

---

# ADR-011

## Docker-Based Development Environment

### Status

Accepted

### Context

The project includes multiple services including backend APIs, databases, vector storage, AI services, and frontend components.

### Decision

Every service will run inside Docker containers during development.

### Consequences

Advantages

- Reproducible environments.
- Easy onboarding.
- Consistent deployments.

Trade-offs

- Slightly higher local resource usage.