# Phase D memory evaluation and query-plan gate

Date: 2026-08-12
Branch: `codex/phase-d-memory`
Database: disposable PostgreSQL 16.14 + pgvector 0.8.6 only

## Synthetic fixture

- 3 synthetic organizations: `alpha`, `beta`, `gamma`
- 100 active memories per organization (300 total)
- 30 excluded samples per organization: 10 candidate, 10 superseded, 10 physically deleted
- 20 queries per organization (60 total)
- Categories: fact, preference, decision, correction, conflict, expired, no-answer,
  cross-organization, prompt-injection
- No customer content, credentials, runtime files, uploads, or provider responses

## Retrieval metrics

The FTS baseline and test-only deterministic embedding/RRF are reported separately. They are not
production/provider quality claims or substitutes for each other.

| Mode | Relevant queries | Precision@5 | Recall@5 | No-answer accuracy | p95 latency | Context token p95 | Authorization leaks |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Authorized PostgreSQL FTS-only | 57 | 0.0632 | 0.3158 | 1.0000 | 1.30 ms | 9 | 0 |
| Test-only deterministic vector/RRF | 57 | 0.1930 | 0.9649 | 0.0000 | 37.48 ms | 42 | 0 |

The deterministic fake returns nearest vectors for no-answer queries, so its no-answer score is
intentionally recorded as 0.0 and must not be treated as a production improvement. The deployable
baseline remains authorized FTS-only when no embedding provider is configured.

## EXPLAIN gate

`EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` on the same disposable database passed with no missing
memory FK indexes:

- list: `ix_memory_records_active_owner_list`
- FTS: `ix_memory_records_active_fts`
- vector: `ix_memory_records_active_embedding_hnsw`
- queue claim: `ix_memory_extraction_jobs_claim`

The vector statement is scoped by organization/user/status before ranking. If an ANN result needs
defense-in-depth, exact fallback is bounded to the same authorized owner and at most 100 embeddings.

## Reproduction

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://postgres@127.0.0.1:55432/phase_d_memory_eval2"
.\.venv\Scripts\python.exe scripts\evaluate_memory.py `
  --dataset tests/fixtures/memory_eval/dataset.json `
  --report E:/Temp/phase-d-memory-evaluation-v3.json `
  --allow-disposable-database
.\.venv\Scripts\python.exe scripts\verify_memory_query_plans.py `
  --report E:/Temp/phase-d-memory-query-plans-v3.json `
  --allow-disposable-database
```

The disposable instance was upgraded, evaluated, downgraded to `20260810_0012`, and upgraded to
`20260811_0013` again. It was then stopped; no shared, demo, or production database was used.
