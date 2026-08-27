# Backend Difficulty Analysis

## 1. Hermes Integration Challenges and Resolutions

Hermes exposes no supported memory-write API (`memory_write_api: False`). The platform-owned
PostgreSQL/pgvector memory ledger is the only durable memory source of truth. External extraction
providers may return validated candidates, but cannot own scope, authorization, state, or writes.
Platform memory CRUD never edits `MEMORY.md` or treats Hermes runtime memory as authoritative.

Chat uses the stateful `/v1/responses` API. The platform sends a new message plus a Hermes session
identifier instead of rebuilding full history. Before production acceptance, validate tool calling,
event ordering, session retention, cancellation, and reconnect behavior against the pinned Hermes
version.

Profile lifecycle remains an integration risk. The current manager deliberately produces metadata;
runtime reconciliation, secrets injection, readiness checks, and cleanup must remain outside HTTP
transactions and must never make profile paths or credentials client-controlled.

## 2. Multi-Tenancy Architecture

The platform stores organizations, active memberships, normalized role permissions, and a
server-selected current organization in signed access-token context. Persistent Hermes
profiles, sessions, knowledge, skills, and reminders carry an organization key and retain existing
user ownership as a lower-level guard. Legacy role permission JSON remains for compatibility;
`Permission` and `RolePermission` are the authorization source of truth.

Hermes profile multiplexing is process efficiency, not a security boundary. Tool execution and
filesystem access still require the existing per-user sandbox. Memory and RAG requests always use
server-derived organization and user scope. Provider credentials are runtime secrets
and never copied into profile metadata or audit records.

## 3. Scaling Strategy

A single multiplexing gateway is the recommended starting point because it reduces idle process cost
and centralizes routing. Scale gateways horizontally by stable profile-to-shard mapping and route
all events for one run to the same shard. Keep PostgreSQL behind an async connection pool and bound
pool size per API replica.

SSE connections are long-lived. Production ingress must disable buffering, raise idle timeouts,
send heartbeats, and cap concurrent streams per user and tenant. Track active streams, time to first
token, disconnects, and Hermes run failures. Move stream recovery metadata to a shared store before
running more than one API replica.

## 4. Platform-Owned RAG Pipeline

The platform owns the RAG source of truth. Files are stored in a private object store, Docling runs
in a separate ingestion worker, and PostgreSQL 16 with pgvector stores versioned chunks and 1024
dimensional `text-embedding-v4` vectors. The API remains the authorization boundary; retrieval first
filters by the server-derived organization, user, and resource scope, then performs vector and
PostgreSQL full-text retrieval within that already-authorized set.

The first implementation uses deterministic heading/paragraph chunking, cosine HNSW plus simple
full-text search, and Reciprocal Rank Fusion. It returns bounded citations and never sends file
bytes, object keys, platform paths, or unfiltered document text to Hermes. The old
`/api/knowledge/search` response shape remains compatible while delegating to the same authorized
retrieval service.

Embedding credentials are worker-only runtime secrets. The embedding model, dimension, parser
version, and content hash are persisted as metadata so a model or parser change creates a new index
version instead of silently mixing vectors. Exit criteria are repeatable ingestion, idempotent
reprocessing, delete propagation, tenant-filtered retrieval, citation accuracy, and a measured
Chinese/English evaluation set. Any schema change requires a verified backup and separate approval.

## 5. Security Considerations

Profile separation does not by itself stop a Hermes tool from reading another profile's files. Keep
the existing per-user sandbox with read-only base images, explicit mounts, network egress policy,
CPU/memory limits, and short-lived credentials. Knowledge mode must not expose terminal/file tools
by default.

Enforce organization scope plus user ownership in every platform query. The authorization dependency
resolves an active membership from the signed current-organization context; clients cannot supply
a profile path, raw organization scope, or arbitrary source ids. Audit administrative profile,
membership, role, ingestion lifecycle, and retrieval outcome without logging prompts, tokens,
document contents, object keys, or provider response bodies.

The memory ledger and RAG object store must run in the private deployment or its approved equivalent.
Backups, deletion requests, retention, and encryption keys must cover PostgreSQL, object storage,
ingestion metadata, and memory capture sources.

## 6. Recommended Implementation Roadmap

### Phase 1: Stable Hermes Boundary and Internal Conversation

Entry: confirmed product scope, pinned Hermes commit, API decisions, and real auth/chat Beta.
Work: current FastAPI contract, PostgreSQL metadata, JWT/RBAC, compatibility mock streaming, private
Hermes HTTP adapter, capability probe, and frontend integration. Exit: migrations and tests pass,
the pinned container contract is probeable in a private environment, and compatibility behavior is
explicitly labelled.

### Phase 2: Hermes Runtime and Organization Boundaries

Entry: Phase 1 contract and organization authorization boundary are stable. Work: profile
reconciliation, configured real `/v1/responses` events, memory ledger operations, secrets, readiness, and
failure recovery. Exit: per-user and per-organization isolation tests, restart recovery, stream
cancellation, memory durability, and an operational runbook pass.

### Phase 3: Platform-Owned RAG and Retrieval Authorization

Entry: real chat and the organization boundary are reliable. Work: private object storage, Docling
parsing, asynchronous ingestion, text-embedding-v4, pgvector/full-text retrieval, citations, and
deletion propagation. Exit: retrieval quality meets the evaluation threshold and cross-tenant
access tests show no leakage. Database migration is blocked until backup and explicit confirmation.

### Phase 4: Production Hardening

Entry: feature and data contracts are stable. Work: rate limits, observability, disaster recovery,
key rotation, penetration testing, and capacity tests. Kubernetes, gateway sharding, and additional
tool capabilities remain upgrade paths rather than Phase 3 prerequisites.
