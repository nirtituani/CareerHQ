# Feature Specification: Platform Foundation

**Feature Branch**: `001-platform-foundation`

**Created**: 2026-08-05

**Status**: Draft

**Input**: User description: "Foundation slice for CareerHQ. Establish the running skeleton of the platform that every later feature builds on: a containerized development environment, an authenticated user session, and a health-checked API/UI pair. Scope: (1) A user can sign in with their Google account and see a personalized empty dashboard, and sign out. First sign-in creates their user record and their single empty Professional Profile. (2) The system runs entirely via Docker Compose with PostgreSQL (pgvector enabled), Redis, and S3-compatible object storage (MinIO) available for later slices. (3) A backend REST API exists with a health endpoint, layered structure (api/application/domain/infrastructure), database schema migrations, and interactive API documentation. (4) A web frontend exists with the sign-in flow, an authenticated shell (navigation, user menu), and an empty dashboard placeholder. (5) Automated quality gates run on every change: backend lint, type check, and tests; frontend build and tests. Explicitly NOT in this slice: applications tracking, professional profile editing, resume features, or any AI capability. Success means a developer can clone the repo, run one command, sign in with Google, and land on an authenticated dashboard, with all quality gates green."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start the whole platform with one command (Priority: P1)

A developer clones the repository, provides configuration values, and runs a single command. Every
service the platform needs — the web application, the API, the database, the cache, and file storage —
starts together and reports that it is healthy. The developer can confirm readiness without reading
logs or starting services individually.

**Why this priority**: Nothing else in CareerHQ can be built, demonstrated, or tested until the
environment starts reliably. This story alone delivers value: it is the reusable substrate for every
future slice.

**Independent Test**: On a machine with no prior project state, clone the repository, copy the example
configuration, run the single startup command, and confirm the health check reports every dependency
as reachable and the web application loads in a browser.

**Acceptance Scenarios**:

1. **Given** a freshly cloned repository and valid configuration, **When** the developer runs the
   documented startup command, **Then** all services start and the health check reports the system and
   each of its dependencies (database, cache, object storage) as healthy.
2. **Given** the platform is running, **When** the developer opens the API documentation page,
   **Then** an interactive listing of available endpoints is displayed.
3. **Given** the platform has never been started before, **When** it starts for the first time,
   **Then** the database schema is created automatically to the current version without manual steps.
4. **Given** a required configuration value is missing, **When** the platform starts, **Then** startup
   fails immediately with a message naming the missing value rather than failing later at runtime.

---

### User Story 2 - Sign in and reach a personal workspace (Priority: P2)

A job seeker visits CareerHQ, signs in with their Google account, and arrives at their own workspace.
On first sign-in the system creates their account and an empty professional profile that later features
will fill. On return visits they go straight to their workspace. They can sign out at any time, and
their workspace is never visible to anyone else.

**Why this priority**: Identity and per-user data isolation are prerequisites for every user-facing
feature; every later entity is owned by a user. It follows P1 because signing in requires a running
system.

**Independent Test**: With the platform running, visit the application while signed out, complete the
Google sign-in flow, confirm arrival at a personalized empty workspace showing the signed-in identity,
sign out, and confirm the workspace is no longer reachable.

**Acceptance Scenarios**:

1. **Given** an unauthenticated visitor, **When** they open any workspace page, **Then** they are sent
   to the sign-in page instead of seeing workspace content.
2. **Given** a visitor on the sign-in page, **When** they complete Google sign-in for the first time,
   **Then** an account and exactly one empty professional profile are created for them and they land on
   their workspace.
3. **Given** a returning user, **When** they sign in again, **Then** they reach their existing
   workspace and no additional account or professional profile is created.
4. **Given** a signed-in user, **When** they view the workspace shell, **Then** their name or email and
   navigation to future sections are visible.
5. **Given** a signed-in user, **When** they choose to sign out, **Then** their session ends and
   returning to a workspace page requires signing in again.
