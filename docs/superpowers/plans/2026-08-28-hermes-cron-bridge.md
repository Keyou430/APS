# Hermes Cron Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Hermes native cron the authoritative scheduler for confirmed platform pipeline tasks while preserving dashboard outputs and approval/regeneration behavior.

**Architecture:** The platform creates task metadata and a native Hermes cron job in one confirmed workflow, persists the Hermes job id, and exposes a protected idempotent trigger endpoint for cron prompts. Platform scheduling skips Hermes-bound tasks; the existing pipeline worker continues producing outputs and dashboard decisions.

**Tech Stack:** FastAPI, SQLAlchemy/Alembic, asyncio subprocess, Hermes CLI.

---

### Task 1: Cron registration contract

**Files:** `backend/app/services/hermes_cron_bridge.py`, `backend/app/models/entities.py`, `backend/app/routers/pipeline.py`, migration, `backend/tests/test_pipeline_hermes_cron.py`

- [ ] Add failing tests for native cron registration, rollback on registration failure, and persistence of the job id.
- [ ] Implement the subprocess bridge and task creation integration.
- [ ] Run focused tests, then full backend tests.

### Task 2: Idempotent Hermes trigger

**Files:** `backend/app/routers/pipeline.py`, `backend/app/services/pipeline_repository.py`, `backend/tests/test_pipeline_hermes_cron.py`

- [ ] Add a failing test proving repeated trigger payloads create one run.
- [ ] Implement an authenticated internal trigger using task id plus scheduled slot.
- [ ] Verify the resulting run is visible to the existing worker and dashboard.

### Task 3: Scheduler ownership and Hermes MCP exposure

**Files:** `backend/app/services/pipeline_scheduler.py`, `hermes/MCP/src/hermes_mcp/server/factory.py`, `hermes/MCP/src/hermes_mcp/tools/platform_pipeline.py`, tests

- [ ] Add failing tests that Hermes-bound tasks are not locally enqueued and the MCP server exposes the trigger tool.
- [ ] Implement the skip and the minimal controlled tool/configuration.
- [ ] Run backend and Hermes MCP suites.

### Task 4: End-to-end verification

- [ ] Run migration, backend tests, MCP tests, frontend tests/build.
- [ ] Start Hermes and backend services, create a confirmed task, verify `hermes cron list`, task board data, and decision output.
