# CareerHQ

> **Technology Stack**

**Version:** 1.0  
**Status:** Draft

---

# 1. Purpose

This document defines the official technology stack used by CareerHQ.

It serves as the single source of truth for all implementation technologies, frameworks, infrastructure components, and development tools.

Architectural decisions are documented in `02_ADR.md`.

System responsibilities are documented in `04_System_Design.md`.

This document answers one question:

> **What technologies are used to build CareerHQ?**

---

# 2. Guiding Principles

Technology selection follows these principles:

- Simplicity over complexity
- Mature ecosystems over novelty
- Open-source first
- Cloud agnostic where possible
- AI-native development
- Developer productivity
- Easy deployment
- Low operational overhead

---

# 3. Technology Overview

| Category | Technology |
|----------|------------|
| Frontend | Next.js |
| Language (Frontend) | TypeScript |
| UI Library | React |
| Styling | Tailwind CSS |
| Components | shadcn/ui |
| Backend | FastAPI |
| Language (Backend) | Python |
| ORM | SQLAlchemy |
| Validation | Pydantic |
| Database | PostgreSQL |
| Vector Search | pgvector |
| Cache | Redis |
| Background Jobs | Celery |
| Object Storage | S3 Compatible Storage |
| AI Runtime | LangGraph |
| AI Gateway | LiteLLM |
| LLM Providers | OpenAI, Anthropic, Gemini |
| Authentication | Google OAuth |
| Containers | Docker |
| Local Development | Docker Compose |
| Migrations | Alembic |
| Testing (Backend) | Pytest |
| Testing (Frontend) | Playwright, React Testing Library |
| API Documentation | OpenAPI / Swagger |
| Version Control | Git |
| CI/CD | GitHub Actions |

---

# 4. Frontend Stack

## Framework

**Next.js**

Purpose

- Web Application
- Routing
- Server Components
- API Integration

Reasons

- Excellent React ecosystem
- Great developer experience
- Production ready
- Strong community support

---

## Programming Language

**TypeScript**

Purpose

- Static typing
- Better maintainability
- Safer refactoring

---

## UI Library

**React**

Purpose

- Component-based UI
- State management
- Interactive user experience

---

## Styling

**Tailwind CSS**

Purpose

- Utility-first styling
- Fast UI development
- Consistent design

---

## Component Library

**shadcn/ui**

Purpose

- Accessible UI components
- Reusable design system
- Modern user interface

---

# 5. Backend Stack

## Framework

**FastAPI**

Purpose

- REST API
- Dependency Injection
- Validation
- OpenAPI generation

Reasons

- Excellent async support
- Python ecosystem
- High performance
- Automatic API documentation

---

## Programming Language

**Python**

Purpose

- Business Logic
- AI Integration
- Domain Model

Reasons

- Best AI ecosystem
- Large community
- Excellent libraries

---

## ORM

**SQLAlchemy**

Purpose

- Database access
- Repository implementation
- ORM mapping

---

## Validation

**Pydantic**

Purpose

- Request validation
- Response validation
- Configuration models

---

## Database Migration

**Alembic**

Purpose

- Schema migrations
- Version control
- Deployment consistency

---

# 6. Data Layer

## Primary Database

**PostgreSQL**

Purpose

- Business data
- Transactions
- Relational storage

Stores

- Users
- Professional Profiles
- Resume Profiles
- Resume Versions
- Applications
- Companies
- Interviews
- Workflow Metadata

Reasons

- Mature
- Reliable
- ACID compliant
- Excellent tooling

---

## Vector Database

**pgvector**

Purpose

- Semantic search
- Embedding storage
- RAG

Reasons

- Native PostgreSQL extension
- Simple MVP architecture
- No additional infrastructure

---

## Cache

**Redis**

Purpose

- Workflow state
- Caching
- Session context
- Temporary data

Redis is **not** a source of truth.

---

## Object Storage

**S3 Compatible Storage**

Development

- MinIO

Production

- AWS S3
- Cloudflare R2
- Backblaze B2
- Any S3-compatible provider

Purpose

- Resume PDFs
- Uploaded files
- Generated reports
- Future cover letters
- Binary assets

---

# 7. AI Stack

## Agent Runtime

**LangGraph**

Purpose

- Workflow execution
- Agent orchestration
- State management

Reasons

- Native graph execution
- Human-in-the-loop support
- Production ready

