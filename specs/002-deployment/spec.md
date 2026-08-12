# Feature Specification: Deployment

**Feature Branch**: `002-deployment`

**Created**: 2026-08-12

**Status**: Draft

**Input**: User description: "Slice 002 — Deployment. Run CareerHQ at a public HTTPS URL on Railway, built from the same Docker images used locally, and redeploy it automatically whenever work merges to main. Scope is deliberately small, per docs/05 §5.2 and docs/08 §3.5. Railway hosts the backend and the frontend from the existing Dockerfiles; the backend connects to the already-provisioned pgvector Postgres; secrets are configured; PUBLIC_BASE_URL drives the OAuth redirect; ENVIRONMENT=production runs for the first time, activating HSTS, Secure cookies and https_only sessions, which must be verified against the deployed site rather than assumed; merging to main redeploys with CI gating it; the quickstart documents deploying and rolling back. Redis and object storage are NOT deployed, which forces the readiness endpoint to probe only the dependencies that are actually configured while staying honest about what it did not check. No application features. Done when a real Google sign-in succeeds on the public URL creating exactly one user and one profile, readiness reports truthfully, production security is observed in real responses, and a merge redeploys automatically."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Reach CareerHQ from anywhere, without installing anything (Priority: P1)

A person is given a web address. They open it on a device that has never run CareerHQ, has no
copy of the source, and has no development tools installed. The site loads over a secure
connection and presents the sign-in page. An operator, separately, can ask the running system
whether it is healthy and get an answer that names each dependency it actually checked.

**Why this priority**: This is the slice's reason for existing. Everything else in CareerHQ has
so far been demonstrable only on the author's machine, which makes it unverifiable by anyone
else. A public address is also a graded project requirement, and every later slice ships onto
whatever this establishes.

**Independent Test**: From a device with no project setup — a phone on mobile data is the
strictest version — open the address and confirm the sign-in page renders over a secure
connection. Separately, request the readiness report and confirm it names the dependencies it
checked.

**Acceptance Scenarios**:

1. **Given** a device with no CareerHQ source, tooling, or prior session, **When** a person
   opens the public address, **Then** the sign-in page loads over a secure connection.
2. **Given** the deployed system, **When** an operator requests the readiness report, **Then** it
   names each dependency that was checked and its result, and does not report a healthy result
   for any dependency it did not check.
3. **Given** a dependency that is deliberately not deployed in this slice, **When** readiness is
   requested, **Then** the report makes clear that dependency was not checked, and the overall
   result is not failed on its account.
4. **Given** a dependency that is deployed but unreachable, **When** readiness is requested,
   **Then** the overall result is failed and the response describes the kind of failure without
   disclosing internal addresses, ports, or credentials.
5. **Given** an attempt to reach the site over an insecure connection, **When** the request is
   made, **Then** the person ends up on the secure address.

---

### User Story 2 - Sign in on the public site and land in your own workspace (Priority: P2)

A job seeker opens the public address, signs in with their Google account, and arrives at their
own dashboard. On first sign-in the system creates their account and their single empty
professional profile. Their session survives a page reload and is protected in transit.

**Why this priority**: A site that loads but cannot authenticate is a landing page, not an
application. This story is what proves the deployment is genuinely functional — it exercises the
database, the migrations, the session layer, and the external identity provider together. It is
also the first time the production security configuration executes at all.

**Independent Test**: On a device with no prior session, complete a real Google sign-in against
the public address, confirm arrival at the dashboard, then confirm the account and profile counts
increased by exactly one each and that a second sign-in creates no duplicates.

**Acceptance Scenarios**:

1. **Given** a person who has never used CareerHQ, **When** they sign in with Google on the
   public address, **Then** they arrive at their dashboard, and exactly one account and exactly
   one professional profile now exist for them.
2. **Given** a person who has signed in before, **When** they sign in again, **Then** they reach
   their existing workspace and no second account or profile is created.
3. **Given** a completed sign-in, **When** the session credential is inspected as a browser would
   see it, **Then** it is marked so that it is sent only over secure connections and is not
   readable by page scripts.
4. **Given** any response from the deployed site, **When** its headers are inspected, **Then**
   they instruct the browser to use only secure connections for future visits.
5. **Given** a person who declines consent at the identity provider, **When** they are returned
   to the site, **Then** the outcome is explained to them and no account or profile is created.
6. **Given** a signed-in person, **When** they reload the page, **Then** they remain signed in.
7. **Given** a signed-out visitor, **When** they request a page that requires an account, **Then**
   they are sent to sign in.

