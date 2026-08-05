# CareerHQ

> **System Design & Architecture**

**Version:** 1.0  
**Status:** Draft

---

# 1. Executive Summary

CareerHQ is an AI-native career platform designed around intelligent workflows rather than isolated AI features.

Business domains remain deterministic and own all business data.

Artificial Intelligence operates through a dedicated Agent Runtime that retrieves knowledge, executes specialized agents and produces structured recommendations.

Every workflow follows the same lifecycle:

1. Receive business goal
2. Retrieve contextual knowledge
3. Execute AI workflow
4. Generate recommendations
5. Request user approval
6. Persist validated business changes

---

# 2. Architecture Goals

```mermaid
mindmap
  root((CareerHQ))
    AI Native
    Workflow First
    Human in the Loop
    Explainable AI
    Knowledge Driven
    Modular
    Extensible
    Provider Agnostic
    Scalable
```

---

# 3. Quality Attributes

| Attribute | Priority | Response |
|-----------|----------|----------|
| Maintainability | High | Layered Architecture |
| Extensibility | High | Platform Services |
| Explainability | High | Structured Outputs |
| Reliability | High | Human Approval |
| Security | High | OAuth + User Isolation |
| Scalability | Medium | Stateless APIs |
| Performance | Medium | Async Workers |
| Cost | High | AI Gateway |

---

# 4. Architecture Principles

## Business Domains Own Data

Business entities belong exclusively to Business Domains.

AI never modifies business entities directly.

---

## Workflow First

Users initiate workflows.

Agents execute workflow steps.

Users never invoke agents directly.

---

## AI Is A Platform Capability

Artificial Intelligence is implemented through reusable platform services.

Business logic never depends on model providers.

---

## Knowledge Before Generation

Knowledge is retrieved before every generation task whenever factual information is required.

---

## Human In The Loop

Business changes require explicit approval before persistence.

---

## Technology Independence

Architecture describes responsibilities.

Technology implements responsibilities.

---

# 5. Responsibility Map

```mermaid
flowchart TB

Presentation["Presentation Layer"]
Application["Application Layer"]
Domain["Business Domains"]
Platform["Platform Services"]
Infrastructure["Infrastructure"]
External["External Services"]

Presentation --> Application
Application --> Domain
Application --> Platform
Platform --> Infrastructure
Infrastructure --> External
```

| Layer | Responsibility |
|--------|----------------|
| Presentation | User Experience |
| Application | Use Cases |
| Domain | Business Rules |
| Platform | AI Execution |
| Infrastructure | Technical Services |
| External | Third-party Integrations |

---

# 6. C4 - System Context

```mermaid
flowchart LR

User["User"]

CareerHQ["CareerHQ"]

OAuth["Google OAuth"]

AI["AI Providers"]

Search["Web Search"]

Storage["Object Storage"]

User --> CareerHQ

CareerHQ --> OAuth

CareerHQ --> AI

CareerHQ --> Search

CareerHQ --> Storage
```

---

# 7. C4 - Container Diagram

```mermaid
flowchart TB

subgraph Client
Frontend["Next.js Frontend"]
end

subgraph Backend
API["FastAPI API"]
Application["Application Layer"]
Professional["Professional Domain"]
Applications["Application Domain"]
KnowledgeDomain["Knowledge Domain"]
Runtime["Agent Runtime"]
KnowledgePlatform["Knowledge Platform"]
end

Database[("PostgreSQL")]
Redis[("Redis")]
ObjectStorage[("Object Storage")]
Gateway["AI Gateway"]
Providers["OpenAI / Anthropic / Gemini"]

Frontend --> API

API --> Application

Application --> Professional
Application --> Applications
Application --> KnowledgeDomain
Application --> Runtime
Application --> KnowledgePlatform

Professional --> Database
Applications --> Database
KnowledgeDomain --> Database

KnowledgePlatform --> Database

Runtime --> Redis
Runtime --> Gateway

Gateway --> Providers

Professional --> ObjectStorage
```

---

# 8. Layered Architecture

```mermaid
flowchart TB

Presentation["Presentation"]

Application["Application"]

Domain["Domain"]

Platform["Platform"]

Infrastructure["Infrastructure"]

Presentation --> Application

Application --> Domain

Application --> Platform

Platform --> Infrastructure
```

## Presentation Layer

Responsibilities:

- User Interface
- Authentication
- Forms
- Dashboard
- Resume Editor

---

## Application Layer

Responsibilities:

- Execute Use Cases
- Coordinate Domains
- Invoke Platform Services
- Handle Transactions
- Manage Approval Flow

---

## Domain Layer

Responsibilities:

- Business Rules
- Validation
- Aggregate Management
- Repository Coordination

Domains:

- Professional
- Application
- Knowledge

---

## Platform Layer

Responsibilities:

- AI Execution
- Knowledge Retrieval

Contains:

- Agent Runtime
- Knowledge Platform

---

## Infrastructure

Responsibilities:

- Database
- Redis
- Storage
- Workers
- Logging
- Configuration

# 9. Backend Component Architecture

```mermaid
flowchart LR

Controller["REST Controllers"]
Application["Application Services"]
Professional["Professional Domain"]
ApplicationDomain["Application Domain"]
KnowledgeDomain["Knowledge Domain"]
Repositories["Repositories"]
Infrastructure["Infrastructure"]

Controller --> Application

Application --> Professional
Application --> ApplicationDomain
Application --> KnowledgeDomain

Professional --> Repositories
ApplicationDomain --> Repositories
KnowledgeDomain --> Repositories

Repositories --> Infrastructure
```

## Purpose

The backend follows Clean Architecture principles.

Each layer has a single responsibility.

Business rules are isolated from infrastructure and AI execution.

---

## Responsibilities

