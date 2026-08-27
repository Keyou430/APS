# Cockpit Enterprise Overview Component Design

## Purpose

The cockpit `添加组件` action should add real enterprise overview components to the data board. These components summarize company-wide operating data such as business performance, headcount, operating efficiency, and risk/compliance status.

This is separate from cockpit `常用功能`. Shortcuts remain entry points; enterprise overview components are data widgets.

## Locked Decisions

- `添加组件` becomes an enterprise overview component picker for the cockpit data board.
- The first frontend aggregation layer exposes four component categories: `经营数据`, `人员统计`, `运营效率`, and `风险与合规`.
- Each component can be added only once. If a component is already visible, the picker shows it as already added and does not insert a duplicate.
- Missing backend fields render an empty or pending-integration state such as `暂无数据` or `待接入`.
- Production paths must not show demo samples when data is missing.
- The visual direction of the existing cockpit stays intact.
- The implementation stays in the legacy cockpit because `/` is currently hosted by the legacy workspace.
- Backend migration, Hermes provider work, and PR #9 are out of scope.

## Frontend Aggregation

The frontend owns a small aggregation layer that converts raw dashboard payload fields into cockpit component view models. The layer should return a consistent shape for every component:

- `id`: stable component id.
- `title`: visible component title.
- `metrics`: summary metrics shown in the card.
- `detail`: detail rows shown when the card expands.
- `empty`: true when no usable data exists.
- `emptyText`: user-facing empty state.

Initial component ids:

- `business`: enterprise business performance.
- `staff`: people and organization statistics.
- `operations`: operating efficiency.
- `risk`: risk and compliance.

The existing static cockpit KPI data can remain as display defaults only when it represents locally available configured dashboard content. It must not be used as a production fallback for missing backend data once the real aggregation input exists.

## Data Contract Guidance

The aggregation layer should first consume available dashboard data from `GET /dashboard`.

Current service fields include:

- `metrics`
- `todos`
- `calendarEvents`
- `notifications`
- `pipelines`
- `quickActions`
- `recentVisits`

Recommended backend evolution:

- Add explicit enterprise overview fields under `GET /dashboard`, for example `enterpriseOverview.business`, `enterpriseOverview.staff`, `enterpriseOverview.operations`, and `enterpriseOverview.risk`.
- Keep each section independently optional so a partially connected backend can still render other components.
- Return normalized metric objects with `label`, `value`, optional `trend`, optional `trendText`, and optional detail rows.

The frontend should treat absent or malformed sections as empty states, not as permission to synthesize demo data.

## UI Behavior

`添加组件` opens a compact picker anchored to the data board controls. The picker lists available enterprise overview components, their descriptions, and whether they are already on the board.

Selecting an available component inserts it into the cockpit data board layout. Removing a component only hides that widget from the board; it does not delete backend data.

The existing layout save/reset flow continues to persist component order through the dashboard layout contract when available and local state when offline.

## AI Service Memory

The AI service `经验方法` area should not display or maintain a frontend memory library.

Frontend behavior:

- Remove local `collab-ai-memory` state and persistence from the legacy AI workbench.
- Do not auto-ingest chat output into `state.ai.memoryCards`.
- Keep `经验方法` focused on user-managed templates.

Backend/Agent handoff:

- Agent workers may summarize useful experience into memory files later.
- That memory-file workflow is outside the frontend display surface.

## Testing

Contract and route tests should verify:

- `添加组件` is treated as an enterprise overview component picker, not a shortcut-entry modal.
- Component ids are unique in the cockpit layout.
- Missing enterprise overview data renders empty states without sample metrics.
- The four initial component categories are discoverable.
- `经验方法` does not render `记忆库`, `暂无记忆`, or memory-delete controls.
- Legacy AI workbench source no longer contains local `aiMemoryKey`, `state.ai.memoryCards`, or `saveAiMemory`.