---

### User Story 3 - Merged work reaches the public site without anyone deploying it (Priority: P3)

A change is merged into the main line of development. The project's existing quality gates run.
If they pass, the public site is updated with that change without any further human action. If
they fail, the public site is left untouched. Anyone can see which version is currently live, and
a bad release can be returned to the previous one.

**Why this priority**: Manual deployment is reliable exactly until the moment someone is tired or
rushed. Automating it now means every later slice ships continuously rather than accumulating an
un-deployed backlog — which is the failure mode that makes end-of-project deployment a disaster.
It is P3 because the previous two stories deliver a working public site on their own; this makes
keeping it current sustainable.

**Independent Test**: Merge a trivial, visible change and confirm it appears on the public site
without further action. Separately, merge a change that deliberately fails a gate and confirm the
public site is unchanged.

**Acceptance Scenarios**:

1. **Given** a change merged to the main line, **When** the quality gates pass, **Then** the
   public site serves that change without any manual step.
2. **Given** a change merged to the main line, **When** any quality gate fails, **Then** the
   public site continues to serve the previous version and the failure is visible.
3. **Given** a release that proves faulty, **When** an operator follows the documented rollback,
   **Then** the public site returns to the previously working version.
4. **Given** a deployment in progress, **When** an operator looks for its status, **Then** they
   can see whether it succeeded or failed and read the reason.
5. **Given** a schema change included in a merge, **When** the deployment runs, **Then** the
   schema is brought up to date automatically before the new version begins serving traffic.

---

### Edge Cases

- **A dependency is configured but unreachable.** Readiness must fail overall, name which
  dependency, and disclose the kind of failure only — never the internal address, port, or
  account it used.
- **A dependency is not configured at all.** Readiness must not fail on its account, and must not
  claim it was checked. Silence and a false "healthy" are both wrong.
- **The identity provider does not recognise the deployed address.** Sign-in fails at the provider
  rather than in CareerHQ. The specific address to register is a manual step outside the system
  and must be recorded, not discovered by trial and error.
- **A schema change fails to apply during deployment.** The new version must not begin serving
  traffic on a database it cannot use.
- **A deployment starts while a previous one is still running.** The site must end in a defined
  state — one of the two versions, not a mixture.
- **A person reaches the site over an insecure connection**, or has previously visited over one.
- **A required secret is missing or malformed at deploy time.** Startup must fail immediately and
  name the missing setting, rather than failing later at the first request that needs it.
- **Someone attempts to reach the database directly** from outside the deployment.
- **Both quality gates and the deployment are triggered by the same merge.** Deployment must not
  race ahead of the gates.

## Requirements *(mandatory)*

### Functional Requirements

**Public availability**

- **FR-001**: The system MUST be reachable at a stable public web address over a secure
  connection, without the visitor installing or configuring anything.
- **FR-002**: The system MUST redirect insecure requests to the secure address.
- **FR-003**: The system MUST serve the identical application that runs locally, built from the
  same container definitions, so that local behaviour is evidence about deployed behaviour.

**Honest health reporting**

- **FR-004**: The system MUST expose a readiness report that names each dependency it checked and
  the result of that check.
- **FR-005**: The readiness report MUST check only those dependencies that are configured for the
  running environment.
- **FR-006**: The readiness report MUST NOT report a successful result for any dependency it did
  not check, and MUST make the distinction between "checked and healthy" and "not configured"
  evident to a reader.
- **FR-007**: Overall readiness MUST fail when a configured dependency is unreachable, and MUST
  NOT fail merely because a dependency is absent by design.
- **FR-008**: When a dependency check fails, the response to an unauthenticated caller MUST
  describe the kind of failure only; the diagnostic detail MUST be available to an operator
  through the system's own logs.

**Identity on the public address**

- **FR-009**: A person MUST be able to sign in with their Google account on the public address and
  reach their own workspace.
- **FR-010**: First sign-in MUST create exactly one account and exactly one professional profile;
  subsequent sign-ins MUST create neither.
- **FR-011**: Every browser-facing address the system generates — the identity provider's return
  address in particular — MUST be derived from a single configured public address rather than
  from the incoming request.
- **FR-012**: The address that must be registered with the identity provider MUST be stated
  explicitly in the project's documentation, since registering it is a manual action outside the
  system.

**Production security, observed rather than assumed**