6. **Given** a signed-in user, **When** the system serves their workspace data, **Then** only records
   owned by that user are returned.

---

### User Story 3 - Every change is automatically checked (Priority: P3)

A contributor proposes a change. Automated checks run without anyone asking: code style, type
correctness, and tests for the backend, plus a production build and tests for the web application. The
result is visible on the change itself, so broken work is caught before it is merged.

**Why this priority**: Quality gates protect the constitutional guarantees (approval flow,
immutability, ownership isolation) as the codebase grows. Valuable from day one but not required for a
first demonstration.

**Independent Test**: Push a branch containing a deliberate style violation, type error, and failing
test; confirm the automated checks fail and identify each problem. Fix them and confirm the checks pass.

**Acceptance Scenarios**:

1. **Given** a proposed change, **When** it is pushed, **Then** style, type, and test checks run
   automatically for the backend and a build plus tests run for the web application.
2. **Given** a change that violates style, type, or test rules, **When** checks run, **Then** the
   result is reported as failed and names the specific violation.
3. **Given** a developer working locally, **When** they run the documented check command, **Then** they
   get the same results the automated pipeline produces.

---

### Edge Cases

- **Sign-in declined**: The user cancels or denies consent at the Google prompt — they return to the
  sign-in page with an explanation and can retry; no account is created.
- **Concurrent first sign-in**: Two sign-in attempts for the same brand-new account arrive at the same
  time — exactly one account and one professional profile exist afterward.
- **Session no longer valid**: A session expires or its account no longer exists — the next request is
  treated as unauthenticated and the user is returned to sign-in rather than shown an error page.
- **Dependency unavailable**: The database, cache, or object storage is unreachable — the health check
  reports which dependency is failing rather than reporting overall success.
- **Web application starts before the API is ready**: The workspace shows a temporary unavailable state
  and recovers automatically once the API becomes healthy, without requiring a page reload loop.
- **Port already in use**: Startup fails with a message identifying the conflicting port.
- **Tampered or forged session credential**: The request is rejected as unauthenticated.
- **Repeated failed sign-in attempts**: The system does not reveal whether an account exists for a given
  address.

## Requirements *(mandatory)*

### Functional Requirements

**Environment and operations**

- **FR-001**: The system MUST start all of its services — web application, API, database, cache, and
  object storage — with a single documented command on a developer machine.
- **FR-002**: The system MUST provide a health endpoint that reports overall status plus the
  reachability of the database, cache, and object storage individually.
- **FR-003**: The system MUST apply database schema migrations automatically on startup, and MUST
  support versioned, reversible schema changes.
- **FR-004**: The system MUST enable vector-similarity storage capability in the database at
  initialization, so later knowledge features require no environment change.
- **FR-005**: The system MUST read all environment-specific values (credentials, secrets, service
  locations) from configuration, MUST ship an example configuration file, and MUST NOT contain real
  secrets in version control.
- **FR-006**: The system MUST fail fast at startup with an explicit message when required configuration
  is missing or invalid.
- **FR-007**: The system MUST publish interactive API documentation generated from the API definition.
- **FR-008**: The system MUST emit structured logs that include a request correlation identifier for
  every API request.

**Identity and access**

- **FR-009**: Users MUST be able to sign in using their Google account.
- **FR-010**: On a user's first successful sign-in, the system MUST create exactly one account record
  and exactly one empty professional profile owned by that account.
- **FR-011**: On subsequent sign-ins, the system MUST reuse the existing account and MUST NOT create an
  additional professional profile.
- **FR-012**: The system MUST maintain an authenticated session across page loads until it expires or
  the user signs out.
- **FR-013**: Users MUST be able to sign out, after which protected content requires signing in again.
- **FR-014**: The system MUST reject unauthenticated or invalid-session requests to protected endpoints
  and MUST redirect unauthenticated visitors from protected pages to sign-in.
- **FR-015**: The system MUST scope every data query to the requesting user, so no user can read or
  modify another user's records.
