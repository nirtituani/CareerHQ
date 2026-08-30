# Benchmark results

**Committed on purpose.** A benchmark result is the record of an experiment, and it belongs beside
the spec that defines it — not inside a Docker volume.

The project's existing evaluation evidence, $3.562567 of it, lives in two local volumes with a
backup on the same machine that is already behind. `HANDOFF.md` opens with that as a red-flagged
risk. Results here are replicated by every clone, diffable, reviewable in a PR, and survive
`docker compose down -v`.

Each file records the configuration fingerprint it ran under — model per task, guideline source,
finalisation rules version, benchmark set version, corpus identity, embedding model, pricing basis.
Two results are comparable only where that fingerprint matches in every dimension but the one under
test. See [../data-model.md](../data-model.md) §2.3.

**Empty until D3 — the ceiling and the case counts — is approved.**