### REST Controllers

- Validate HTTP requests
- Authenticate users
- Convert DTOs
- Return HTTP responses

Controllers never contain business logic.

---

### Application Services

Responsible for orchestrating business use cases.

Examples:

- Tailor Resume
- Submit Application
- Research Company
- Prepare Interview

Application Services coordinate domains and platform services.

---

### Business Domains

Business Domains enforce deterministic rules.

Current domains:

- Professional Domain
- Application Domain
- Knowledge Domain

Business Domains never call AI providers.

---

### Repositories

Repositories abstract persistence.

Responsibilities:

- Load Aggregates
- Save Aggregates
- Query Read Models

Repositories never contain business logic.

---

# 10. Agent Runtime

```mermaid
flowchart TB

Request["Workflow Request"]

Engine["Workflow Engine"]

Planner["Planner"]

Registry["Agent Registry"]

Memory["Memory Manager"]

Tools["Tool Registry"]

Approval["Approval Manager"]

Gateway["AI Gateway"]

Provider["LLM Provider"]

Request --> Engine

Engine --> Planner

Planner --> Registry

Registry --> Memory

Memory --> Tools

Tools --> Gateway

Gateway --> Provider

Engine --> Approval
```

## Purpose

The Agent Runtime is responsible for executing every intelligent workflow inside CareerHQ.

It provides AI capabilities without owning business entities.

Business Domains remain deterministic.

---

## Responsibilities

- Execute workflows
- Coordinate agents
- Manage workflow state
- Invoke tools
- Retrieve knowledge
- Route AI requests
- Pause for approval
- Resume execution
- Record execution metadata

---

## Runtime Boundaries

The Agent Runtime **owns**:

- Workflow execution
- Planning
- Tool invocation
- AI communication
- Temporary memory

The Agent Runtime **does not own**:

- Professional Profiles
- Applications
- Resume Versions
- Company Research
- Business validation

---

# 11. Workflow Engine

```mermaid
stateDiagram-v2

[*] --> Created

Created --> Running

Running --> WaitingApproval

WaitingApproval --> Running

Running --> Completed

Running --> Failed

Failed --> Retrying

Retrying --> Running
```

## Responsibilities

- Start workflows
- Execute workflow graph
- Persist execution state
- Retry failed steps
- Resume paused execution
- Publish workflow events

The Workflow Engine is independent of any specific orchestration framework.

Current implementation:

- LangGraph

---

# 12. Planner

```mermaid
flowchart LR

Goal["Workflow Goal"]

Plan["Execution Plan"]

Step1["Step 1"]

Step2["Step 2"]

Step3["Step 3"]

Complete["Completed"]

Goal --> Plan

Plan --> Step1

Step1 --> Step2

Step2 --> Step3

Step3 --> Complete
```

## Purpose

The Planner converts business goals into executable workflow steps.

Current implementation:

Deterministic planning.

Future implementation:

Dynamic planning based on workflow context.

---

## Example

Resume Tailoring

```mermaid
flowchart LR

Analyze["Analyze Job"]

Retrieve["Retrieve Context"]

Tailor["Tailor Resume"]

Review["Review Resume"]

Approval["Approval"]

Analyze --> Retrieve

Retrieve --> Tailor

Tailor --> Review

Review --> Approval
```

---

# 13. Agent Registry

```mermaid
flowchart TB

Registry["Agent Registry"]

Job["Job Analysis Agent"]

Tailor["Resume Tailoring Agent"]

Review["Resume Review Agent"]

Research["Company Research Agent"]

Career["Career Advisor Agent"]

Interview["Interview Preparation Agent"]

Registry --> Job

Registry --> Tailor

Registry --> Review

Registry --> Research

Registry --> Career

Registry --> Interview
```

## Purpose

The Agent Registry maintains all available AI agents.

Agents are stateless execution units.

Each agent declares:

- Input Schema
- Output Schema
- Supported Models
- Required Tools
- Configuration

---

# 14. Tool Registry

```mermaid
flowchart LR

Agent["Agent"]

Registry["Tool Registry"]

Knowledge["Knowledge Retrieval"]

Search["Web Search"]

ATS["ATS Analyzer"]

Diff["Resume Diff"]

Export["PDF Export"]

Company["Company Lookup"]

Salary["Salary Lookup"]

Agent --> Registry

Registry --> Knowledge
Registry --> Search
Registry --> ATS
Registry --> Diff
Registry --> Export
Registry --> Company
Registry --> Salary
```

## Purpose

The Tool Registry exposes reusable capabilities.

Agents invoke tools through a common interface.

Tools may interact with:

- Knowledge Platform
- Infrastructure
- External Providers

Agents never communicate directly with external systems.

---

# 15. AI Gateway

```mermaid
flowchart TB

Runtime["Agent Runtime"]

Gateway["AI Gateway"]

Router["Model Router"]

Validator["Output Validator"]

Logger["Execution Logger"]

Cost["Cost Tracker"]

OpenAI["OpenAI"]

Anthropic["Anthropic"]

Gemini["Gemini"]

Runtime --> Gateway

Gateway --> Router

Gateway --> Validator

Gateway --> Logger

Gateway --> Cost

Router --> OpenAI
Router --> Anthropic
Router --> Gemini
```

## Purpose

The AI Gateway provides a single integration point for all language models.

Business code remains completely independent from AI providers.

---

## Responsibilities

- Provider Routing
- Model Selection
- Retry Strategy
- Rate Limiting
- Cost Tracking
- Structured Output Validation
- Request Logging
- Response Normalization

---

## Design Decisions

- Business logic never communicates directly with model providers.
- Model providers are replaceable.
- Every AI response is validated before returning to the Agent Runtime.
- All AI requests are observable and auditable.

---