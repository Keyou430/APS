# Smart Decisions Cockpit Design

## Purpose

The cockpit smart decision block is the primary decision-review surface. It sits directly below the cockpit data board as a full-width row and shows AI-generated decision results produced by scheduled AI service tasks.

## Current Contract Boundary

This document captured a future design direction. As of the current
OpenAPI snapshot, dashboard decisions are not registered backend operations.
Frontend code must not call `/dashboard/decisions` or any `/pipeline/*`
endpoint until the backend router, schema, OpenAPI snapshot, frontend
contract document, and contract tests are updated together.

The current acceptance-safe surface is read-only:

- `GET /dashboard` returns `DashboardDataResponse.pipelines`.
- `/pipeline` may render those `pipelines` and generate browser-local
  Markdown previews from the returned fields.
- Approval, rejection, regeneration, server-side task execution, and output
  download remain future work, not active frontend API contracts.

## Locked Decisions

- The cockpit layout places `智能决策` immediately below `数据看板` as a full-width card.
- `待办事务` and `日历摘要` move below the smart decision row.
- The cockpit does not generate AI decisions directly. Until decision APIs are frozen, it may only read existing dashboard pipeline summaries.
- AI service scheduled tasks create decision results from natural-language task definitions on the backend.
- The first viewport shows 5 high-priority recent decisions and a `查看全部` entry.
- `查看全部` opens an in-cockpit drawer with status filters: `全部 / 待决策 / 已同意 / 已驳回 / 重新生成中`.
- Each decision shows title, summary, recommended action, confidence, source task, generated time, status, and available actions.
- `同意` is available only for pending decisions. The backend approval flow records the approved result through backend/Agent-owned contracts; the frontend does not maintain an AI service memory library.
- `驳回` is available only for pending decisions. Rejection requires a reason.
- Rejection offers quick reasons `暂无需求` and `其他情况`, plus a free-text reason field.
- If the rejection reason is `暂无需求` or `其他情况`, the backend archives the decision without regeneration.
- Other rejection reasons let the backend trigger regeneration and preserve the rejected decision as history.
- Non-pending decisions show outcome details instead of action buttons.
- When `VITE_USE_MOCK=true`, the cockpit may use clearly bounded demo decisions. When `VITE_USE_MOCK=false`, unavailable contracts render the real error or empty state and never fall back to sample decisions.

## Future Frontend Contracts

Decision list, approve, reject, and regenerate behavior require a backend
contract first. When those operations exist in OpenAPI, update this spec and
the frontend API contract in the same change that introduces the service
adapter and tests.

## UI Behavior

The full-width cockpit card renders compact decision cards in a five-column responsive grid on wide screens and collapses cleanly on smaller screens. Pending items expose `同意` and `驳回`; completed states show concise status metadata.

The drawer reuses the same decision renderer, adds status filtering, and keeps the user in the cockpit context.

## Testing

Contract tests should verify:

- Smart decisions are placed outside the three-column cockpit panel and below the data board.
- The preview limit is 5.
- The drawer and status filters exist.
- Pending decisions render approve and reject actions.
- No source file calls `/dashboard/decisions` or `/pipeline/*` before the backend contract exists.
- Any future approval delegates experience persistence to the backend contract rather than writing directly to local templates.
