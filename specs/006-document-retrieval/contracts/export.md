# Contract: Export and Submission

## Export

**Precondition**: the version **has been approved and is not submitted** — `READY` or `EXPORTED`.
Export of anything else is refused (FR-016).

***Corrected 2026-08-28 (T036, the task that owns this line).*** It read *"the version is
`APPROVED`"*, which was wrong twice. **The state is `READY`**: the value has been `ready` since
migration `0010` and T005 kept it rather than rewriting the paid evaluation rows. And the literal
reading made a version exportable **exactly once ever**, because the postcondition moves it to
`EXPORTED` — while `ExportedDocument` deliberately carries **no unique constraint on
`resume_version_id`** precisely so a re-export is possible (*"a download that failed, a second
copy"*). FR-016 asks whether a version *has been approved*, not what its status literal is now.
`SUBMITTED` is refused because it is terminal: export sets the status to `EXPORTED`, and nothing
may leave `SUBMITTED` (FR-022, FR-025).

**Postcondition**: rendered bytes in object storage, an `ExportedDocument` row with a SHA-256 over
those exact bytes, and the version at `EXPORTED` (FR-019).

### The six ATS assertions

"ATS-safe" is defined as these, and verified with `pdfplumber` — an **independent extractor**,
already a dependency, already trusted for CV import.

| # | Assertion | How it is checked |
|---|---|---|
| 1 | **Every approved resume item appears in the rendered document in approved order, and no unapproved resume item is presented as resume content** | Extract text; walk the approved items through it with a moving cursor (FR-017) |
| 2 | Real text, not images of text | Extraction returns content; no image object carries textual content |
| 3 | Single-column reading order | Word x-coordinates cluster into one column |
| 4 | No table structures | Extractor finds none (FR-018) |
| 5 | Character integrity | Round-tripped text matches — no ligature or Unicode mangling |
| 6 | **Byte-determinism, within one runtime environment** | Rendering identical content twice **on the same runtime** produces identical bytes |

***Assertion 1 was amended 2026-08-28.*** It read *"Text equals approved items, in approved
order"*, which **no conforming document can satisfy**: a résumé also carries a name, a contact
block and section headings, and FR-018 requires the contact details to be in the body. Read
literally it demanded a document with no structure. **Document structure — name, contact line,
section headings — is legitimate non-item content**; what must not appear is an *item* nobody
approved, and the test drills exactly that by rendering an unapproved line and confirming it is
named. The claim was clarified, not weakened.

**Assertions 1-5 are T031; assertion 6 is T032.** The split is not arbitrary: 1-5 are things
`pdfplumber` can see in the finished bytes, and 6 is a comparison *of* bytes, which no extractor is
involved in. T035's metadata and timestamp pinning is what will make 6 hold.

**Assertion 6 is a requirement, not a preference.** Without byte-determinism the "stable checksum"
FR-021 requires is unstable, and the failure only appears when someone re-exports.

***Scoped to one runtime environment, 2026-08-28 (T032).*** The obligation is what FR-021 and
Constitution IV actually need: verification compares the **stored bytes** against a recorded
checksum and never re-renders, and FR-031's own failure mode is a **re-export** — which happens on
the deployed runtime. A developer's macOS host has no DejaVu and resolves to Verdana, so its bytes
differ from the image's; nothing in the specs asks a laptop to reproduce production bytes, and
making it do so would mean vendoring a font to satisfy a requirement nobody stated. **The test is
not weakened by this**: it still renders the same document twice, in two separate processes, and
demands byte-identical output.

***The font is part of the guarantee, and is now declared.*** Which font resolves decides the
rendered bytes — measured: swapping the family changes an 8,885-byte document to 11,499. DejaVu
reached the image *transitively*; `fonts-dejavu-core` is now an explicit apt dependency in
`backend/Dockerfile` (T032, amending T049), so a base image that stopped supplying it fails the
build's declared contract rather than silently changing every export.

***R10's premise does not hold at WeasyPrint 69.0, measured.*** It states that "PDFs embed a
creation timestamp and document ID by default". This renderer emits **no `/CreationDate`, no
`/ModDate` and no `/ID`**; two renders in separate processes are already byte-identical. **No
normalization code was added** — there was nothing to normalize. Assertion 6 is therefore a
regression gate against a future version reintroducing one, which is why it is asserted on the
specific keys and not only on byte equality.

## Submission

**Precondition**: the version is `EXPORTED`, and the stored bytes still match the recorded
checksum.

**Postcondition**: an insert-only `SubmittedResume`, the version at `SUBMITTED`, the application
referencing it (FR-024).

**Refusals are explicit** (FR-022): a modification attempt returns an error naming the reason. It
is never silently ignored — a silent no-op on an immutability guarantee is indistinguishable from
success, and Constitution IV makes this a release blocker.

**Post-submission revision** creates a new version (FR-025). No path mutates a submitted one.