- **FR-013**: Session credentials issued by the deployed system MUST be restricted to secure
  connections and MUST NOT be readable by page scripts.
- **FR-014**: Responses from the deployed system MUST instruct browsers to use only secure
  connections for subsequent visits.
- **FR-015**: The protections in FR-013 and FR-014 MUST be verified by observing real responses
  and real credentials from the deployed system. Reading the source is not sufficient evidence,
  because this configuration has never executed.
- **FR-016**: Data stores MUST NOT be reachable from the public internet; only the application
  may reach them.
- **FR-017**: Secrets MUST be supplied to the deployed system as configuration and MUST NOT
  appear in the source repository or in any log output.
- **FR-018**: The system MUST refuse to start when a required secret is missing or invalid, and
  MUST name the setting at fault without printing its value.

**Continuous deployment**

- **FR-019**: Merging into the main line MUST update the public site without further human action.
- **FR-020**: The existing quality gates MUST complete successfully before any deployment begins;
  a failing gate MUST leave the public site unchanged.
- **FR-021**: Schema changes MUST be applied automatically during deployment, before the new
  version begins serving traffic.
- **FR-022**: An operator MUST be able to see which version is currently live, whether the last
  deployment succeeded, and why it failed if it did.
- **FR-023**: An operator MUST be able to return the public site to the previously working
  version, and the procedure for doing so MUST be documented.
- **FR-024**: The documentation MUST state which parts of a release cannot be undone by returning
  to a previous version — in particular that a schema change which discards data is not reversed
  by redeploying older code.

**Scope discipline**

- **FR-025**: This slice MUST NOT change any behaviour a signed-in user can observe, beyond the
  system being reachable at a public address.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A person given only the public web address, on a device with no project setup, can
  load the sign-in page. Verified from a device that has never run CareerHQ.
- **SC-002**: A person completes a first sign-in on the public address and reaches their
  dashboard, and account and profile counts each increase by exactly one. A second sign-in by the
  same person increases neither.
- **SC-003**: The readiness report for the deployed system names every dependency that is
  deployed, reports each one's result, and claims no result for any dependency that is not
  deployed. Confirmed against the deployed system, not a local one.
- **SC-004**: Secure-connection enforcement and session credential protection are confirmed by
  inspecting real responses and real credentials from the deployed system — the first time this
  configuration has ever been observed running.
- **SC-005**: A change merged into the main line appears on the public site with no human action
  between the merge and the change being live.
- **SC-006**: A merge whose quality gates fail results in no change to the public site, and the
  failure is visible to the author without inspecting the deployed system.
- **SC-007**: An operator who has not deployed this system before can deploy it, find the status
  of that deployment, and return to the previous version using only the project's documentation.
- **SC-008**: The database is not reachable from the public internet; an attempt to connect from
  outside the deployment fails.
- **SC-009**: No signed-in user can observe any behavioural difference from the previous slice
  other than the address the system is reached at.

## Assumptions

- **The database is already provisioned and verified.** A managed Postgres carrying the vector
  extension exists in the hosting environment, confirmed as PostgreSQL 18.4 with vector 0.8.6
  created successfully. This is established fact, not an assumption to re-test; it closed
  assumption A2 and open question Q1 in `docs/08`.
- **Local and deployed run the same major database version.** The local environment was moved to
  match the deployed one, so local behaviour is evidence about deployed behaviour.
- **One public address, not two.** The web interface is the only publicly reachable service and
  forwards interface-to-service requests internally, mirroring the local arrangement. This keeps
  a single configured public address, which is what the identity provider's return address is
  derived from, and avoids cross-origin configuration.
- **Registering the return address with the identity provider is a manual action by the author.**
  It requires access to an external account that the system cannot and should not automate.
- **Cache and object storage are deliberately absent.** No feature uses them yet. They arrive with
  slices 003 and 004, at which point they become configured dependencies and readiness begins
  checking them without further change.
  **They are not merely unused, though — they are currently *required* configuration**, so the
  system cannot start without values for them. Making that configuration optional is therefore
  prerequisite to any deployment work, not a consequence of it. Sizing this slice from the
  readiness report alone would understate it.
- **A single deployment region and the hosting provider's generated address are sufficient.** No
  custom domain, content delivery network, automatic scaling, or alerting is in scope.
- **Rollback is an operator action, not an automatic response.** The system does not attempt to
  detect a bad release and revert itself; a person decides.
- **The existing quality gates are the release gate.** No new categories of test are introduced by
  this slice; the code change it contains is covered by the existing suite.