- **FR-016**: The system MUST store session credentials in a way that is not readable by browser
  scripts and MUST transmit them only over secure connections outside local development.

**Web application**

- **FR-017**: The web application MUST provide a sign-in page for unauthenticated visitors and an
  authenticated shell containing navigation and a user menu showing the signed-in identity.
- **FR-018**: The web application MUST present an empty dashboard placeholder that states no data exists
  yet and indicates what future features will appear there.
- **FR-019**: The web application MUST display a clear, non-technical message when the API is
  unreachable, and MUST recover once it is available again.

**Quality gates**

- **FR-020**: The system MUST run backend style checks, type checks, and automated tests on every
  proposed change, and MUST report failure when any of them fails.
- **FR-021**: The system MUST run a production build and automated tests for the web application on
  every proposed change.
- **FR-022**: The system MUST let a developer run the same checks locally with a documented command.
- **FR-023**: Automated tests MUST cover, at minimum, the health endpoint, first-sign-in account and
  profile creation, returning-user sign-in, sign-out, rejection of unauthenticated access, and
  cross-user data isolation.

### Key Entities

- **User**: A person who signs in to CareerHQ. Identified by their verified email address and the
  identity issued by the sign-in provider. Owns all of their data. Records when the account was created
  and last used.
- **Professional Profile**: The single container for a user's professional knowledge, created empty at
  first sign-in. Exactly one per user. Holds no content in this slice; later slices populate it.
- **Session**: Proof that a browser is acting on behalf of a signed-in user. Has an expiry and can be
  ended by signing out.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Starting from a fresh clone, a developer reaches a fully healthy running system in under
  15 minutes, using one startup command plus filling in configuration values.
- **SC-002**: A new user completes sign-in and sees their workspace in under 30 seconds and no more than
  3 interactions from the landing page.
- **SC-003**: 100% of protected pages and endpoints deny access without a valid session, verified by
  automated tests.
- **SC-004**: A user account has exactly one professional profile after any number of sign-ins,
  verified by automated tests including a simultaneous first-sign-in case.
- **SC-005**: Attempts to read another user's data return no data in 100% of tested cases.
- **SC-006**: Automated quality checks complete in under 10 minutes and fail whenever a style, type,
  test, or build error is present.
- **SC-007**: Automated tests cover at least 80% of backend code in this slice.
- **SC-008**: The health check reports each unavailable dependency by name in 100% of simulated outage
  cases.

## Assumptions

- **Open registration**: Any valid Google account may sign in and will be provisioned automatically.
  No invitation, allowlist, or admin approval exists in this slice.
- **Single identity provider**: Google is the only sign-in method. Email/password and other providers
  are deferred, though the design keeps room for them.
- **Session lifetime**: Sessions remain valid for 7 days of inactivity by default and are configurable.
  This is a convenience default for a personal-productivity tool, not a compliance requirement.
- **Users have modern browsers** with cookies enabled and stable internet connectivity, consistent with
  the product-level assumption that connectivity is available.
- **Local development target**: This slice targets a developer machine. Production hosting, custom
  domains, and TLS termination are deferred to a later deployment slice; secure-transport requirements
  apply once deployed.
- **Object storage and cache are provisioned but unused** by user-facing behavior in this slice. They
  exist so later slices (file export, workflow state) need no environment change.
- **Empty professional profile means a container with no content**, not a set of blank required fields;
  its internal structure is defined in a later slice.
- **JobTracker data is not imported here.** Migration from the existing JobTracker application is part
  of the applications-tracking slice.
- **Technology is fixed by the project constitution** (containerized services, relational database with
  vector capability, cache, object storage, Google sign-in). This specification states outcomes; the
  implementation plan selects the specific components within those constraints.

## Dependencies

- A Google Cloud OAuth client (client ID and secret) with authorized redirect URIs for local
  development must exist before sign-in can be exercised end to end.
- Container runtime available on the developer machine.
- A source-hosting service that can run automated checks on proposed changes.