---

## AI Gateway

**LiteLLM**

Purpose

- Provider abstraction
- Model routing
- Cost tracking

Reasons

- Unified API
- Multiple providers
- Easy migration

---

## LLM Providers

Primary

- Anthropic Claude (`LLM_PROVIDER_MODEL=anthropic/claude-opus-5`)

Also supported

- OpenAI
- Google Gemini

The application communicates only with LiteLLM.

Providers remain replaceable.

---

## Embedding Models

Embeddings sit behind a configurable interface, separate from the LLM gateway.

Default

- `sentence-transformers/all-MiniLM-L6-v2`, running locally

Optional hosted providers

- OpenAI Embeddings
- Gemini Embeddings
- Voyage AI
- BGE
- Instructor

Reasons

- **Anthropic has no embeddings endpoint.** The primary LLM provider is
  Anthropic Claude, so embeddings cannot come from the same place as
  generation — they are a genuinely separate choice, not a setting on the
  gateway.
- **The stack runs with no API key.** A local default means `docker compose up`
  works on a clean clone before any provider account exists, which is what keeps
  the quickstart honest.
- **LiteLLM does not cover this seam.** Business code stays provider-agnostic
  either way (Principle IV), but the indirection is our own interface rather
  than the gateway's.

Configured by `EMBEDDING_MODEL`. Changing providers is configuration, not code.

---

# 8. Background Processing

## Celery

Purpose

- Long-running workflows
- AI execution
- PDF generation
- Background processing

Future consideration

- Temporal
- Arq
- Dramatiq

---

# 9. Authentication

## Google OAuth

Purpose

- User authentication
- Secure login
- Simple onboarding

Future Providers

- Microsoft
- GitHub
- Email & Password

---

# 10. Infrastructure

## Containers

**Docker**

Purpose

- Local development
- Deployment
- Environment consistency

---

## Local Environment

**Docker Compose**

Services

- Frontend
- Backend
- PostgreSQL
- Redis
- MinIO

---

# 11. API

## REST

Framework

- FastAPI

Documentation

- OpenAPI
- Swagger UI

Response Format

- JSON

---

# 12. Testing

## Backend

Framework

- Pytest

Coverage Target

- 80%+

---

## Frontend

Frameworks

- Playwright
- React Testing Library

---

# 13. Development Tools

| Category | Tool |
|----------|------|
| IDE | VS Code |
| API Client | Bruno / Postman |
| Database Client | DBeaver |
| Git Client | Git |
| Package Manager | npm |
| Python Environment | uv |
| Formatting | Ruff |
| Linting | Ruff |
| Type Checking | mypy |

---

# 14. CI/CD

Platform

- GitHub Actions

Pipeline

- Build
- Lint
- Unit Tests
- Integration Tests
- Docker Build
- Deploy

---

# 15. Future Technology Candidates

These technologies are not part of the MVP but may be evaluated in the future.

| Category | Candidate |
|----------|-----------|
| Event Bus | RabbitMQ |
| Workflow Engine | Temporal |
| Vector Database | Qdrant |
| Vector Database | Pinecone |
| Monitoring | Grafana |
| Metrics | Prometheus |
| Tracing | OpenTelemetry |
| Kubernetes | Kubernetes |
| Secrets | Vault |

---

# 16. Technology Decision Summary

| Responsibility | Technology |
|----------------|------------|
| Frontend | Next.js |
| Backend | FastAPI |
| Language | Python |
| Frontend Language | TypeScript |
| ORM | SQLAlchemy |
| Validation | Pydantic |
| Database | PostgreSQL |
| Vector Search | pgvector |
| Cache | Redis |
| Object Storage | S3 Compatible Storage |
| AI Runtime | LangGraph |
| AI Gateway | LiteLLM |
| LLM Providers | OpenAI, Anthropic, Gemini |
| Background Jobs | Celery |
| Authentication | Google OAuth |
| Containers | Docker |
| Local Development | Docker Compose |
| Testing | Pytest, Playwright |
| CI/CD | GitHub Actions |

---

# 17. Conclusion

The selected technology stack prioritizes developer productivity, architectural simplicity, and AI-native capabilities.

Every technology has been selected to support the MVP while allowing future evolution without major architectural changes.

Technology choices may evolve over time, while the architectural principles defined in the System Design remain stable.