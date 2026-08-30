---
state_id: ps-backend-mid
full_name: Dana Okonkwo
email: dana.okonkwo@example.com
headline: Backend Engineer
summary: Backend engineer with six years building payment and billing services in Python and Go. Comfortable
  owning a service end to end, from schema to on-call.
experiences:
- company: Meridian Pay
  title: Senior Backend Engineer
  location: Tel Aviv
  start_date: 03/2021
  end_date: ''
  is_current: true
  ordinal: 0
  bullets:
  - Rebuilt the settlement ledger on PostgreSQL, cutting end-of-day reconciliation from four hours to
    eleven minutes.
  - Introduced idempotency keys across the payments API after a duplicate-charge incident, and wrote the
    runbook the team still uses.
  - Mentored two junior engineers through their first on-call rotations.
  - Migrated seventeen services from a shared database to per-service schemas over three quarters.
- company: Halcyon Logistics
  title: Backend Engineer
  location: Haifa
  start_date: 07/2018
  end_date: 02/2021
  is_current: false
  ordinal: 1
  bullets:
  - Built the route-assignment service in Go, serving 40,000 dispatch decisions a day.
  - Replaced nightly CSV exports with a change-data-capture pipeline into the warehouse.
  - Cut container image size from 1.2 GB to 180 MB, which took deploy time from nine minutes to under
    two.
skills:
- name: Python
  category: Languages
- name: Go
  category: Languages
- name: PostgreSQL
  category: Data
- name: Docker
  category: Infrastructure
- name: Kubernetes
  category: Infrastructure
- name: FastAPI
  category: Frameworks
- name: Redis
  category: Data
- name: Terraform
  category: Infrastructure
education:
- institution: Ben-Gurion University of the Negev
  qualification: B.Sc. in Software Engineering
  field_of_study: Software Engineering
  start_date: '2014'
  end_date: '2018'
  grade: '87'
languages:
- name: Hebrew
  proficiency: Native
- name: English
  proficiency: Fluent
certifications:
- name: Certified Kubernetes Administrator
  issuer: CNCF
  year: '2022'
projects:
- name: ledger-fuzz
  description: A property-based test harness for double-entry ledgers.
  url: https://example.com/ledger-fuzz
---

<!-- A SYNTHETIC profile state. Every person, employer and address here is invented.
     This repository is public; FR-005a and FR-039 forbid a real one from ever living
     in this directory. The real-world sanity set is gitignored (D2, FR-005c). -->
